# Enterprise Agent OS — Universal AI Agent Orchestration

![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![Qdrant](https://img.shields.io/badge/Qdrant-FF4A00?style=for-the-badge&logo=qdrant&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-336791?style=for-the-badge&logo=postgresql&logoColor=white)
![MCP](https://img.shields.io/badge/MCP_Server-181717?style=for-the-badge&logo=modelcontextprotocol&logoColor=white)
![15_Agents](https://img.shields.io/badge/Sub--Agents-15-7c3aed?style=for-the-badge)
![7_Patterns](https://img.shields.io/badge/Orchestration_Patterns-7-0ea5e9?style=for-the-badge)

> **One OS to run them all.** MCP server + 15 specialized sub-agents + 7 orchestration patterns — the reference implementation for production multi-agent systems.

### Demo

> 🎬 **Demo coming soon** — screen capture will be added at `docs/demo.gif`

### Architecture

```mermaid
graph TD
  A[Claude / Any MCP Client] --> B[MCP Server Layer]
  B --> C[Orchestrator: 7 Patterns]
  C --> D1[Research Agent]
  C --> D2[Coder Agent]
  C --> D3[Reviewer Agent]
  C --> D4[Data Agent]
  C --> D5[+11 Specialized Agents]
  D1 --> E[(Qdrant Vector DB)]
  D2 --> F[(PostgreSQL)]
  C --> G[Event Bus + Audit Log]
```

**7 Orchestration Patterns:** Sequential · Parallel · Hierarchical · Mesh · Pipeline · Consensus · Adaptive routing

### Quickstart

```bash
git clone https://github.com/bravforcode/enterprise-agent-os.git
cd enterprise-agent-os
cp .env.example .env  # set QDRANT_URL, DATABASE_URL, LLM_API_KEY
docker compose up --build
```

### Results

| Metric | Value |
|---|---|
| Sub-agents | **15** specialized |
| Orchestration patterns | **7** |
| MCP tools exposed | Full tool surface |
| Vector search | Qdrant + hybrid retrieval |


---

**Phirawit Jitnarong — Strategic Full-Stack & AI Engineer**

xme176@gmail.com · 092-551-0427 · [LinkedIn](https://www.linkedin.com/in/%E0%B8%9E%E0%B8%B5%E0%B8%A3%E0%B8%A7%E0%B8%B4%E0%B8%8A%E0%B8%8D%E0%B9%8C-%E0%B8%88%E0%B8%B4%E0%B8%95%E0%B8%93%E0%B8%A3%E0%B8%87%E0%B8%84%E0%B9%8C-0000393a4) · [Fastwork](https://fastwork.co/user/bravforcode?source=search)

> Hiring for this stack? Let's talk — production hardened, 300k+ users shipped.