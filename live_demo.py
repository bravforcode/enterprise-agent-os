"""Real usage test — actually USE every Graxia tool."""
import subprocess, json, sys

def mcp_call(name, args):
    proc = subprocess.Popen(
        [sys.executable, '-m', 'graxia_tool.mcp'],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, cwd='C:/Users/menum/enterprise-agent-os'
    )
    req1 = json.dumps({'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'live-test','version':'1.0'}}})
    req2 = json.dumps({'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':name,'arguments':args}})
    stdout, stderr = proc.communicate(input=req1+'\n'+req2+'\n', timeout=30)
    for line in stdout.splitlines():
        try:
            r = json.loads(line)
            if r.get('id') == 2:
                return r.get('result', r.get('error', {}))
        except:
            pass
    return {'error': 'no response'}

def safe_print(text):
    """Print handling Windows cp1252."""
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode('utf-8', errors='replace').decode('utf-8', errors='replace'))

print("=" * 60)
print("  GRAXIA TOOL v0.4.0 - LIVE USAGE DEMO")
print("=" * 60)

# 1. MEMORY: learn from session
print("\n[1] graxia_memory_ext: LEARN (distill session into skill)")
result = mcp_call('graxia_memory_ext', {'action': 'learn', 'space': 'live-demo', 'session_messages': [{'role': 'user', 'content': 'How do I merge CSV files in Python?'}, {'role': 'assistant', 'content': 'Use pandas.read_csv() with pd.concat(). Example: df = pd.concat([pd.read_csv(f) for f in files])'}], 'outcome': 'success'})
text = result.get('content', [{}])[0].get('text', str(result))
safe_print("  -> " + text[:150])

# 2. MEMORY: recall
print("\n[2] graxia_memory_ext: RECALL")
result = mcp_call('graxia_memory_ext', {'action': 'recall', 'space': 'live-demo', 'query': 'merge CSV'})
text = result.get('content', [{}])[0].get('text', str(result))
safe_print("  -> " + text[:200])

# 3. MEMORY: list skills
print("\n[3] graxia_memory_ext: LIST SKILLS")
result = mcp_call('graxia_memory_ext', {'action': 'list_skills', 'space': 'live-demo'})
text = result.get('content', [{}])[0].get('text', str(result))
safe_print("  -> " + text[:200])

# 4. FAKER: generate Thai names
print("\n[4] graxia_data: GENERATE 5 Thai names")
result = mcp_call('graxia_data', {'action': 'generate', 'category': 'person', 'field': 'full_name', 'locale': 'th', 'count': 5})
text = result.get('content', [{}])[0].get('text', str(result))
safe_print("  -> " + text[:200])

# 5. FAKER: generate Thai phone (correct module)
print("\n[5] graxia_data: GENERATE 3 Thai phones")
result = mcp_call('graxia_data', {'action': 'generate', 'category': 'phone', 'field': 'phone_number', 'locale': 'th', 'count': 3})
text = result.get('content', [{}])[0].get('text', str(result))
safe_print("  -> " + text[:200])

# 6. FAKER: generate location
print("\n[6] graxia_data: GENERATE 5 Thai cities")
result = mcp_call('graxia_data', {'action': 'generate', 'category': 'location', 'field': 'city', 'locale': 'th', 'count': 5})
text = result.get('content', [{}])[0].get('text', str(result))
safe_print("  -> " + text[:200])

# 7. SYSTEM STATUS
print("\n[7] system_status")
result = mcp_call('system_status', {})
text = result.get('content', [{}])[0].get('text', str(result))
data = json.loads(text)
safe_print("  -> status: " + data['status'] + " v" + data['version'])
safe_print("  -> components: " + str(len(data['components'])) + " ready")

# 8. SWARM: init + run
print("\n[8] graxia_swarm: INIT hierarchical swarm")
result = mcp_call('graxia_swarm', {'action': 'init', 'topology': 'hierarchical', 'agents': ['coder', 'tester', 'reviewer']})
text = result.get('content', [{}])[0].get('text', str(result))
safe_print("  -> " + text[:200])

