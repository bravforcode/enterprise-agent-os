import sys, asyncio
sys.path.insert(0, 'src')
from graxia_tool.agents import get_agent

async def test():
    coder = get_agent('coder')
    result = await coder.run('Test query')
    print(f'Type: {type(result)}')
    if hasattr(result, '__dict__'):
        for k, v in result.__dict__.items():
            print(f'  {k}: {repr(v)[:100]}')
    print(f'Output type: {type(result.output)}')
    print(f'Output: {repr(result.output)[:200]}')

asyncio.run(test())
