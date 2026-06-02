$env:PYTHONIOENCODING="utf-8"
python -c "
from src.graxia_tool.auto_router import AutoRouter
router = AutoRouter()
tests = [
    ('Write a Python function to parse CSV files', 'code', 'coder'),
    ('Fix the bug in auth.py that causes 500 errors', 'debug', 'debugger'),
    ('Search for latest OpenAI API documentation', 'research', 'researcher'),
    ('Research how to implement OAuth2', 'research', 'researcher'),
    ('Deploy the application to production', 'deploy', 'deployer'),
    ('Write unit tests for the user service', 'test', 'tester'),
    ('Review this pull request for security issues', 'review', 'reviewer'),
    ('Explain how the caching layer works', 'document', 'documenter'),
]
all_pass = True
for prompt, expected_intent, expected_agent in tests:
    d = router.route(prompt)
    status = 'PASS' if d.intent == expected_intent and d.agent_type == expected_agent else 'FAIL'
    if status == 'FAIL':
        all_pass = False
    print(f'{status}: intent={d.intent} (exp {expected_intent}), agent={d.agent_type} (exp {expected_agent})')
print()
print('All tests passed!' if all_pass else 'Some tests failed')
"
