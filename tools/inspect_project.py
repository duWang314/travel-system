#!/usr/bin/env python3
from pathlib import Path
import json

root = Path(__file__).resolve().parents[1]
print('ROOT', root)
print('\nTop-level:')
for p in sorted(root.iterdir()):
    print('-', p.name, 'DIR' if p.is_dir() else 'FILE')

map_dir = root / 'backend' / 'data' / 'map'
print('\nMaps:')
for file in sorted(map_dir.glob('*.json')):
    data = json.loads(file.read_text(encoding='utf-8'))
    if isinstance(data, dict):
        nodes = data.get('nodes') or data.get('features') or []
        edges = data.get('edges') or []
        print(file.name, 'dict keys=', list(data.keys()), 'nodes=', len(nodes), 'edges=', len(edges))
        if nodes:
            print('  node keys:', list(nodes[0].keys()))
            print('  first node:', nodes[0])
        if edges:
            print('  edge keys:', list(edges[0].keys()))
            print('  first edge:', edges[0])
    else:
        print(file.name, type(data), 'len=', len(data))

indoor_dir = root / 'backend' / 'data' / 'indoor_nevigation'
print('\nIndoor files:')
for file in sorted(indoor_dir.glob('*.json')):
    data = json.loads(file.read_text(encoding='utf-8'))
    print(file.name, 'keys=', list(data.keys()) if isinstance(data, dict) else type(data), 'len=', len(data) if hasattr(data, '__len__') else '?')
    print(str(data)[:1000])

diaries = root / 'backend' / 'data' / 'diaries'
print('\nDiaries:')
for file in sorted(diaries.glob('*.txt')):
    text = file.read_text(encoding='utf-8', errors='ignore')
    print(file.name, len(text), text[:200].replace('\n',' '))
