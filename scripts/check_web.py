import sys
sys.path.insert(0, 'src')
from graxia_tool.web import app
print('App created with routes:')
for r in app.routes:
    if hasattr(r, 'path'):
        methods = r.methods if hasattr(r, 'methods') else ''
        print(f'  {methods} {r.path}')
