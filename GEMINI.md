# Gemini Agent Config

## Rules

Read and follow: `enterprise-agent-os/AGENT_RULES.md`

This is the SINGLE SOURCE OF TRUTH for all agent behavior.

## MCP Tools

5 unified tools (39 actions):

| Tool | Purpose |
|------|---------|
| `brain` | Memory, search, skills, vault, sync (17 actions) |
| `run` | Execute tasks, workflows (8 actions) |
| `guard` | Safety, governance, quality (6 actions) |
| `data` | Generate synthetic data (3 actions) |
| `sys` | System status, cache (5 actions) |

## Mandatory Startup

1. `brain(action="auto_route", prompt="user's message")`
2. `brain(action="recall", query="keywords")`
3. [work]
4. `brain(action="store", content="...", memory_type="task")`
