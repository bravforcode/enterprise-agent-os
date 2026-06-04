"""Test qwen3.5:4b capabilities for Graxia integration."""
import httpx, json, time

def ask(prompt, max_tokens=300):
    r = httpx.post('http://localhost:11434/api/generate', json={
        'model': 'qwen3.5:4b',
        'prompt': '/no_think\n' + prompt,
        'stream': False,
        'options': {'num_predict': max_tokens}
    }, timeout=60)
    return r.json().get('response', '')

tests = [
    ('Thai code', 'Write a Python function to calculate factorial recursively'),
    ('JSON', 'Return a JSON object: name=somchai, age=25, skills=[python, rust, go]'),
    ('Reason', 'If A > B and B > C, is A > C? Answer yes or no with 1 sentence.'),
    ('Tool call', 'You have a tool called graxia_data. To generate 3 Thai names, call: graxia_data(action="generate", category="person", field="first_name", locale="th", count=3). Show the tool call as JSON.'),
    ('Memory', 'You have a tool called memory_store. Store this: "qwen3.5 4b is good for code generation but struggles with Thai text". Show the tool call as JSON.'),
    ('Plan', 'Plan 3 steps to create a Python web scraper. Return as numbered list.'),
]

for name, prompt in tests:
    start = time.time()
    resp = ask(prompt)
    elapsed = time.time() - start
    print(f'=== {name} ({elapsed:.0f}s) ===')
    print(resp[:300])
    print()