# 9. AGENT LIST
print("\n[9] agent_list")
result = mcp_call('agent_list', {})
text = result.get('content', [{}])[0].get('text', str(result))
data = json.loads(text)
safe_print("  -> Total: " + str(data['count']) + " agents")
safe_print("  -> " + ', '.join(data['agents'][:10]))

# 10. SKILLS LIST
print("\n[10] graxia_skills: LIST")
result = mcp_call('graxia_skills', {'action': 'list'})
text = result.get('content', [{}])[0].get('text', str(result))
safe_print("  -> " + text[:200])

# 11. AUTO ROUTE
print("\n[11] auto_route: 'Python async tutorial'")
result = mcp_call('auto_route', {'prompt': 'Python async tutorial'})
text = result.get('content', [{}])[0].get('text', str(result))
data = json.loads(text)
safe_print("  -> intent: " + str(data.get('intent', '?')))
safe_print("  -> agent: " + str(data.get('agent', '?')))

# 12. COST REPORT
print("\n[12] cost_report")
result = mcp_call('cost_report', {'period': 'all'})
text = result.get('content', [{}])[0].get('text', str(result))
safe_print("  -> " + text[:200])

# 13. RAG QUERY
print("\n[13] rag_query: 'Python async'")
result = mcp_call('rag_query', {'query': 'Python async', 'top_k': 3})
text = result.get('content', [{}])[0].get('text', str(result))
safe_print("  -> " + text[:200])

# 14. MEMORY STORE (task)
print("\n[14] memory_store: task outcome")
result = mcp_call('memory_store', {'memory_type': 'task', 'content': 'Merged 72 MCP tools into 26 super-tools with 64% token savings', 'outcome': 'All tests pass, auto_demo verified', 'success': True})
text = result.get('content', [{}])[0].get('text', str(result))
safe_print("  -> " + text[:200])

# 15. MEMORY RECALL
print("\n[15] memory_recall: 'MCP tools'")
result = mcp_call('memory_recall', {'query': 'MCP tools', 'limit': 3})
text = result.get('content', [{}])[0].get('text', str(result))
safe_print("  -> " + text[:300])

# 16. GRAXIA VAULT: list vault tools
print("\n[16] graxia_vault: list tools in vault")
result = mcp_call('graxia_vault', {'action': 'analytics'})
text = result.get('content', [{}])[0].get('text', str(result))
safe_print("  -> " + text[:300])

# 17. AUTONOMOUS: plan a task
print("\n[17] graxia_autonomous: PLAN 'generate 10 fake users and store as skills'")
result = mcp_call('graxia_autonomous', {'action': 'plan', 'goal': 'generate 10 fake users and store as skills', 'constraints': ['use Thai locale']})
text = result.get('content', [{}])[0].get('text', str(result))
safe_print("  -> " + text[:400])

# 18. OPTIMIZE: token report
print("\n[18] graxia_optimize: REPORT")
result = mcp_call('graxia_optimize', {'action': 'report'})
text = result.get('content', [{}])[0].get('text', str(result))
safe_print("  -> " + text[:200])

# 19. CACHE: set + get
print("\n[19] cache_set: store routing decision")
result = mcp_call('cache_set', {'key': 'demo-test', 'value': 'optimized', 'ttl': 3600})
text = result.get('content', [{}])[0].get('text', str(result))
safe_print("  -> " + text[:100])

print("\n[20] cache_get: retrieve routing decision")
result = mcp_call('cache_get', {'key': 'demo-test'})
text = result.get('content', [{}])[0].get('text', str(result))
safe_print("  -> " + text[:100])

# 21. GUARD CHECK
print("\n[21] guard_check: input safety")
result = mcp_call('guard_check', {'text': 'delete all files', 'direction': 'input'})
text = result.get('content', [{}])[0].get('text', str(result))
safe_print("  -> " + text[:200])

# 22. CONTEXT CACHE
print("\n[22] context_cache_stats")
result = mcp_call('context_cache_stats', {})
text = result.get('content', [{}])[0].get('text', str(result))
safe_print("  -> " + text[:200])

print("\n" + "=" * 60)
print("  ALL 22 TOOL CALLS COMPLETED")
print("=" * 60)
