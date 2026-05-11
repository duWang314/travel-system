# 个性化旅游系统的设计与实现

作者：Manus AI

本项目基于用户提供的 `travel-system` 框架实现了一个可本地运行的个性化旅游系统。系统采用 **Python FastAPI 后端 + 原生 HTML/CSS/JavaScript 前端** 的轻量化架构，不依赖数据库服务，所有业务数据以 JSON 文件形式持久化，便于课程验收、离线演示与代码审阅。

系统围绕作业要求中的旅游推荐、地图路线规划、附近设施查询、游记管理与交流、旅游日记压缩、目的地封面提示词生成、室内导航、美食推荐和用户管理等功能展开实现。前端采用 **Apple Cinematic Minimalism（苹果产品发布会式极简主义）** 设计方向，通过黑白灰分层、单一蓝色交互、玻璃导航栏、低饱和背景与克制动画，突出系统功能和算法演示过程。

## 一、快速运行

请在项目根目录执行以下命令安装依赖并启动系统。

```bash
cd travel-system
pip install -r requirements.txt
python run.py
```

启动后访问：

```text
http://127.0.0.1:8000/
```

如果需要重新生成系统演示数据，可运行：

```bash
python tools/init_system_data.py
```

如果需要执行核心接口测试，可运行：

```bash
python tools/test_system.py
```

## 二、测试账号

系统初始化时内置了三个演示用户，用户中心与登录弹窗可以直接使用这些账号进行演示。

| 用户名 | 密码 | 用户偏好 |
|---|---|---|
| alice | 123456 | 历史文化、摄影、美食 |
| bob | 123456 | 校园参观、轻徒步、亲子 |
| carol | 123456 | 艺术展览、夜景、咖啡 |

## 三、主要功能模块

系统后端位于 `backend/app.py`，前端页面位于 `frontend/index.html`、`frontend/static/style.css` 与 `frontend/static/app.js`。数据初始化脚本位于 `tools/init_system_data.py`，接口测试脚本位于 `tools/test_system.py`。

| 模块 | 实现内容 | 对应文件 |
|---|---|---|
| 个性化旅游推荐 | 支持关键词、兴趣标签、分类、评分权重、热度权重和 Top-K 推荐。 | `backend/app.py`、`frontend/static/app.js` |
| 地图与路线规划 | 使用图结构表示道路网络，基于 Dijkstra 与优先队列计算最短路径，支持必打卡点分段拼接。 | `backend/app.py`、`backend/data/universal_map.json` |
| 附近设施查询 | 按道路图最短距离查找卫生间、超市、中餐厅、西餐厅、咖啡、食堂等服务设施。 | `backend/app.py` |
| 美食推荐 | 支持关键词与排序，综合考虑评分、热度、距离和标签匹配。 | `backend/data/foods.json` |
| 游记交流 | 支持游记列表、标题检索、正文 KMP 搜索、评分、阅读详情。 | `backend/data/diaries_meta.json`、`texts/` |
| 游记压缩 | 使用哈夫曼编码对游记正文进行压缩，展示压缩率、编码表样例与二进制预览。 | `backend/app.py` |
| 封面提示词 | 根据游记标题、目的地、标签和内容生成封面图提示词。 | `backend/app.py` |
| 室内导航 | 集成项目原有室内导航思路，实现房间列表、最短路径、转向提示与距离统计。 | `backend/app.py`、`indoor_navigation_algorithm.py` |
| 用户中心 | 支持登录、注册、用户偏好、收藏、最近访问记录和个人推荐摘要。 | `backend/data/users.json` |

## 四、算法覆盖说明

本项目保留了课程作业需要展示的数据结构与算法特征。推荐模块使用堆结构完成 Top-K 选择；路线规划模块使用图、邻接表、Dijkstra 与优先队列；游记检索模块使用 KMP 字符串匹配；游记压缩模块使用哈夫曼编码；附近设施查询复用图最短路径而非简单直线距离。

