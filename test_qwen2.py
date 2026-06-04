"""Test qwen3.5 with think=false."""
import httpx, json, time

def ask(prompt, max_tokens=200):
    start = time.time()
    r = httpx.post('http://localhost:11434/api/generate', json={
        'model': 'qwen3.5:4b',
        'prompt': prompt,
        'stream': False,
        'think': False,
        'options': {'num_predict': max_tokens}
    }, timeout=60)
    data = r.json()
    elapsed = time.time() - start
    return data.get('response', ''), data.get('thinking', ''), round(elapsed, 1)

tests = [
    ('Hello', 'Say hello in Thai'),
    ('Code', 'Write a Python function to calculate factorial'),
    ('JSON', 'Return JSON with keys: name=somchai, age=25'),
    ('Tool', 'Call graxia_data(action=generate, category=person, field=first_name, locale=th, count=3). Return the JSON tool call only.'),
    ('Plan', 'Plan 3 steps to build a web scraper. Return numbered list.'),
    ('Review', 'Review this code: def add(a,b): return a+b. Give 2 bullet points.'),
]

for name, prompt in tests:
    resp, thinking, elapsed = ask(prompt)
    try:
        print(f'=== {name} ({elapsed}s) ===')
        if resp:
            print('RESPONSE:', resp[:250].encode('utf-8', errors='replace').decode('utf-8', errors='replace'))
        if thinking:
            print('THINKING:', thinking[:100].encode('utf-8', errors='replace').decode('utf-8', errors='replace'))
        if not resp and not thinking:
            print('(empty)')
        print()
    except UnicodeEncodeError:
        print(f'=== {name} ({elapsed}s) === (unicode error)')
        print()
