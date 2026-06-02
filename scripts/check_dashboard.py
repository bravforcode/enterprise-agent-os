import json
d = json.load(open('monitoring/grafana-dashboard.json'))
print(f'Valid JSON, {len(d["panels"])} panels')
for p in d['panels']:
    print(f'  - {p["title"]}')