| 算法/数据结构 | 在系统中的用途 | 可演示入口 |
|---|---|---|
| Top-K 小顶堆 | 从 200 个目的地中选择推荐得分最高的条目，避免全量排序依赖。 | “个性化旅游推荐”区域 |
| 图与邻接表 | 表示景区/校园道路网络和节点连通关系。 | “地图路线规划”区域 |
| Dijkstra + 优先队列 | 计算起点、终点和必打卡点之间的最短路线。 | “规划路线”按钮 |
| 多段路径拼接 | 当用户设置必打卡点时，按起点—必打卡点—终点分段计算并拼接。 | “必打卡点”下拉框 |
| 道路距离设施排序 | 设施查询按道路最短距离排序，不采用直线距离。 | “查找附近设施”按钮 |
| KMP 字符串匹配 | 对游记正文进行关键词搜索，返回匹配次数和结果列表。 | “游记交流”区域 |
| 哈夫曼编码 | 对游记正文进行压缩并展示压缩率与编码表样例。 | “哈夫曼压缩”按钮 |

## 五、数据规模

初始化脚本会生成完整的演示数据，并将其保存在 `backend/data/` 与 `texts/` 目录下。系统启动时会自动检查关键数据是否存在，如不存在则执行初始化。

| 数据类型 | 数量 | 说明 |
|---|---:|---|
| 旅游目的地 | 200 | 含城市、分类、标签、评分、热度、建议游玩时长和坐标。 |
| 通用道路节点 | 220 | 用于 SVG 地图渲染、路线规划和附近设施查询。 |
| 美食条目 | 300 | 含菜品、餐厅、评分、热度、距离、价格和标签。 |
| 游记元数据 | 25 | 对应 `texts/` 目录中的游记正文文件。 |
| 演示用户 | 3 | 支持登录、偏好、收藏和最近访问。 |
| 室内导航房间 | 多个 | 支持教室、办公室、机房等室内节点路径规划。 |

## 六、接口测试

项目提供了端到端测试脚本 `tools/test_system.py`。当前已通过以下测试项：健康检查、登录、推荐 Top-K、地图数据、路线规划、附近设施、美食推荐、游记 KMP 搜索、哈夫曼压缩、室内房间、室内导航和用户资料接口。

运行结果摘要如下：

```text
[PASS] health
[PASS] login
[PASS] recommendation top-k
[PASS] map data
[PASS] route planning
[PASS] nearby facilities
[PASS] food recommendation
[PASS] diary kmp search
[PASS] huffman compression
[PASS] indoor rooms
[PASS] indoor navigation
[PASS] profile
全部核心功能接口测试通过。
```

更详细的前端可视化检查记录见 `TEST_REPORT_FRONTEND.md`。

## 七、目录结构

```text
travel-system/
├── backend/
│   ├── app.py
│   └── data/
│       ├── destinations.json
│       ├── diaries_meta.json
│       ├── foods.json
│       ├── universal_map.json
│       └── users.json
├── frontend/
│   ├── index.html
│   └── static/
│       ├── app.js
│       └── style.css
├── tools/
│   ├── init_system_data.py
│   ├── inspect_project.py
│   └── test_system.py
├── texts/
├── IMPLEMENTATION_PLAN.md
├── PROJECT_INSPECTION.txt
├── TEST_REPORT_FRONTEND.md
├── requirements.txt
└── run.py
```

## 八、验收建议

验收时建议按以下路径演示：首先运行 `python run.py` 并打开首页，展示 200 个目的地数据与推荐区域；随后调整兴趣标签或权重并刷新推荐；接着进入地图路线规划区域，设置起点、终点、必打卡点并点击“规划路线”；然后点击“查找附近设施”展示道路距离排序；之后进入游记交流区域，执行关键词搜索、阅读全文、哈夫曼压缩和评分；最后进入室内导航与用户中心，展示室内最短路径与用户偏好数据。

该演示路径可以覆盖系统的核心工程能力、前端交互、数据持久化和主要算法实现。
