from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient
from backend.app import app

client = TestClient(app)


def check(name: str, condition: bool, detail=""):
    if not condition:
        raise AssertionError(f"{name} failed: {detail}")
    print(f"[PASS] {name}")


def main():
    health = client.get("/api/health").json()
    check("health", health["ok"] and health["destinations"] >= 200, health)

    login = client.post("/api/login", json={"username": "admin", "password": "admin"})
    check("login", login.status_code == 200, login.text)
    token = login.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    rec = client.get("/api/destinations", params={"interests": "校园,美食,历史文化", "limit": 10}).json()
    check("recommendation top-k", len(rec["items"]) == 10 and "堆" in rec["algorithm"], rec)
    dest_id = rec["items"][0]["id"]

    map_data = client.get(f"/api/map/{dest_id}").json()
    check("map data", len(map_data["nodes"]) >= 200 and len(map_data["edges"]) >= 200, (len(map_data["nodes"]), len(map_data["edges"])))
    start = map_data["nodes"][0]["node_id"]
    end = map_data["nodes"][80]["node_id"]

    route = client.post("/api/route", json={"destination_id": dest_id, "start_id": start, "end_id": end, "waypoints": [], "strategy": "distance", "transport": "mixed"}).json()
    check("route planning", route["success"] and len(route["path"]) >= 2 and route["distance_meters"] > 0, route)

    facilities = client.get(f"/api/facilities/{dest_id}", params={"node_id": start, "type": "toilet", "limit": 5}).json()
    check("nearby facilities", len(facilities["items"]) > 0, facilities)

    foods = client.get("/api/foods", params={"destination_id": dest_id, "limit": 5}).json()
    check("food recommendation", len(foods["items"]) <= 5 and foods["algorithm"], foods)

    diaries = client.get("/api/diaries", params={"q": "路线", "limit": 5}).json()
    check("diary kmp search", len(diaries["items"]) > 0 and "KMP" in diaries["algorithm"], diaries)
    diary_id = diaries["items"][0]["id"]

    compress = client.post(f"/api/diaries/{diary_id}/compress", headers=headers).json()
    check("huffman compression", compress["original_bytes"] > 0 and compress["stored_bytes"] > 0, compress)

    rooms = client.get("/api/indoor/public_teaching_building/rooms").json()
    check("indoor rooms", len(rooms["rooms"]) > 0, rooms)
    room_id = rooms["rooms"][0]["id"]
    indoor = client.post("/api/indoor/public_teaching_building/navigate", json={"room_id": room_id}).json()
    check("indoor navigation", indoor["success"] and len(indoor["path"]) >= 2, indoor)

    me = client.get("/api/me", headers=headers).json()
    check("profile", me["username"] == "admin", me)

    print("\n全部核心功能接口测试通过。")


if __name__ == "__main__":
    main()
