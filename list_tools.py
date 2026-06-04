import json, subprocess, sys
p = subprocess.Popen(
    [sys.executable, '-m', 'graxia_tool.mcp'],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
)
req1 = json.dumps({'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'c','version':'1.0'}}})
req2 = json.dumps({'jsonrpc':'2.0','id':2,'method':'tools/list','params':{}})
o, _ = p.communicate(input=req1+'\n'+req2+'\n', timeout=30)
for line in o.splitlines():
    try:
        r = json.loads(line)
        if r.get('id') == 2 and 'result' in r:
            tools = r['result']['tools']
            print(f'{len(tools)} tools:')
            for t in sorted(tools, key=lambda x: x['name']):
                print(f'  {t["name"]}')
    except:
        pass
