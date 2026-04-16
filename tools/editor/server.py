#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本地地图编辑服务（无第三方依赖）
- 提供静态页面托管
- 提供地图列表 / 读取 / 全量保存 / 增量补丁保存 API
"""

import json
import os
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, unquote

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MAP_DATA_DIR = os.path.join(BASE_DIR, "../map_data")


def _safe_map_path(file_name: str) -> str:
    file_name = os.path.basename(file_name).strip()
    if not file_name:
        raise ValueError("文件名不能为空")
    if not file_name.endswith('.json'):
        raise ValueError("只允许 .json 文件")
    abs_path = os.path.abspath(os.path.join(MAP_DATA_DIR, file_name))
    map_root = os.path.abspath(MAP_DATA_DIR)
    if os.path.commonpath([abs_path, map_root]) != map_root:
        raise ValueError("非法路径")
    return abs_path


def _read_json(path: str):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def _write_json(path: str, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _node_id_key(n):
    return str(n.get('node_id'))


def _edge_key(e):
    return f"{e.get('source_id')}->{e.get('target_id')}::{e.get('road_name', '')}"


def apply_patch(map_data: dict, patch: dict) -> dict:
    if 'nodes' not in map_data or 'edges' not in map_data:
        raise ValueError('地图数据缺少 nodes/edges 字段')

    nodes = map_data['nodes']
    edges = map_data['edges']

    # 1) 新增节点
    for n in patch.get('add_nodes', []):
        nid = _node_id_key(n)
        if not nid:
            continue
        exists = any(_node_id_key(x) == nid for x in nodes)
        if not exists:
            nodes.append(n)

    # 2) 更新节点（按 node_id 合并覆盖）
    for n in patch.get('update_nodes', []):
        nid = _node_id_key(n)
        if not nid:
            continue
        hit = False
        for i, old in enumerate(nodes):
            if _node_id_key(old) == nid:
                merged = dict(old)
                merged.update(n)
                nodes[i] = merged
                hit = True
                break
        if not hit:
            nodes.append(n)

    # 3) 新增边
    for e in patch.get('add_edges', []):
        edges.append(e)

    # 4) 更新边
    for item in patch.get('update_edges', []):
        idx = item.get('index')
        new_edge = item.get('data', {})

        if isinstance(idx, int) and 0 <= idx < len(edges):
            merged = dict(edges[idx])
            merged.update(new_edge)
            edges[idx] = merged
            continue

        # 兜底：按 key 匹配
        new_key = _edge_key(new_edge)
        hit = False
        for i, old in enumerate(edges):
            if _edge_key(old) == new_key:
                merged = dict(old)
                merged.update(new_edge)
                edges[i] = merged
                hit = True
                break
        if not hit and new_edge:
            edges.append(new_edge)

    # 5) 删除边（可选）
    del_keys = set(patch.get('delete_edges', []))
    if del_keys:
        map_data['edges'] = [e for e in edges if _edge_key(e) not in del_keys]

    return map_data


class MapEditorHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    def _send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body_json(self):
        size = int(self.headers.get('Content-Length', 0))
        raw = self.rfile.read(size) if size > 0 else b'{}'
        if not raw:
            return {}
        return json.loads(raw.decode('utf-8'))

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET,POST,PUT,OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        super().end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == '/api/maps':
            try:
                files = []
                for fn in os.listdir(MAP_DATA_DIR):
                    if not fn.endswith('.json'):
                        continue
                    file_path = os.path.join(MAP_DATA_DIR, fn)
                    display_name = os.path.splitext(fn)[0]
                    try:
                        data = _read_json(file_path)
                        display_name = data.get('destination_name') or display_name
                    except Exception:
                        pass
                    files.append({
                        'file_name': fn,
                        'display_name': display_name,
                    })
                files.sort(key=lambda x: x['display_name'])
                self._send_json({'maps': files})
            except Exception as e:
                self._send_json({'error': str(e)}, status=500)
            return

        if path.startswith('/api/maps/'):
            file_name = unquote(path[len('/api/maps/'):])
            try:
                map_path = _safe_map_path(file_name)
                data = _read_json(map_path)
                self._send_json(data)
            except FileNotFoundError:
                self._send_json({'error': '文件不存在'}, status=404)
            except Exception as e:
                self._send_json({'error': str(e)}, status=400)
            return

        return super().do_GET()

    def do_PUT(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path.startswith('/api/maps/'):
            file_name = unquote(path[len('/api/maps/'):])
            try:
                map_path = _safe_map_path(file_name)
                incoming = self._read_body_json()
                if not isinstance(incoming, dict):
                    raise ValueError('请求体必须是 JSON 对象')
                if 'nodes' not in incoming or 'edges' not in incoming:
                    raise ValueError('必须包含 nodes 和 edges 字段')
                _write_json(map_path, incoming)
                self._send_json({'ok': True, 'saved_file': file_name})
            except Exception as e:
                self._send_json({'error': str(e)}, status=400)
            return

        self._send_json({'error': '未知接口'}, status=404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path.startswith('/api/maps/') and path.endswith('/patch'):
            file_name = unquote(path[len('/api/maps/'): -len('/patch')])
            try:
                map_path = _safe_map_path(file_name)
                current = _read_json(map_path)
                patch = self._read_body_json()
                if not isinstance(patch, dict):
                    raise ValueError('补丁必须是 JSON 对象')
                updated = apply_patch(current, patch)
                _write_json(map_path, updated)
                self._send_json({'ok': True, 'saved_file': file_name, 'map_data': updated})
            except Exception as e:
                self._send_json({'error': str(e)}, status=400)
            return

        self._send_json({'error': '未知接口'}, status=404)


def run(host='0.0.0.0', port=8080):
    os.makedirs(MAP_DATA_DIR, exist_ok=True)
    httpd = HTTPServer((host, port), MapEditorHandler)
    print(f"[OK] Map editor server running at http://{host}:{port}")
    print(f"[INFO] Serving from: {BASE_DIR}")
    print(f"[INFO] Map data dir: {MAP_DATA_DIR}")
    httpd.serve_forever()


if __name__ == '__main__':
    run()
