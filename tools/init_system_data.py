from __future__ import annotations

import hashlib
import json
import random
import re
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "backend" / "data"
MAP_DIR = DATA / "map"
DIARY_DIR = DATA / "diaries"
INDOOR_DIR = DATA / "indoor_nevigation"
COVER_DIR = DATA / "generated_covers"

for d in [MAP_DIR, DIARY_DIR, INDOOR_DIR, COVER_DIR]:
    d.mkdir(parents=True, exist_ok=True)

random.seed(20260510)


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def sha256_password(password: str, salt: str = "course-design"):
    return {"salt": salt, "hash": hashlib.sha256((salt + password).encode("utf-8")).hexdigest()}


def slug(text: str) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "_", text).strip("_")[:70]


# 1. 生成通用景区/校园内部道路图：节点 220 个、道路 409 条，服务设施超过 50 个。
def build_universal_map():
    nodes = []
    edges = []
    rows, cols = 11, 20
    service_cycle = [
        ("toilet", "公共卫生间"),
        ("supermarket", "便利超市"),
        ("restaurant_cn", "中餐厅"),
        ("restaurant_we", "西餐厅"),
        ("coffee", "咖啡休息区"),
        ("shop", "文创商店"),
        ("library", "游客阅读区"),
        ("canteen", "校园食堂"),
    ]
    scenic_cycle = ["gate", "landmark", "viewpoint", "museum", "garden", "lake", "square", "classroom", "dorm", "lab"]
    for r in range(rows):
        for c in range(cols):
            i = r * cols + c + 1
            if i % 4 == 0:
                ntype, prefix = service_cycle[(i // 4) % len(service_cycle)]
                name = f"{prefix}{i:03d}"
            else:
                ntype = scenic_cycle[i % len(scenic_cycle)]
                name = f"景观节点{i:03d}"
            nodes.append({
                "node_id": f"u{i:03d}",
                "name": name,
                "x": 80 + c * 52 + (r % 2) * 12,
                "y": 80 + r * 52,
                "type": ntype,
                "description": f"通用旅游道路图中的{name}，用于路线规划、设施查询与算法演示。",
                "is_indoor": i == 108,
                "indoor_building_id": "public_teaching_building" if i == 108 else None,
            })
    edge_id = 1
    for r in range(rows):
        for c in range(cols):
            idx = r * cols + c + 1
            if c + 1 < cols:
                allows = ["walk"]
                if r % 2 == 0:
                    allows.append("bike")
                if c % 7 == 0:
                    allows.append("cart")
                edges.append({
                    "edge_id": f"e{edge_id:04d}",
                    "source_id": f"u{idx:03d}",
                    "target_id": f"u{idx+1:03d}",
                    "length_meters": 45 + random.randint(0, 18),
                    "congestion": round(random.uniform(0.68, 1.0), 2),
                    "allows": allows,
                })
                edge_id += 1
            if r + 1 < rows:
                allows = ["walk"]
                if c % 3 == 0:
                    allows.append("bike")
                if c % 8 == 0:
                    allows.append("cart")
                edges.append({
                    "edge_id": f"e{edge_id:04d}",
                    "source_id": f"u{idx:03d}",
                    "target_id": f"u{idx+cols:03d}",
                    "length_meters": 50 + random.randint(0, 20),
                    "congestion": round(random.uniform(0.62, 1.0), 2),
                    "allows": allows,
                })
                edge_id += 1
    # 补充几条景区摆渡线，提高交通工具演示效果。
    for a, b in [("u001", "u020"), ("u021", "u040"), ("u101", "u120"), ("u181", "u200"), ("u050", "u170")]:
        edges.append({
            "edge_id": f"e{edge_id:04d}",
            "source_id": a,
            "target_id": b,
            "length_meters": 420 + random.randint(0, 90),
            "congestion": round(random.uniform(0.76, 0.96), 2),
            "allows": ["walk", "cart", "ebus"],
        })
        edge_id += 1
    data = {
        "map_name": "通用景区校园内部道路图",
        "width": 1180,
        "height": 720,
        "description": "包含 220 个道路/服务节点和 414 条道路边，所有目的地均可复用该内部图，符合题目中景区和校园内部可以一致的要求。",
        "nodes": nodes,
        "edges": edges,
    }
    write_json(MAP_DIR / "universal_tour_map.json", data)


# 2. 生成目的地元数据：至少 200 个。
def build_destinations():
    cities = ["北京", "上海", "杭州", "南京", "成都", "西安", "广州", "深圳", "苏州", "厦门", "重庆", "武汉", "青岛", "长沙", "天津", "哈尔滨", "昆明", "桂林", "大理", "洛阳"]
    themes = [
        ("历史文化", ["古建", "博物馆", "人文", "摄影"]),
        ("自然风光", ["山水", "徒步", "摄影", "亲子"]),
        ("校园参观", ["校园", "建筑", "研学", "图书馆"]),
        ("城市漫游", ["夜景", "美食", "街区", "购物"]),
        ("亲子休闲", ["亲子", "乐园", "休闲", "科普"]),
        ("艺术展览", ["艺术", "展览", "摄影", "咖啡"]),
        ("红色研学", ["研学", "历史", "纪念馆", "讲解"]),
        ("美食探索", ["美食", "夜市", "街区", "打卡"]),
    ]
    famous = [
        ("北京邮电大学", "校园参观", ["校园", "研学", "图书馆", "食堂"], "课程数据框架中已有示例校园，适合作为室内导航入口演示。"),
        ("故宫博物院", "历史文化", ["古建", "博物馆", "摄影", "人文"], "以中轴线、宫殿建筑和历史展陈为核心的热门景区。"),
        ("颐和园", "自然风光", ["山水", "古建", "摄影", "亲子"], "湖山园林与长廊建筑结合的经典路线规划场景。"),
        ("南锣鼓巷", "城市漫游", ["街区", "美食", "夜景", "购物"], "胡同街区与小吃店铺密集，适合美食与附近设施查询。"),
        ("天坛公园", "历史文化", ["古建", "公园", "摄影", "晨练"], "中轴线礼制建筑与城市绿地结合。"),
        ("清华大学", "校园参观", ["校园", "建筑", "研学", "图书馆"], "校园参观与研学路线的典型目的地。"),
        ("北京大学", "校园参观", ["校园", "湖景", "研学", "图书馆"], "校园湖景、历史建筑与学术氛围结合。"),
        ("上海外滩", "城市漫游", ["夜景", "摄影", "建筑", "街区"], "滨江建筑群与夜景路线适合多目标打卡。"),
        ("西湖风景区", "自然风光", ["山水", "摄影", "徒步", "美食"], "湖区环线、断桥与苏堤适合路径优化演示。"),
        ("秦始皇帝陵博物院", "历史文化", ["博物馆", "历史", "研学", "讲解"], "大型博物馆与展厅动线适合室内外路线说明。"),
    ]
    destinations = []
    for idx, (name, category, tags, desc) in enumerate(famous, 1):
        destinations.append({
            "id": f"dest_{idx:03d}",
            "name": name,
            "city": name[:2] if name.startswith("北京") else random.choice(cities),
            "category": category,
            "tags": tags,
            "rating": round(random.uniform(4.55, 4.95), 2),
            "views": random.randint(36000, 98000),
            "ticket_price": random.choice([0, 10, 20, 30, 40, 60, 80]),
            "recommended_hours": random.choice([2, 3, 4, 5, 6]),
            "map_file": "universal_tour_map.json",
            "description": desc,
        })
    i = len(destinations) + 1
    while i <= 200:
        city = random.choice(cities)
        category, tags = random.choice(themes)
        scenic_name = f"{city}{category}体验区{i:03d}"
        destinations.append({
            "id": f"dest_{i:03d}",
            "name": scenic_name,
            "city": city,
            "category": category,
            "tags": random.sample(tags + ["路线", "打卡", "讲解", "轻徒步", "亲子", "夜景"], 4),
            "rating": round(random.uniform(3.8, 4.9), 2),
            "views": random.randint(1200, 86000),
            "ticket_price": random.choice([0, 5, 10, 20, 30, 40, 60, 80, 120]),
            "recommended_hours": random.choice([1.5, 2, 3, 4, 5, 6]),
            "map_file": "universal_tour_map.json",
            "description": f"位于{city}的{category}主题目的地，标签覆盖{ '、'.join(tags) }，可用于推荐排序、路线规划和游记交流演示。",
        })
        i += 1
    write_json(DATA / "destinations.json", destinations)
    return destinations


# 3. 用户数据：管理员与普通用户。
def build_users():
    users = [
        {"username": "admin", "role": "admin", "password": sha256_password("admin"), "portrait": 1, "interests": ["历史文化", "校园", "美食"], "history": [], "created_at": 1710000000},
        {"username": "alice", "role": "user", "password": sha256_password("123456"), "portrait": 5, "interests": ["自然风光", "摄影", "美食"], "history": [], "created_at": 1710100000},
        {"username": "bob", "role": "user", "password": sha256_password("123456"), "portrait": 8, "interests": ["校园", "研学", "图书馆"], "history": [], "created_at": 1710200000},
    ]
    write_json(DATA / "users.json", users)


# 4. 美食数据：每个前 60 个目的地生成 5 条。
def build_foods(destinations):
    dishes = [
        ("老北京炸酱面", "京味", "胡同小馆"), ("宫廷奶酪", "甜品", "御茶点心铺"),
        ("西湖醋鱼", "杭帮菜", "湖畔餐厅"), ("龙井虾仁", "杭帮菜", "茶园小厨"),
        ("肉夹馍", "西北菜", "古城小吃"), ("担担面", "川菜", "巷口面馆"),
        ("广式早茶", "粤菜", "云吞茶楼"), ("海鲜沙茶面", "闽南菜", "码头小店"),
        ("校园鸡腿饭", "快餐", "学生食堂"), ("手冲咖啡", "咖啡", "蓝线咖啡"),
    ]
    foods = []
    fid = 1
    for d in destinations[:60]:
        sampled = random.sample(dishes, 5)
        for name, cuisine, restaurant in sampled:
            foods.append({
                "id": f"food_{fid:04d}",
                "destination_id": d["id"],
                "destination_name": d["name"],
                "name": name,
                "cuisine": cuisine,
                "restaurant": restaurant,
                "distance_meters": random.randint(80, 1600),
                "rating": round(random.uniform(3.8, 4.9), 2),
                "views": random.randint(500, 30000),
                "price_per_person": random.choice([18, 25, 35, 48, 65, 88, 120]),
                "description": f"{d['name']}附近推荐的{name}，适合路线结束后的就餐推荐。",
            })
            fid += 1
    write_json(DATA / "foods.json", foods)


# 5. 游记索引：复用现有 txt 文件，并补充部分示例正文。
def build_diaries(destinations):
    existing = sorted(DIARY_DIR.glob("*.txt"))
    sample_titles = [
        "蓝线穿过校园的午后", "一日看尽古建与湖光", "从美食街走到博物馆", "亲子路线里的慢旅行", "夜色中的城市漫游", "图书馆与银杏路", "山水之间的轻徒步", "展览结束后的咖啡时间", "研学旅行观察笔记", "周末打卡路线复盘",
    ]
    metas = []
    authors = ["alice", "bob", "admin"]
    # 为已有文件建立索引。
    for idx, path in enumerate(existing[:30], 1):
        dest = destinations[(idx - 1) % len(destinations)]
        title = path.stem.replace("_zip", "")[:36]
        metas.append({
            "id": f"diary_{idx:04d}",
            "title": title,
            "filename": path.name,
            "author": random.choice(authors),
            "destination_id": dest["id"],
            "destination_name": dest["name"],
            "views": random.randint(20, 9000),
            "rating": round(random.uniform(3.8, 4.9), 2),
            "rating_count": random.randint(1, 120),
            "created_at": 1710000000 + idx * 86400,
            "cover_url": "",
        })
    # 补充演示游记。
    start = len(metas) + 1
    for offset in range(24):
        idx = start + offset
        dest = destinations[offset % 20]
        title = sample_titles[offset % len(sample_titles)] + f" {offset + 1}"
        filename = f"{slug(title)}.txt"
        body = f"景点：{dest['name']}\n\n今天按照系统推荐的路线游览了{dest['name']}。从入口出发后，先经过安静的景观节点，再前往服务区补给。路线规划避开了拥挤路段，也把{ '、'.join(dest['tags'][:3]) }串联起来。最满意的是附近美食推荐，距离不远，评分也高。下一次我会尝试把必打卡点加入路线，让行程更个性化。\n\n关键词：{ ' '.join(dest['tags']) } 美食 路线 推荐 摄影"
        (DIARY_DIR / filename).write_text(body, encoding="utf-8")
        metas.append({
            "id": f"diary_{idx:04d}",
            "title": title,
            "filename": filename,
            "author": authors[offset % len(authors)],
            "destination_id": dest["id"],
            "destination_name": dest["name"],
            "views": random.randint(50, 12000),
            "rating": round(random.uniform(3.9, 4.95), 2),
            "rating_count": random.randint(2, 100),
            "created_at": 1712000000 + idx * 43200,
            "cover_url": "",
        })
    write_json(DATA / "diaries_meta.json", metas)


# 6. 如果原始室内导航不存在，则创建公共教学楼数据。
def ensure_indoor():
    file = INDOOR_DIR / "public_teaching_building.json"
    if file.exists():
        return
    nodes = [{"id": "entrance", "name": "教学楼入口", "floor": 1, "type": "entrance"}]
    for floor in range(1, 6):
        nodes.append({"id": f"elevator_{floor}", "name": f"{floor}楼电梯厅", "floor": floor, "type": "elevator"})
        nodes.append({"id": f"stair_{floor}", "name": f"{floor}楼楼梯间", "floor": floor, "type": "stair"})
        for room in range(1, 9):
            nodes.append({"id": f"r{floor}{room:02d}", "name": f"{floor}{room:02d}教室", "floor": floor, "type": "room"})
    conns = [
        {"from": "entrance", "to": "elevator_1", "distance": 18, "congestion_factor": 1.0, "description": "从入口直行到一楼电梯厅"},
        {"from": "entrance", "to": "stair_1", "distance": 15, "congestion_factor": 1.0, "description": "从入口右转到楼梯间"},
    ]
    for floor in range(1, 6):
        conns.append({"from": f"elevator_{floor}", "to": f"stair_{floor}", "distance": 12, "congestion_factor": 1.0, "description": "穿过楼层大厅"})
        for room in range(1, 9):
            hub = f"elevator_{floor}" if room <= 4 else f"stair_{floor}"
            conns.append({"from": hub, "to": f"r{floor}{room:02d}", "distance": 10 + room * 3, "congestion_factor": round(random.uniform(0.8, 1.2), 2), "description": "沿走廊前往教室"})
        if floor < 5:
            conns.append({"from": f"elevator_{floor}", "to": f"elevator_{floor+1}", "distance": 8, "congestion_factor": 1.15, "description": "乘坐电梯上/下楼"})
            conns.append({"from": f"stair_{floor}", "to": f"stair_{floor+1}", "distance": 12, "congestion_factor": 1.0, "description": "通过楼梯上/下楼"})
    write_json(file, {"building": {"id": "public_teaching_building", "name": "公共教学楼", "floors": 5}, "nodes": nodes, "connections": conns})


if __name__ == "__main__":
    build_universal_map()
    dests = build_destinations()
    build_users()
    build_foods(dests)
    build_diaries(dests)
    ensure_indoor()
    print("初始化完成：200 个目的地、通用道路图、用户、游记、美食与室内导航数据已写入 backend/data。")
