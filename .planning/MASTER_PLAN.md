# Graxia Tool — Master Plan (15 Tasks)

## Status Legend
- [ ] Not started
- [/] In progress
- [x] Done
- [!] Blocked

## Tier 1: Quick Win (ใช้งานจริงได้)

### T1.1 — Test MCP with Claude Desktop
- [ ] Verify `~/.claude/claude_desktop_config.json` is valid JSON
- [ ] Start MCP server manually, test JSON-RPC handshake
- [ ] Test all 18 tools end-to-end via stdio
- [ ] Document test results

### T1.2 — Example Workflow
- [ ] Create `examples/code_review_pipeline.py` (coder→reviewer→tester)
- [ ] Create `examples/data_analysis_pipeline.py` (researcher→data_engineer→documenter)
- [ ] Create `examples/security_audit.py` (auditor→security_auditor→reviewer)
- [ ] Each example runs end-to-end with real output

### T1.3 — Real API Integration
- [ ] Add `RealLLMClient` for Anthropic API
- [ ] Add `RealLLMClient` for OpenAI API
- [ ] Wire to sub-agents (replacing mock)
- [ ] Add API key management (env vars)
- [ ] Test real API call + measure actual cost

### T1.4 — Setup Postgres + Qdrant (Docker)
- [ ] `docker-compose.yml` with Postgres + Qdrant
- [ ] Verify `storage.py` connects
- [ ] Run integration test against real DBs
- [ ] Document setup steps

## Tier 2: Production Ready (deploy ได้)

### T2.5 — CI/CD Pipeline
- [ ] `.github/workflows/test.yml` — run 567 tests
- [ ] `.github/workflows/lint.yml` — ruff + mypy
- [ ] `.github/workflows/build.yml` — docker build + push
- [ ] `.github/workflows/deploy.yml` — k8s deploy

### T2.6 — Real Grafana Dashboard
- [ ] Update `monitoring/grafana-dashboard.json` (13 panels → 20+)
- [ ] Add Prometheus metrics in `src/graxia_tool/metrics.py`
- [ ] Test dashboard with mock metrics

### T2.7 — API Rate Limiting per User
- [ ] Use `AdvancedRateLimiter` in API middleware
- [ ] Add JWT auth middleware
- [ ] Tests for rate limit per user/org

### T2.8 — Audit Logging
- [ ] Wire `AuditLogger` to all sensitive operations
- [ ] Persist audit logs to Postgres
- [ ] API endpoint to query audit logs
- [ ] Tests

### T2.9 — Load Test
- [ ] `tests/load/api_load.js` (k6)
- [ ] Test 100 RPS for 5 minutes
- [ ] Document results

### T2.10 — Backup & DR
- [ ] `scripts/backup_postgres.sh`
- [ ] `scripts/backup_qdrant.sh`
- [ ] `scripts/restore_postgres.sh`
- [ ] Schedule via cron/k8s CronJob

## Tier 3: Scale (ขยายความสามารถ)

### T3.11 — More Agents
- [ ] `DatabaseAdmin` agent
- [ ] `NetworkEngineer` agent
- [ ] `FrontendDesigner` agent
- [ ] Update AGENT_REGISTRY + tests

### T3.12 — Web UI
- [ ] FastAPI endpoints for dashboard
- [ ] Simple HTML+JS dashboard (cost, agents, vault)
- [ ] Real-time updates via SSE

### T3.13 — Multi-tenancy
- [ ] Tenant model in Postgres
- [ ] Per-tenant vault path + namespace
- [ ] Per-tenant cost tracking
- [ ] Tests

### T3.14 — Fine-tuning
- [ ] Script to collect training data from logs
- [ ] Export to ONNX format
- [ ] Skill router retraining script

### T3.15 — Plugin Marketplace
- [ ] Plugin loader (dynamic import)
- [ ] Plugin manifest schema
- [ ] Example plugin: `hello_world_plugin.py`
- [ ] Tests

## Final Deliverables

- [ ] All 567+ tests passing
- [ ] CI/CD green
- [ ] Docker compose works
- [ ] MCP server validated with real client
- [ ] Load test passes
- [ ] Backup scripts work
- [ ] Documentation complete
- [ ] Final SUMMARY.md
