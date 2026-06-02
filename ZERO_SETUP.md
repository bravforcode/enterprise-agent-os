# Graxia Tool — Zero-Setup Quick Start

**No API key. No monthly bill. Runs on your machine.**

---

## The 30-Second Start

```bash
pip install graxia-tool
graxia-install       # One command: pulls model, sets up MCP
graxia               # Launch web UI → http://localhost:8000
```

That's it. No API keys, no cloud accounts, no setup beyond `pip install`.

---

## What Graxia Installs

When you run `graxia-install`, it does **4 things**:

1. **Checks for Ollama** (free, local LLM) — installs if missing
2. **Pulls a model** (`llama3.2:1b` by default, 1.3GB, fast on any GPU/CPU)
3. **Configures MCP** for Claude Desktop / Codex / Gemini / OpenCode
4. **Creates launcher scripts** (`graxia.bat` on Windows, `graxia` on Mac/Linux)

After install, you can:
- Run `graxia` → opens the web UI at `http://localhost:8000`
- Run `graxia-mcp` → starts the MCP server for your AI client
- Restart your AI client (Claude Desktop etc.) to see Graxia tools appear

---

## Why Ollama (not Mock, not API)

You said:
- ❌ Don't want to use API key
- ❌ Don't want to use mock
- ✅ Real LLM

**Ollama is the only answer that fits all 3.** It runs a real, full LLM
(like Llama 3.2, Qwen, Mistral, etc.) **locally on your machine**, with
**zero cloud dependency** and **no API key needed**.

| Option | Real? | No Key? | Free? | Local? |
|---|---|---|---|---|
| Anthropic Claude API | ✅ | ❌ | ❌ | ❌ |
| OpenAI GPT API | ✅ | ❌ | ❌ | ❌ |
| Mock | ❌ | ✅ | ✅ | ✅ |
| **Ollama** | ✅ | ✅ | ✅ | ✅ |

---

## Models You Can Use (all free, all local)

```bash
ollama pull llama3.2:1b      # 1.3GB — fastest, default
ollama pull llama3.2:3b      # 2.0GB — better quality
ollama pull qwen2.5:7b       # 4.7GB — strong reasoning
ollama pull gemma2:2b        # 1.6GB — Google's model
ollama pull mistral          # 4.1GB — popular European model
ollama pull codellama        # 3.8GB — code-specialized
ollama pull deepseek-coder   # 3.4GB — code + reasoning
```

Set `OLLAMA_MODEL=qwen2.5:7b` to switch defaults.

---

## Three Ways to Use Graxia

### 1. Web UI (easiest — just click)

```bash
graxia
```

Opens `http://localhost:8000` with:
- Agent dashboard (18 agents)
- Live cost report ($0.00 with Ollama)
- Skill browser
- Vault search
- Audit log

### 2. MCP Server (for Claude Desktop / Codex / Gemini)

```bash
graxia-mcp
```

The MCP server speaks stdio. Once running, your AI client sees 18 Graxia tools:
- `agent_run` — run any of 18 sub-agents
- `pipeline_run` — chain agents
- `multi_agent_run` — parallel/sequential patterns
- `guard_check` — security guardrails
- `memory_search` / `rag_query` — RAG over your notes
- `cost_report` — spending analytics
- `skills_list` / `skills_load` — load Claude Code skills
- `vault_search` / `vault_read` / `vault_write` — Obsidian/Graxia access
- ... and 7 more

### 3. Python API (for custom apps)

```python
from graxia_tool.llm import OllamaClient  # Free, local, no key
from graxia_tool.agents import get_agent

llm = OllamaClient()  # Defaults to llama3.2:1b
agent = get_agent("coder")
agent.llm_func = llm.complete
result = await agent.run("Write a Python hello world")
print(result.output)
```

---

## What if I Already Have Anthropic / OpenAI Keys?

Graxia auto-detects and uses the best available:

```bash
# Order of preference (no env vars = Ollama):
export ANTHROPIC_API_KEY=sk-...   # → uses Claude
export OPENAI_API_KEY=sk-...      # → uses GPT
# Otherwise → uses Ollama
```

---

## Verify Your Install

```bash
graxia status
```

Output:
```
Graxia Tool Status
========================================
  Ollama installed: ✓
  Ollama running:   ✓
  Models available: 1
    - llama3.2:1b
  Agents loaded:    18
```

---

## Troubleshooting

| Problem | Solution |
|---|---|
| "Cannot connect to Ollama" | Run `ollama serve` in another terminal, or `graxia ollama` to auto-start |
| "Model not found" | Run `ollama pull llama3.2:1b` (or your chosen model) |
| Slow responses | Try smaller model: `ollama pull llama3.2:1b` (1.3GB vs 4.7GB) |
| Out of memory | Use `qwen2.5:0.5b` (~500MB) or `llama3.2:1b` (1.3GB) |
| Want to use Claude/GPT | Set `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` env var |
| Need to re-run setup | `graxia-install` (idempotent, safe to re-run) |

---

## System Requirements

- **Python 3.11+**
- **4GB RAM minimum** (8GB+ recommended)
- **GPU optional** — Ollama runs on CPU but is faster on GPU
  - NVIDIA: uses CUDA
  - AMD: uses ROCm (Linux only)
  - Apple Silicon: uses Metal (very fast)
- **Disk: ~2GB** for the default model
- **OS**: Windows 10+, macOS 11+, Linux (any modern distro)

---

## What Graxia Gives You (Beyond Just LLM)

Ollama is the LLM, but Graxia wraps it with:
- **18 specialized sub-agents** (coder, researcher, debugger, security_auditor, etc.)
- **MCP server** for Claude Desktop, Codex, Gemini, OpenCode
- **Web UI** with cost dashboard, audit log, skill browser
- **Cost engine** (dedup, cache, compression, model routing) — saves ~41% on cloud LLM spend
- **Multi-tenant** with per-user rate limits, quotas
- **Fine-tune export** (collect agent outputs → JSONL for training)
- **Plugin marketplace** (load community agents/tools)
- **Obsidian / Graxia vault** integration
- **JWT auth** + audit logger
- **Prometheus metrics** + Grafana dashboard

---

## Next Steps

1. `graxia` → open web UI → click "Run" on any agent
2. Configure Claude Desktop → see 18 Graxia tools in your chat
3. `ollama pull qwen2.5:7b` → upgrade to a stronger model
4. `graxia install --model qwen2.5:7b` → switch default

Read the full docs: see `MASTER_PLAN.md` and `FINAL_SUMMARY.md` in the project.
