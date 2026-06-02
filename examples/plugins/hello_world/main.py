"""Hello World plugin for Graxia Tool."""


def hello(name: str = "World") -> str:
    """Say hello to someone."""
    return f"Hello, {name}!"


def goodbye(name: str = "World") -> str:
    """Say goodbye to someone."""
    return f"Goodbye, {name}!"


def on_agent_run(agent_name: str, query: str) -> None:
    """Hook called when an agent runs."""
    print(f"[hello_world plugin] Agent {agent_name} ran: {query[:50]}")
