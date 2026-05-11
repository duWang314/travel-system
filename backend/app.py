from __future__ import annotations

import base64
import hashlib
import heapq
import json
import math
import os
import random
import re
import time
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
MAP_DIR = DATA_DIR / "map"
DIARY_DIR = DATA_DIR / "diaries"
INDOOR_DIR = DATA_DIR / "indoor_nevigation"
PORTRAIT_DIR = DATA_DIR / "portraits"
COVER_DIR = DATA_DIR / "generated_covers"
FRONTEND_DIR = BASE_DIR.parent / "frontend"
STATIC_DIR = FRONTEND_DIR / "static"
COVER_DIR.mkdir(parents=True, exist_ok=True)

DESTINATIONS_FILE = DATA_DIR / "destinations.json"
USERS_FILE = DATA_DIR / "users.json"
DIARIES_META_FILE = DATA_DIR / "diaries_meta.json"
FOODS_FILE = DATA_DIR / "foods.json"

SESSIONS: Dict[str, str] = {}

app = FastAPI(title="个性化旅游系统", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if PORTRAIT_DIR.exists():
    app.mount("/portraits", StaticFiles(directory=str(PORTRAIT_DIR)), name="portraits")
if COVER_DIR.exists():
    app.mount("/covers", StaticFiles(directory=str(COVER_DIR)), name="covers")
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ----------------------------- 基础存储工具 -----------------------------

def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def sha256_password(password: str, salt: Optional[str] = None) -> Dict[str, str]:
    salt = salt or uuid.uuid4().hex[:16]
    digest = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return {"salt": salt, "hash": digest}


def verify_password(password: str, info: Dict[str, str]) -> bool:
    return sha256_password(password, info.get("salt", ""))["hash"] == info.get("hash")


def now_ts() -> int:
    return int(time.time())


def normalize_id(value: Any) -> str:
    return str(value)


def safe_filename(name: str) -> str:
    name = re.sub(r"[\\/:*?\"<>|]+", "_", name.strip())
    return name[:80] or f"diary_{uuid.uuid4().hex[:8]}"


# ----------------------------- 数据访问 -----------------------------

def load_destinations() -> List[Dict[str, Any]]:
    return read_json(DESTINATIONS_FILE, [])


def save_destinations(data: List[Dict[str, Any]]) -> None:
    write_json(DESTINATIONS_FILE, data)


def load_users() -> List[Dict[str, Any]]:
    return read_json(USERS_FILE, [])


def save_users(data: List[Dict[str, Any]]) -> None:
    write_json(USERS_FILE, data)


def load_diaries_meta() -> List[Dict[str, Any]]:
    return read_json(DIARIES_META_FILE, [])


def save_diaries_meta(data: List[Dict[str, Any]]) -> None:
    write_json(DIARIES_META_FILE, data)


def load_foods() -> List[Dict[str, Any]]:
    return read_json(FOODS_FILE, [])


def get_destination(dest_id: str) -> Dict[str, Any]:
    for item in load_destinations():
        if item["id"] == dest_id or item["name"] == dest_id:
            return item
    raise HTTPException(404, "目的地不存在")


def read_map_for_destination(dest_id: str) -> Dict[str, Any]:
    dest = get_destination(dest_id)
    map_file = MAP_DIR / dest.get("map_file", "")
    if not map_file.exists():
        candidates = sorted(MAP_DIR.glob("*.json"))
        if not candidates:
            raise HTTPException(404, "地图数据不存在")
        map_file = candidates[0]
    data = read_json(map_file, {})
    data["destination_id"] = dest["id"]
    data["destination_name"] = dest["name"]
    return data


def user_public(u: Dict[str, Any]) -> Dict[str, Any]:
    copied = {k: v for k, v in u.items() if k != "password"}
    copied["portrait_url"] = f"/portraits/{copied.get('portrait', 1)}.png"
    return copied


def require_user(authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    if not authorization:
        raise HTTPException(401, "请先登录")
    token = authorization.replace("Bearer", "").strip()
    username = SESSIONS.get(token)
    if not username:
        raise HTTPException(401, "登录已过期，请重新登录")
    for user in load_users():
        if user["username"] == username:
            return user
    raise HTTPException(401, "用户不存在")


def require_admin(user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    if user.get("role") != "admin":
        raise HTTPException(403, "需要管理员权限")
    return user


# ----------------------------- 推荐、搜索与 Top-K -----------------------------

def interest_match_score(item: Dict[str, Any], interests: List[str]) -> float:
    if not interests:
        return 0.0
    tags = set(item.get("tags", [])) | {item.get("category", "")}
    matched = len(tags & set(interests))
    return matched / max(1, len(set(interests)))


def weighted_destination_score(item: Dict[str, Any], interests: List[str], hot_weight: float, rating_weight: float, interest_weight: float) -> float:
    hot = min(float(item.get("views", 0)) / 10000.0, 1.0)
    rating = float(item.get("rating", 0)) / 5.0
    interest = interest_match_score(item, interests)
    return hot * hot_weight + rating * rating_weight + interest * interest_weight


def fuzzy_contains(text: str, q: str) -> bool:
    if not q:
        return True
    text = text.lower()
    q = q.lower()
    return q in text or all(ch in text for ch in q)


def top_k(items: List[Dict[str, Any]], k: int, score_func) -> List[Dict[str, Any]]:
    scored: List[Tuple[float, int, Dict[str, Any]]] = []
    for i, item in enumerate(items):
        score = float(score_func(item))
        wrapped = (score, i, item)
        if len(scored) < k:
            heapq.heappush(scored, wrapped)
        elif score > scored[0][0]:
            heapq.heapreplace(scored, wrapped)
    return [item for score, i, item in sorted(scored, key=lambda x: (-x[0], x[1]))]


# ----------------------------- 图算法 -----------------------------

def build_graph(map_data: Dict[str, Any], strategy: str = "distance", transport: str = "walk") -> Tuple[Dict[str, Dict[str, Dict[str, Any]]], Dict[str, Dict[str, Any]]]:
    nodes = {normalize_id(n.get("node_id")): n for n in map_data.get("nodes", [])}
    graph: Dict[str, Dict[str, Dict[str, Any]]] = {node_id: {} for node_id in nodes}
    for e in map_data.get("edges", []):
        s = normalize_id(e.get("source_id"))
        t = normalize_id(e.get("target_id"))
        if s not in nodes or t not in nodes:
            continue
        allows = set(e.get("allows", ["walk"]))
        if transport != "mixed":
            if transport == "bike" and "bike" not in allows:
                continue
            if transport in {"cart", "ebus"} and not ({"cart", "ebus", "bus"} & allows):
                continue
            if transport == "walk" and "walk" not in allows:
                continue
        length = max(0.1, float(e.get("length_meters", 1)))
        congestion = max(0.1, float(e.get("congestion", 1)))
        speed = 1.25
        if transport == "bike":
            speed = 4.0
        elif transport in {"cart", "ebus"}:
            speed = 5.5
        elif transport == "mixed":
            speed = 3.0 if ({"bike", "cart", "ebus", "bus"} & allows) else 1.25
        if strategy == "time":
            weight = length / (speed * congestion)
        else:
            weight = length
        edge_info = {
            "source_id": s,
            "target_id": t,
            "length_meters": length,
            "congestion": congestion,
            "allows": list(allows),
            "weight": weight,
        }
        graph.setdefault(s, {})[t] = edge_info
        graph.setdefault(t, {})[s] = {**edge_info, "source_id": t, "target_id": s}
    return graph, nodes


def dijkstra(graph: Dict[str, Dict[str, Dict[str, Any]]], start: str, end: Optional[str] = None) -> Tuple[Dict[str, float], Dict[str, Optional[str]], int]:
    dist = {node_id: math.inf for node_id in graph}
    prev: Dict[str, Optional[str]] = {node_id: None for node_id in graph}
    if start not in graph:
        return dist, prev, 0
    dist[start] = 0.0
    pq = [(0.0, start)]
    visited = set()
    while pq:
        d, u = heapq.heappop(pq)
        if u in visited:
            continue
        visited.add(u)
        if end is not None and u == end:
            break
        for v, edge in graph.get(u, {}).items():
            nd = d + float(edge["weight"])
            if nd < dist.get(v, math.inf):
                dist[v] = nd
                prev[v] = u
                heapq.heappush(pq, (nd, v))
    return dist, prev, len(visited)


def reconstruct_path(prev: Dict[str, Optional[str]], start: str, end: str) -> List[str]:
    if start == end:
        return [start]
    path = []
    cur: Optional[str] = end
    seen = set()
    while cur is not None and cur not in seen:
        seen.add(cur)
        path.append(cur)
        if cur == start:
            path.reverse()
            return path
        cur = prev.get(cur)
    return []


def route_segment(map_data: Dict[str, Any], start: str, end: str, strategy: str, transport: str) -> Dict[str, Any]:
    graph, nodes = build_graph(map_data, strategy=strategy, transport=transport)
    dist, prev, visited_count = dijkstra(graph, start, end)
    path = reconstruct_path(prev, start, end)
    if not path:
        return {"success": False, "message": "无法在当前交通方式和道路限制下到达目标", "path": []}
    distance = 0.0
    time_seconds = 0.0
    edges = []
    for a, b in zip(path, path[1:]):
        edge = graph[a][b]
        distance += edge["length_meters"]
        congestion = max(0.1, float(edge.get("congestion", 1)))
        allowed = set(edge.get("allows", []))
        speed = 1.25
        mode = "步行"
        if transport == "bike" or (transport == "mixed" and "bike" in allowed):
            speed, mode = 4.0, "自行车"
        elif transport in {"cart", "ebus"} or (transport == "mixed" and ({"cart", "ebus", "bus"} & allowed)):
            speed, mode = 5.5, "电瓶车"
        time_seconds += edge["length_meters"] / (speed * congestion)
        edges.append({"from": a, "to": b, "mode": mode, **edge})
    return {
        "success": True,
        "path": path,
        "path_nodes": [nodes[p] for p in path if p in nodes],
        "edges": edges,
        "distance_meters": round(distance, 2),
        "estimated_time_minutes": round(time_seconds / 60, 2),
        "visited_count": visited_count,
    }


# ----------------------------- KMP 与哈夫曼压缩 -----------------------------

def kmp_count(text: str, pattern: str) -> int:
    if not pattern:
        return 0
    nxt = [0] * len(pattern)
    j = 0
    for i in range(1, len(pattern)):
        while j > 0 and pattern[i] != pattern[j]:
            j = nxt[j - 1]
        if pattern[i] == pattern[j]:
            j += 1
        nxt[i] = j
    count = 0
    j = 0
    for ch in text:
        while j > 0 and ch != pattern[j]:
            j = nxt[j - 1]
        if ch == pattern[j]:
            j += 1
        if j == len(pattern):
            count += 1
            j = nxt[j - 1]
    return count


@dataclass(order=True)
class HuffmanNode:
    freq: int
    serial: int
    char: Optional[str] = None
    left: Optional["HuffmanNode"] = None
    right: Optional["HuffmanNode"] = None


def build_huffman_codes(text: str) -> Dict[str, str]:
    counter = Counter(text)
    if not counter:
        return {}
    heap: List[HuffmanNode] = []
    serial = 0
    for ch, freq in counter.items():
        heapq.heappush(heap, HuffmanNode(freq=freq, serial=serial, char=ch))
        serial += 1
    if len(heap) == 1:
        node = heap[0]
        return {node.char or "": "0"}
    while len(heap) > 1:
        a = heapq.heappop(heap)
        b = heapq.heappop(heap)
        heapq.heappush(heap, HuffmanNode(freq=a.freq + b.freq, serial=serial, left=a, right=b))
        serial += 1
    root = heap[0]
    codes: Dict[str, str] = {}

    def walk(node: HuffmanNode, prefix: str) -> None:
        if node.char is not None:
            codes[node.char] = prefix or "0"
            return
        if node.left:
            walk(node.left, prefix + "0")
        if node.right:
            walk(node.right, prefix + "1")

    walk(root, "")
    return codes


def huffman_compress(text: str) -> Dict[str, Any]:
    codes = build_huffman_codes(text)
    bitstring = "".join(codes[ch] for ch in text)
    padded = bitstring + "0" * ((8 - len(bitstring) % 8) % 8)
    raw_bytes = int(padded or "0", 2).to_bytes(max(1, len(padded) // 8), "big") if padded else b""
    encoded = base64.b64encode(raw_bytes).decode("ascii")
    original_bytes = len(text.encode("utf-8"))
    compressed_bytes = len(encoded.encode("utf-8")) + len(json.dumps(codes, ensure_ascii=False).encode("utf-8"))
    return {
        "codes": codes,
        "bit_length": len(bitstring),
        "padding": len(padded) - len(bitstring),
        "data": encoded,
        "original_bytes": original_bytes,
        "stored_bytes": compressed_bytes,
        "saving_ratio": round((1 - compressed_bytes / max(1, original_bytes)) * 100, 2),
        "tree_summary": sorted([{"char": k, "code": v, "freq": text.count(k)} for k, v in codes.items()], key=lambda x: (len(x["code"]), x["char"]))[:30],
    }


def huffman_decompress(payload: Dict[str, Any]) -> str:
    codes = payload.get("codes", {})
    reverse = {v: k for k, v in codes.items()}
    raw = base64.b64decode(payload.get("data", "")) if payload.get("data") else b""
    if not raw:
        return ""
    bitstring = bin(int.from_bytes(raw, "big"))[2:].zfill(len(raw) * 8)
    padding = int(payload.get("padding", 0))
    if padding:
        bitstring = bitstring[:-padding]
    out = []
    buf = ""
    for bit in bitstring[: int(payload.get("bit_length", len(bitstring)))]:
        buf += bit
        if buf in reverse:
            out.append(reverse[buf])
            buf = ""
    return "".join(out)


def extract_keywords(text: str, n: int = 8) -> List[str]:
    words = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z]{3,}", text)
    stop = {"我们", "这里", "这个", "一个", "可以", "以及", "进行", "景点", "旅游"}
    counter = Counter(w for w in words if w not in stop)
    return [w for w, c in counter.most_common(n)]


# ----------------------------- 请求模型 -----------------------------

class LoginBody(BaseModel):
    username: str
    password: str


class RegisterBody(BaseModel):
    username: str
    password: str
    portrait: int = 1
    interests: List[str] = []


class ProfileBody(BaseModel):
    portrait: Optional[int] = None
    interests: Optional[List[str]] = None


class PasswordBody(BaseModel):
    old_password: str
    new_password: str


class RouteBody(BaseModel):
    destination_id: str
    start_id: str
    end_id: str
    waypoints: List[str] = []
    strategy: str = "distance"
    transport: str = "walk"


class DiaryBody(BaseModel):
    title: str
    destination_id: str
    content: str


class RateBody(BaseModel):
    score: float


# ----------------------------- 页面入口 -----------------------------

@app.get("/", response_class=HTMLResponse)
def index() -> Any:
    index_file = FRONTEND_DIR / "index.html"
    if index_file.exists():
        return HTMLResponse(index_file.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>个性化旅游系统</h1><p>请先创建 frontend/index.html。</p>")


@app.get("/api/health")
def health() -> Dict[str, Any]:
    return {
        "ok": True,
        "destinations": len(load_destinations()),
        "users": len(load_users()),
        "diaries": len(load_diaries_meta()),
        "foods": len(load_foods()),
    }


@app.get("/api/algorithm-notes")
def algorithm_notes() -> Dict[str, Any]:
    return {
        "旅游推荐": "加权评分 + 小顶堆 Top-K，时间复杂度 O(n log k)。",
        "目的地查询": "哈希索引辅助精确匹配，模糊查询后多关键字排序。",
        "路线规划": "道路图邻接表 + Dijkstra 优先队列，支持距离/时间/交通工具限制。",
        "场所查询": "从当前位置在道路图上运行 Dijkstra，以路径距离而非直线距离排序。",
        "室内导航": "室内节点图 + Dijkstra，从入口到房间生成步骤说明。",
        "游记精确查询": "标题哈希索引；正文全文搜索使用 KMP。",
        "游记压缩": "Unicode 字符级哈夫曼编码，保存码表和压缩二进制串。",
        "美食推荐": "模糊查找 + 热度/评分/距离加权 Top-K。",
    }


# ----------------------------- 用户系统 -----------------------------

@app.post("/api/register")
def register(body: RegisterBody) -> Dict[str, Any]:
    users = load_users()
    username = body.username.strip()
    if not username or len(username) < 2:
        raise HTTPException(400, "用户名至少需要 2 个字符")
    if any(u["username"] == username for u in users):
        raise HTTPException(400, "用户名已存在")
    pwd = sha256_password(body.password)
    user = {
        "username": username,
        "role": "user",
        "password": pwd,
        "portrait": min(max(int(body.portrait), 1), 24),
        "interests": body.interests[:8],
        "history": [],
        "created_at": now_ts(),
    }
    users.append(user)
    save_users(users)
    token = uuid.uuid4().hex
    SESSIONS[token] = username
    return {"token": token, "user": user_public(user)}


@app.post("/api/login")
def login(body: LoginBody) -> Dict[str, Any]:
    for user in load_users():
        if user["username"] == body.username and verify_password(body.password, user.get("password", {})):
            token = uuid.uuid4().hex
            SESSIONS[token] = user["username"]
            return {"token": token, "user": user_public(user)}
    raise HTTPException(401, "账号或密码错误")


@app.get("/api/me")
def me(user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return user_public(user)


@app.put("/api/me")
def update_me(body: ProfileBody, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    users = load_users()
    for u in users:
        if u["username"] == user["username"]:
            if body.portrait is not None:
                u["portrait"] = min(max(int(body.portrait), 1), 24)
            if body.interests is not None:
                u["interests"] = body.interests[:8]
            save_users(users)
            return user_public(u)
    raise HTTPException(404, "用户不存在")


@app.post("/api/me/password")
def change_password(body: PasswordBody, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    users = load_users()
    for u in users:
        if u["username"] == user["username"]:
            if not verify_password(body.old_password, u.get("password", {})):
                raise HTTPException(400, "原密码错误")
            u["password"] = sha256_password(body.new_password)
            save_users(users)
            return {"ok": True}
    raise HTTPException(404, "用户不存在")


@app.get("/api/admin/users")
def admin_users(_: Dict[str, Any] = Depends(require_admin)) -> List[Dict[str, Any]]:
    return [user_public(u) for u in load_users()]


@app.delete("/api/admin/users/{username}")
def admin_delete_user(username: str, _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    if username == "admin":
        raise HTTPException(400, "不能删除管理员 admin")
    users = [u for u in load_users() if u["username"] != username]
    save_users(users)
    return {"ok": True}


# ----------------------------- 目的地推荐与查询 -----------------------------

@app.get("/api/destinations")
def list_destinations(
    q: str = "",
    category: str = "",
    interests: str = "",
    hot_weight: float = 0.4,
    rating_weight: float = 0.4,
    interest_weight: float = 0.2,
    limit: int = 10,
    sort: str = "weighted",
) -> Dict[str, Any]:
    items = load_destinations()
    interest_list = [x.strip() for x in interests.split(",") if x.strip()]
    if q:
        items = [d for d in items if fuzzy_contains(" ".join([d.get("name", ""), d.get("category", ""), " ".join(d.get("tags", [])), d.get("description", "")]), q)]
    if category:
        items = [d for d in items if d.get("category") == category]

    def score(d: Dict[str, Any]) -> float:
        if sort == "hot":
            return float(d.get("views", 0))
        if sort == "rating":
            return float(d.get("rating", 0))
        return weighted_destination_score(d, interest_list, hot_weight, rating_weight, interest_weight)

    k = max(1, min(int(limit), 100))
    result = top_k(items, k, score)
    for d in result:
        d["recommend_score"] = round(score(d), 4)
    return {
        "items": result,
        "total_matched": len(items),
        "algorithm": f"小顶堆 Top-{k}，未对全部 {len(items)} 条记录完全排序",
    }


@app.get("/api/destinations/{dest_id}")
def destination_detail(dest_id: str, user: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    dest = get_destination(dest_id)
    destinations = load_destinations()
    for d in destinations:
        if d["id"] == dest["id"]:
            d["views"] = int(d.get("views", 0)) + 1
            dest = d
            break
    save_destinations(destinations)
    return dest


@app.get("/api/map/{dest_id}")
def map_data(dest_id: str) -> Dict[str, Any]:
    data = read_map_for_destination(dest_id)
    return data


@app.post("/api/route")
def plan_route(body: RouteBody, user: Optional[Dict[str, Any]] = Depends(lambda authorization=Header(default=None): None)) -> Dict[str, Any]:
    map_data = read_map_for_destination(body.destination_id)
    checkpoints = [body.start_id] + [w for w in body.waypoints if w] + [body.end_id]
    full_path: List[str] = []
    full_edges: List[Dict[str, Any]] = []
    total_distance = 0.0
    total_time = 0.0
    visited = 0
    for a, b in zip(checkpoints, checkpoints[1:]):
        seg = route_segment(map_data, normalize_id(a), normalize_id(b), body.strategy, body.transport)
        if not seg.get("success"):
            return seg
        part = seg["path"]
        full_path.extend(part if not full_path else part[1:])
        full_edges.extend(seg.get("edges", []))
        total_distance += float(seg.get("distance_meters", 0))
        total_time += float(seg.get("estimated_time_minutes", 0))
        visited += int(seg.get("visited_count", 0))
    nodes = {normalize_id(n.get("node_id")): n for n in map_data.get("nodes", [])}
    return {
        "success": True,
        "strategy": body.strategy,
        "transport": body.transport,
        "checkpoints": checkpoints,
        "path": full_path,
        "path_nodes": [nodes[p] for p in full_path if p in nodes],
        "edges": full_edges,
        "distance_meters": round(total_distance, 2),
        "estimated_time_minutes": round(total_time, 2),
        "visited_count": visited,
        "algorithm": "Dijkstra + 优先队列；必打卡点按顺序分段规划后拼接。",
    }


@app.get("/api/facilities/{dest_id}")
def nearby_facilities(dest_id: str, node_id: str, type: str = "", limit: int = 10) -> Dict[str, Any]:
    map_data = read_map_for_destination(dest_id)
    graph, nodes = build_graph(map_data, strategy="distance", transport="walk")
    start = normalize_id(node_id)
    if start not in graph:
        raise HTTPException(404, "起点节点不存在")
    dist, _, visited = dijkstra(graph, start)
    service_types = {"toilet", "supermarket", "restaurant_cn", "restaurant_we", "library", "canteen", "coffee", "shop", "restaurant", "hotel", "service"}
    candidates = []
    for nid, node in nodes.items():
        ntype = node.get("type", "")
        if type and ntype != type:
            continue
        if not type and ntype not in service_types:
            continue
        if math.isfinite(dist.get(nid, math.inf)) and nid != start:
            candidates.append({**node, "node_id": nid, "path_distance_meters": round(dist[nid], 2)})
    candidates.sort(key=lambda x: x["path_distance_meters"])
    return {
        "items": candidates[: max(1, min(limit, 50))],
        "total_matched": len(candidates),
        "visited_count": visited,
        "algorithm": "从当前节点运行 Dijkstra，以道路最短路径距离排序，不使用直线距离。",
    }


# ----------------------------- 美食推荐 -----------------------------

@app.get("/api/foods")
def foods(destination_id: str = "", q: str = "", cuisine: str = "", sort: str = "weighted", limit: int = 10) -> Dict[str, Any]:
    items = load_foods()
    if destination_id:
        items = [f for f in items if f.get("destination_id") == destination_id]
    if cuisine:
        items = [f for f in items if f.get("cuisine") == cuisine]
    if q:
        items = [f for f in items if fuzzy_contains(" ".join([f.get("name", ""), f.get("cuisine", ""), f.get("restaurant", "")]), q)]

    def score(f: Dict[str, Any]) -> float:
        if sort == "hot":
            return float(f.get("views", 0))
        if sort == "rating":
            return float(f.get("rating", 0))
        if sort == "distance":
            return -float(f.get("distance_meters", 99999))
        return float(f.get("views", 0)) / 10000 * 0.35 + float(f.get("rating", 0)) / 5 * 0.45 + (1 / (1 + float(f.get("distance_meters", 999)) / 500)) * 0.2

    result = top_k(items, max(1, min(limit, 50)), score)
    for item in result:
        item["recommend_score"] = round(score(item), 4)
    return {"items": result, "total_matched": len(items), "algorithm": "模糊查找 + 小顶堆 Top-K 加权排序。"}


# ----------------------------- 游记管理与交流 -----------------------------

@app.get("/api/diaries")
def diaries(q: str = "", destination_id: str = "", title: str = "", sort: str = "hot") -> Dict[str, Any]:
    metas = load_diaries_meta()
    title_index = {m["title"]: m for m in metas}
    if title:
        item = title_index.get(title)
        return {"items": [item] if item else [], "algorithm": "标题哈希表精确查找。"}
    results = []
    for m in metas:
        if destination_id and m.get("destination_id") != destination_id:
            continue
        path = DIARY_DIR / m.get("filename", "")
        content = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
        if q:
            matched = fuzzy_contains(m.get("title", ""), q) or fuzzy_contains(content, q)
            if not matched:
                continue
            m = {**m, "kmp_hits": kmp_count(content, q), "snippet": make_snippet(content, q)}
        results.append(m)
    if sort == "rating":
        results.sort(key=lambda x: float(x.get("rating", 0)), reverse=True)
    elif sort == "destination":
        results.sort(key=lambda x: x.get("destination_name", ""))
    else:
        results.sort(key=lambda x: int(x.get("views", 0)), reverse=True)
    return {"items": results, "total_matched": len(results), "algorithm": "正文搜索使用 KMP 统计命中，结果可按热度或评分排序。"}


def make_snippet(text: str, q: str, size: int = 80) -> str:
    if not q:
        return text[:size]
    idx = text.lower().find(q.lower())
    if idx < 0:
        return text[:size]
    start = max(0, idx - size // 2)
    end = min(len(text), idx + len(q) + size // 2)
    return text[start:end]


@app.get("/api/diaries/{diary_id}")
def diary_detail(diary_id: str) -> Dict[str, Any]:
    metas = load_diaries_meta()
    for m in metas:
        if m["id"] == diary_id:
            m["views"] = int(m.get("views", 0)) + 1
            save_diaries_meta(metas)
            path = DIARY_DIR / m.get("filename", "")
            content = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
            return {**m, "content": content}
    raise HTTPException(404, "游记不存在")


@app.post("/api/diaries")
def create_diary(body: DiaryBody, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    dest = get_destination(body.destination_id)
    title = safe_filename(body.title)
    filename = f"{title}.txt"
    path = DIARY_DIR / filename
    if path.exists():
        filename = f"{title}_{uuid.uuid4().hex[:6]}.txt"
        path = DIARY_DIR / filename
    path.write_text(f"景点：{dest['name']}\n\n{body.content}", encoding="utf-8")
    meta = {
        "id": uuid.uuid4().hex[:12],
        "title": body.title,
        "filename": filename,
        "author": user["username"],
        "destination_id": dest["id"],
        "destination_name": dest["name"],
        "views": 0,
        "rating": 0,
        "rating_count": 0,
        "created_at": now_ts(),
        "cover_url": "",
    }
    metas = load_diaries_meta()
    metas.append(meta)
    save_diaries_meta(metas)
    return meta


@app.delete("/api/diaries/{diary_id}")
def delete_diary(diary_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    metas = load_diaries_meta()
    kept = []
    removed = None
    for m in metas:
        if m["id"] == diary_id:
            if user.get("role") != "admin" and m.get("author") != user.get("username"):
                raise HTTPException(403, "只能删除自己的游记")
            removed = m
        else:
            kept.append(m)
    if not removed:
        raise HTTPException(404, "游记不存在")
    save_diaries_meta(kept)
    return {"ok": True}


@app.post("/api/diaries/{diary_id}/rate")
def rate_diary(diary_id: str, body: RateBody) -> Dict[str, Any]:
    metas = load_diaries_meta()
    for m in metas:
        if m["id"] == diary_id:
            old_rating = float(m.get("rating", 0))
            old_count = int(m.get("rating_count", 0))
            score = min(max(float(body.score), 1.0), 5.0)
            m["rating"] = round((old_rating * old_count + score) / (old_count + 1), 2)
            m["rating_count"] = old_count + 1
            save_diaries_meta(metas)
            return m
    raise HTTPException(404, "游记不存在")


@app.post("/api/diaries/{diary_id}/compress")
def compress_diary(diary_id: str) -> Dict[str, Any]:
    for m in load_diaries_meta():
        if m["id"] == diary_id:
            path = DIARY_DIR / m.get("filename", "")
            if not path.exists():
                raise HTTPException(404, "游记正文不存在")
            text = path.read_text(encoding="utf-8", errors="ignore")
            payload = huffman_compress(text)
            zip_file = path.with_name(path.stem + "_zip.txt")
            zip_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return {"ok": True, "zip_file": zip_file.name, **payload, "algorithm": "哈夫曼编码，无损压缩。"}
    raise HTTPException(404, "游记不存在")


@app.get("/api/diaries/{diary_id}/decompress")
def decompress_diary(diary_id: str) -> Dict[str, Any]:
    for m in load_diaries_meta():
        if m["id"] == diary_id:
            path = DIARY_DIR / m.get("filename", "")
            zip_file = path.with_name(path.stem + "_zip.txt")
            if not zip_file.exists():
                raise HTTPException(404, "请先压缩游记")
            payload = json.loads(zip_file.read_text(encoding="utf-8"))
            return {"content": huffman_decompress(payload), "zip_file": zip_file.name}
    raise HTTPException(404, "游记不存在")


@app.post("/api/diaries/{diary_id}/cover")
def generate_cover(diary_id: str) -> Dict[str, Any]:
    metas = load_diaries_meta()
    for m in metas:
        if m["id"] == diary_id:
            path = DIARY_DIR / m.get("filename", "")
            text = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else m.get("title", "")
            keywords = extract_keywords(text)
            prompt = f"以{m.get('destination_name')}为主题，突出{','.join(keywords[:5])}，生成苹果风格极简旅游日记封面。"
            svg_name = f"{diary_id}.svg"
            svg_path = COVER_DIR / svg_name
            svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="800" viewBox="0 0 1200 800">
<defs><linearGradient id="g" x1="0" x2="1" y1="0" y2="1"><stop stop-color="#f5f5f7"/><stop offset="1" stop-color="#dfe9f8"/></linearGradient><filter id="s"><feDropShadow dx="0" dy="22" stdDeviation="24" flood-color="#000" flood-opacity="0.18"/></filter></defs>
<rect width="1200" height="800" fill="url(#g)"/>
<path d="M110 580 C260 380, 420 650, 590 430 S880 210, 1080 420" fill="none" stroke="#0071e3" stroke-width="10" stroke-linecap="round" opacity="0.8"/>
<circle cx="590" cy="430" r="28" fill="#0071e3"/>
<rect x="220" y="150" width="760" height="470" rx="34" fill="white" filter="url(#s)"/>
<text x="600" y="315" font-family="Helvetica, Arial, sans-serif" font-size="56" font-weight="700" text-anchor="middle" fill="#1d1d1f">{m.get('title')}</text>
<text x="600" y="385" font-family="Helvetica, Arial, sans-serif" font-size="28" text-anchor="middle" fill="#6e6e73">{m.get('destination_name')}</text>
<text x="600" y="470" font-family="Helvetica, Arial, sans-serif" font-size="24" text-anchor="middle" fill="#86868b">{' · '.join(keywords[:6])}</text>
</svg>'''
            svg_path.write_text(svg, encoding="utf-8")
            m["cover_url"] = f"/covers/{svg_name}"
            m["cover_prompt"] = prompt
            save_diaries_meta(metas)
            return {"cover_url": m["cover_url"], "prompt": prompt, "keywords": keywords}
    raise HTTPException(404, "游记不存在")


# ----------------------------- 室内导航 -----------------------------

@app.get("/api/indoor/{building_id}/rooms")
def indoor_rooms(building_id: str) -> Dict[str, Any]:
    file = INDOOR_DIR / f"{building_id}.json"
    if not file.exists():
        raise HTTPException(404, "该建筑暂无室内导航数据")
    data = read_json(file, {})
    return {"building": data.get("building"), "rooms": [n for n in data.get("nodes", []) if n.get("type") == "room"]}


@app.post("/api/indoor/{building_id}/navigate")
def indoor_navigate(building_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    file = INDOOR_DIR / f"{building_id}.json"
    if not file.exists():
        raise HTTPException(404, "该建筑暂无室内导航数据")
    data = read_json(file, {})
    room_id = payload.get("room_id")
    nodes = {n["id"]: n for n in data.get("nodes", [])}
    graph: Dict[str, Dict[str, Dict[str, Any]]] = {nid: {} for nid in nodes}
    for c in data.get("connections", []):
        a, b = c.get("from"), c.get("to")
        if a not in graph or b not in graph:
            continue
        dist = float(c.get("distance", 1)) * float(c.get("congestion_factor", 1))
        graph[a][b] = {"weight": dist, "distance": c.get("distance", 1), "description": c.get("description", "")}
        graph[b][a] = {"weight": dist, "distance": c.get("distance", 1), "description": c.get("description", "")}
    dist, prev, visited = dijkstra(graph, "entrance", room_id)
    path = reconstruct_path(prev, "entrance", room_id)
    if not path:
        return {"success": False, "message": "无法到达该房间"}
    steps = []
    for i, (a, b) in enumerate(zip(path, path[1:]), 1):
        edge = graph[a][b]
        steps.append({
            "step": i,
            "from": nodes[a]["name"],
            "to": nodes[b]["name"],
            "floor_change": nodes[a].get("floor") != nodes[b].get("floor"),
            "description": edge.get("description") or f"从{nodes[a]['name']}前往{nodes[b]['name']}",
            "distance": edge.get("distance", 0),
        })
    return {
        "success": True,
        "building": data.get("building"),
        "destination": nodes.get(room_id),
        "path": path,
        "path_nodes": [nodes[p] for p in path],
        "steps": steps,
        "total_weight": round(dist.get(room_id, 0), 2),
        "visited_count": visited,
        "algorithm": "室内图 Dijkstra，从大门入口到目标房间。",
    }


@app.exception_handler(HTTPException)
def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
