import osmnx as ox
import networkx as nx
import json
import os
import pandas as pd

# 配置：打印日志，开启缓存（避免重复请求被封禁IP）
ox.settings.log_console = True
ox.settings.use_cache = True

# 兜底坐标字典（如果自动搜索名字彻底失败，会尝试读取这里的中心经纬度）
MANUAL_COORDS = {
    # 方案 A (搜名字) 必败的地点，直接强制启用坐标法：
    "八达岭长城": (40.3546, 116.0022),
    "南锣鼓巷": (39.9388, 116.4027),  # 胡同片区，不规则，用中心向外抓取最好
    "什刹海": (39.9383, 116.3899),  # 水域复杂，用坐标向外扩张覆盖最好

    # 郊区校园极大，强制坐标+覆盖保证道路不缺失：
    "北京航空航天大学（沙河校区）": (40.1601, 116.2883),
    "北京邮电大学（沙河校区）": (40.1585, 116.2801)
}


def process_destination(place_name, dist=800):
    print(f"\n======================================")
    print(f"🚀 正在处理: {place_name}")
    print(f"======================================")

    # 感兴趣的标签（建筑物、基础设施等）
    tags = {
        'building': True,
        'amenity': ['toilets', 'cafe', 'fast_food', 'restaurant', 'library', 'university'],
        'tourism': ['museum', 'attraction', 'viewpoint'],
        'shop': ['convenience', 'supermarket']
    }

    G = None
    pois = None
    crs = None

    try:
        # 尝试方案 A: 严格按区域多边形边界获取
        print("[尝试方案A]: 请求闭合多边形边界数据...")
        query = f"{place_name}, 北京市, 中国"
        G = ox.graph_from_place(query, network_type='all')
        pois = ox.features_from_place(query, tags=tags)

    except Exception as e:
        print(f"⚠️ 方案A失败，多边形匹配错误: {e}")
        print("[尝试方案B]: 降级通过中心坐标 + 提取半径进行获取...")

        try:
            # 尝试通过地名获取经纬度
            if place_name in MANUAL_COORDS:
                center_point = MANUAL_COORDS[place_name]
                print(f"    -> 触发兜底字典，使用强制坐标 {center_point}")
            else:
                center_point = ox.geocode(f"{place_name}, 北京市, 中国")
                print(f"    -> 成功将名称解析为中心坐标 {center_point}")

            # 以目标地点中心经纬度向外辐射 dist 米建立边界圆，获取路网
            G = ox.graph_from_point(center_point, dist=dist, network_type='all')
            # 以同范围抓取建筑及服务设施
            pois = ox.features_from_point(center_point, tags=tags, dist=dist)

        except Exception as e2:
            print(f"❌ 方案B也失败。此地点抓取彻底中断，跳过该地点。错误: {e2}")
            return None

    # 如果运行到这儿，图已经抓取到了，后续转为纯数据对象处理
    G_projected = ox.project_graph(G)
    nodes_data = []
    edges_data = []

    # 1. 抽取所有的拓扑节点（交通路口 / 通道路口）
    for node_id, data in G.nodes(data=True):
        nodes_data.append({
            "node_id": node_id,
            "name": "路口",
            "lon": round(data.get('x'), 5),
            "lat": round(data.get('y'), 5),
            "type": "intersection",
            "is_indoor": False,
            "indoor_info": {}
        })

    poi_added = 0
    # 2. 抽取 POI，将其处理后添加到 Nodes 里
    if pois is not None and not pois.empty:
        # 转投影取建筑真实中心点，防止是不规则多边形导致的位置偏移
        pois_projected = pois.to_crs(G_projected.graph['crs'])
        pois['centroid'] = pois_projected.centroid.to_crs(4326)  # 换回正常经纬度坐标

        for idx, row in pois.iterrows():
            name = row.get('name')
            if not isinstance(name, str):
                name = row.get('name:zh', "未命名建筑")

                # 这里的设施推断也要加上非空判断
                facility_type = "facility"
                if 'amenity' in row and not pd.isna(row['amenity']):
                    facility_type = row["amenity"]
                elif 'tourism' in row and not pd.isna(row['tourism']):
                    facility_type = row["tourism"]

                nodes_data.append({
                    "node_id": f"poi_{idx}",
                    "name": str(name),  # 强转为安全字符串
                    "lon": round(row['centroid'].x, 5),
                    "lat": round(row['centroid'].y, 5),
                    "type": str(facility_type),  # 此时就不会出现 "nan" 了
                    "is_indoor": False,
                    "indoor_info": {}
                })

            # --- 接驳边 --- 建筑物接入路网虚拟通道
            try:
                # 寻找路网图中离建筑物重心最近的一个节点，创建接入路径
                nearest_node = ox.distance.nearest_nodes(G, row['centroid'].x, row['centroid'].y)
                edges_data.append({
                    "source_id": f"poi_{idx}",
                    "target_id": nearest_node,
                    "length_meters": 5.0,  # 建筑走到路口固定赋予一个短距离5米
                    "allows": ["walk", "bike"],
                    "congestion": 1.0,
                    "is_stairs": False
                })
            except Exception:
                pass
            poi_added += 1

    # 3. 抽取核心路网 (边 / Edge)
    for u, v, key, data in G.edges(keys=True, data=True):
        hw_type = data.get('highway', 'path')

        allows = ["walk"]
        # 通过标签规则推断自行车与电车是否可进入
        if "cycleway" in str(hw_type) or "residential" in str(hw_type) or "service" in str(
                hw_type) or "unclassified" in str(hw_type):
            allows.append("bike")

        # ------------------ 新增的几何弯曲点提取 ------------------
        geometry_pts = []
        if 'geometry' in data:
            # geometry 是包含路上所有拐点经纬度的序列
            # 我们直接转为 [lat, lon] 的格式，方便前端 Leaflet 连线
            for lon, lat in data['geometry'].coords:
                geometry_pts.append([round(lat, 5), round(lon, 5)])
        # --------------------------------------------------------

        edges_data.append({
            "source_id": u,
            "target_id": v,
            "length_meters": round(data.get('length', 10.0), 2),
            "allows": allows,
            "congestion": 1.0,
            "is_stairs": "steps" in str(hw_type),  # 在地图标为 steps 楼梯的路段会生效
            "geometry_pts": geometry_pts
        })

    print(
        f"✅ [{place_name}] 构建图成功: {len(nodes_data)} 个节点(其中建筑 {poi_added} 个)，{len(edges_data)} 条连接道路。")

    # 将字典数据抛入 json 持久化保存
    final_dict = {
        "destination_name": place_name,
        "nodes": nodes_data,
        "edges": edges_data
    }

    os.makedirs('map_data', exist_ok=True)
    with open(f"map_data/{place_name}.json", "w", encoding="utf-8") as f:
        json.dump(final_dict, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    # 这是你在开头注中列出的 15 个要求地点
    destinations = [
        "八达岭长城",
        "天坛公园",
        "圆明园遗址",  # OSM官方名去掉了公园俩字
        "国家体育场",  # 即鸟巢，OSM官方名为国家体育场
        "国家游泳中心",  # 即水立方，OSM官方名为国家游泳中心
        "南锣鼓巷",
        "什刹海",
        "北京大学",
        "北京航空航天大学（沙河校区）",
        "北京师范大学",
        "北京邮电大学（沙河校区）"
    ]

    # 开始批量跑数据（对于偏远且庞大的沙河高教园区，或者大型自然水系，把抓取半径从800扩展到1000米）
    for dest in destinations:
        process_destination(dest, dist=1000)