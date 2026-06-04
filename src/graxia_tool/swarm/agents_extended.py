"""Extended agent definitions for the Graxia swarm — 80+ additional agents.

Categories: code quality, architecture, devops, testing, documentation,
data, security, frontend, and a few utility specialists. Combined with
the original 18 in graxia_tool.agents.implementations, the registry holds
100+ agents.

Each agent is a BaseSubAgent subclass; we build them via a small factory
to keep this file compact and uniform.
"""
from __future__ import annotations

from typing import Any, List, Optional, Type

from ..agents.base import BaseSubAgent, SubAgentResult


def _make_agent(
    cls_name: str,
    name: str,
    description: str,
    system_prompt: str,
    category: str,
    output_key: str = "response",
    output_extra: Optional[dict] = None,
    required_skills: Optional[List[str]] = None,
    required_tools: Optional[List[str]] = None,
    max_tokens: int = 200,
) -> Type[BaseSubAgent]:
    """Dynamically build a BaseSubAgent subclass with the given attributes."""

    async def _execute(self, query: str, context: Optional[dict] = None) -> SubAgentResult:
        return await self.execute_with_llm(
            query,
            system_prompt=system_prompt,
            output_key=output_key,
            output_extra={"category": category, **(output_extra or {})},
        )

    cls_dict: dict[str, Any] = {
        "__doc__": f"{name} — {description}",
        "name": name,
        "description": description,
        "category": category,
        "required_skills": required_skills or [],
        "required_tools": required_tools or [],
        "max_tokens": max_tokens,
        "execute": _execute,
    }
    return type(cls_name, (BaseSubAgent,), cls_dict)


# ---------------------------------------------------------------------------
# Code Quality (15)
# ---------------------------------------------------------------------------

CODE_QUALITY_AGENTS: List[Type[BaseSubAgent]] = [
    _make_agent("CodeReviewer", "code-reviewer",
        "Code review: correctness, style, security, performance.",
        "Review code for correctness, security, performance, and style. Flag issues with severity.",
        "code_quality", output_key="review"),
    _make_agent("SecurityScanner", "security-scanner",
        "SAST/DAST security scanner for source code.",
        "Scan code for vulnerabilities: injection, XSS, SSRF, hardcoded secrets, unsafe deserialization.",
        "code_quality", output_key="findings",
        required_skills=["ai-security"], required_tools=["file_read", "shell_exec"]),
    _make_agent("LintChecker", "lint-checker",
        "Run linters and report violations.",
        "Run linters (ruff, eslint, golangci-lint) and report violations with file/line.",
        "code_quality", output_key="violations",
        required_tools=["shell_exec"]),
    _make_agent("Formatter", "formatter",
        "Auto-format code (black, prettier, gofmt).",
        "Apply language-appropriate formatting (black/isort, prettier, gofmt, rustfmt).",
        "code_quality", output_key="formatted",
        required_tools=["file_read", "file_write", "shell_exec"]),
    _make_agent("RefactorSuggester", "refactor-suggester",
        "Suggest refactors (extract method, DRY, simplify).",
        "Suggest refactorings: extract method/class, reduce duplication, simplify conditionals.",
        "code_quality", output_key="refactors"),
    _make_agent("DependencyAuditor", "dependency-auditor",
        "Audit dependencies for vulnerabilities and license issues.",
        "Audit deps: CVEs (pip-audit, npm audit), license compatibility, outdated, abandoned.",
        "code_quality", output_key="audit",
        required_tools=["shell_exec"]),
    _make_agent("TypeChecker", "type-checker",
        "Run static type checkers (mypy, tsc, pyright).",
        "Run mypy/tsc/pyright; report type errors with strictness rationale.",
        "code_quality", output_key="type_errors",
        required_tools=["shell_exec"]),
    _make_agent("ComplexityAnalyzer", "complexity-analyzer",
        "Cyclomatic / cognitive complexity analyzer.",
        "Compute cyclomatic & cognitive complexity; flag functions >10 cyclomatic / >15 cognitive.",
        "code_quality", output_key="complexity"),
    _make_agent("DocstringGenerator", "docstring-generator",
        "Generate docstrings (PEP 257, JSDoc, GoDoc).",
        "Generate language-appropriate docstrings following PEP 257 / JSDoc / GoDoc.",
        "code_quality", output_key="docstrings"),
    _make_agent("TestCoverageAnalyzer", "test-coverage-analyzer",
        "Analyze line/branch coverage; suggest missing tests.",
        "Analyze coverage reports; identify untested branches; suggest targeted test cases.",
        "code_quality", output_key="coverage",
        required_tools=["shell_exec"]),
    _make_agent("CodeSmellDetector", "code-smell-detector",
        "Detect code smells (long method, god class, feature envy).",
        "Detect smells: long method, god class, feature envy, shotgun surgery, primitive obsession.",
        "code_quality", output_key="smells"),
    _make_agent("NamingConventionEnforcer", "naming-convention-enforcer",
        "Enforce naming conventions (PEP 8, Google, BEM).",
        "Enforce naming: snake_case Python, camelCase JS, BEM CSS, PascalCase classes.",
        "code_quality", output_key="violations"),
    _make_agent("ImportOrganizer", "import-organizer",
        "Sort and group imports (isort, eslint-plugin-import).",
        "Organize imports: standard lib, third-party, local; alphabetize within group.",
        "code_quality", output_key="imports"),
    _make_agent("DeprecationChecker", "deprecation-checker",
        "Detect use of deprecated APIs.",
        "Detect uses of deprecated APIs/stdlib/SDK methods; suggest replacements.",
        "code_quality", output_key="deprecations"),
    _make_agent("BreakingChangeDetector", "breaking-change-detector",
        "Detect breaking API changes (semver).",
        "Detect breaking changes: removed exports, signature changes, behavior changes, dropped params.",
        "code_quality", output_key="breaking_changes"),
]

# ---------------------------------------------------------------------------
# Architecture (10)
# ---------------------------------------------------------------------------

ARCHITECTURE_AGENTS: List[Type[BaseSubAgent]] = [
    _make_agent("SystemArchitect", "system-architect",
        "System design: components, data flow, trade-offs.",
        "Design systems with components, data flow, failure modes, and trade-offs (C4 model).",
        "architecture", output_key="design",
        max_tokens=300),
    _make_agent("ApiDesigner", "api-designer",
        "REST/GraphQL/gRPC API designer.",
        "Design APIs: REST resource modeling, GraphQL schema, gRPC contracts, error conventions.",
        "architecture", output_key="api",
        max_tokens=300),
    _make_agent("DatabaseDesigner", "database-designer",
        "Database schema designer (relational + NoSQL).",
        "Design schemas: 3NF/BCNF, indexes, FKs, partitioning, sharding, denormalization trade-offs.",
        "architecture", output_key="schema",
        max_tokens=300),
    _make_agent("MicroserviceArchitect", "microservice-architect",
        "Microservices decomposition and contracts.",
        "Decompose monoliths: bounded contexts, service boundaries, contracts, saga choreography.",
        "architecture", output_key="design",
        max_tokens=300),
    _make_agent("EventDrivenArchitect", "event-driven-architect",
        "Event-driven: Kafka, RabbitMQ, NATS, event sourcing.",
        "Design event-driven systems: topics, schemas (Avro/Proto), outbox, idempotency, replay.",
        "architecture", output_key="design",
        max_tokens=300),
    _make_agent("CqrsArchitect", "cqrs-architect",
        "CQRS + Event Sourcing architect.",
        "Apply CQRS: separate read/write models, projections, snapshots, eventual consistency.",
        "architecture", output_key="design",
        max_tokens=300),
    _make_agent("HexagonalArchitect", "hexagonal-architect",
        "Hexagonal/Ports-and-Adapters architect.",
        "Apply hexagonal architecture: domain core, ports, adapters, dependency inversion.",
        "architecture", output_key="design",
        max_tokens=300),
    _make_agent("DddArchitect", "ddd-architect",
        "Domain-Driven Design (DDD) strategist.",
        "Apply DDD: aggregates, entities, value objects, domain events, ubiquitous language.",
        "architecture", output_key="design",
        max_tokens=300),
    _make_agent("CloudArchitect", "cloud-architect",
        "Cloud architecture (AWS/GCP/Azure).",
        "Design cloud-native: VPC, IAM, multi-AZ, serverless vs containers, cost/perf trade-offs.",
        "architecture", output_key="design",
        max_tokens=300),
    _make_agent("SecurityArchitect", "security-architect",
        "Security architecture: zero trust, threat models.",
        "Design security: zero trust, defense in depth, threat models (STRIDE), secure defaults.",
        "architecture", output_key="threat_model",
        max_tokens=300),
]

# ---------------------------------------------------------------------------
# DevOps (12)
# ---------------------------------------------------------------------------

DEVOPS_AGENTS: List[Type[BaseSubAgent]] = [
    _make_agent("DockerfileGenerator", "dockerfile-generator",
        "Generate optimized multi-stage Dockerfiles.",
        "Generate multi-stage Dockerfiles: minimal base, layer caching, non-root user, healthcheck.",
        "devops", output_key="dockerfile",
        required_tools=["file_write"]),
    _make_agent("KubernetesManifestCreator", "kubernetes-manifest-creator",
        "Create K8s manifests, Helm charts, Kustomize overlays.",
        "Write K8s manifests: Deployment, Service, Ingress, HPA, PDB, NetworkPolicy, SecurityContext.",
        "devops", output_key="manifests",
        max_tokens=300),
    _make_agent("TerraformSpecialist", "terraform-specialist",
        "Terraform: modules, state, drift, providers.",
        "Write Terraform: modules, remote state, providers, drift remediation, OPA policies.",
        "devops", output_key="tf",
        max_tokens=300),
    _make_agent("GithubActionsAuthor", "github-actions-author",
        "Author GitHub Actions workflows.",
        "Author workflows: matrix, reusable workflows, OIDC, caching, secrets, composite actions.",
        "devops", output_key="workflows",
        max_tokens=300),
    _make_agent("CiCdDebugger", "ci-cd-debugger",
        "Debug CI/CD pipeline failures.",
        "Debug failing pipelines: read logs, identify flaky tests, race conditions, cache invalidation.",
        "devops", output_key="diagnosis",
        required_tools=["shell_exec", "file_read"]),
    _make_agent("MonitoringSetup", "monitoring-setup",
        "Setup observability: metrics, logs, traces (Prometheus, Grafana, OTel).",
        "Setup observability: Prometheus exporters, Grafana dashboards, OpenTelemetry instrumentation.",
        "devops", output_key="setup",
        max_tokens=300),
    _make_agent("LogAnalyzer", "log-analyzer",
        "Analyze logs (Loki, ELK, CloudWatch).",
        "Analyze logs: parse patterns, find anomalies, error budgets, noisy log reduction.",
        "devops", output_key="analysis",
        max_tokens=300),
    _make_agent("MetricsCollector", "metrics-collector",
        "Define and collect SLI/SLO metrics.",
        "Define RED/USE metrics, SLIs, SLOs, error budgets; align with Prometheus conventions.",
        "devops", output_key="metrics",
        max_tokens=300),
    _make_agent("AlertingConfig", "alerting-config",
        "Configure alert rules (Prometheus/Alertmanager).",
        "Author alert rules: severity routing, dedup, runbook URLs, silences, multi-window burn.",
        "devops", output_key="alerts",
        max_tokens=300),
    _make_agent("SecretsRotator", "secrets-rotator",
        "Rotate secrets, manage Vault, KMS, IAM keys.",
        "Plan secret rotation: Vault leases, KMS, IAM key age, break-glass, audit trail.",
        "devops", output_key="plan",
        max_tokens=300),
    _make_agent("BackupStrategist", "backup-strategist",
        "Backup strategy: 3-2-1, RPO/RTO.",
        "Design backups: 3-2-1 rule, RPO/RTO, snapshot frequency, restore drills, encryption at rest.",
        "devops", output_key="plan",
        max_tokens=300),
    _make_agent("DisasterRecoveryPlanner", "disaster-recovery-planner",
        "DR planning: regions, runbooks, drills.",
        "Plan DR: warm/cold standby, region failover, runbook, chaos drills, RTO targets.",
        "devops", output_key="plan",
        max_tokens=300),
]

# ---------------------------------------------------------------------------
# Testing (10)
# ---------------------------------------------------------------------------

TESTING_AGENTS: List[Type[BaseSubAgent]] = [
    _make_agent("UnitTestGenerator", "unit-test-generator",
        "Generate unit tests (pytest, JUnit, Go test).",
        "Write unit tests with Arrange-Act-Assert; cover edge cases; use parametrize/table-driven.",
        "testing", output_key="tests",
        required_skills=["rtk-tdd", "test-driven-development"],
        required_tools=["file_read", "file_write", "shell_exec"]),
    _make_agent("IntegrationTestGenerator", "integration-test-generator",
        "Integration tests: real DBs, services, contracts.",
        "Write integration tests using testcontainers, real DBs, contract tests (Pact).",
        "testing", output_key="tests",
        required_tools=["file_read", "file_write", "shell_exec"]),
    _make_agent("E2ETestGenerator", "e2e-test-generator",
        "E2E tests (Playwright, Cypress, Selenium).",
        "Write E2E tests with Playwright/Cypress: page objects, retries, trace on failure.",
        "testing", output_key="tests",
        required_tools=["file_write"]),
    _make_agent("MutationTester", "mutation-tester",
        "Run mutation testing (mutmut, Stryker, PIT).",
        "Run mutation testing, interpret scores, suggest test improvements to kill mutants.",
        "testing", output_key="mutations",
        required_tools=["shell_exec"]),
    _make_agent("PropertyBasedTester", "property-based-tester",
        "Property-based tests (Hypothesis, fast-check).",
        "Generate property-based tests: invariants, generators, shrinkers, replay seeds.",
        "testing", output_key="tests",
        required_tools=["file_write"]),
    _make_agent("FuzzTester", "fuzz-tester",
        "Fuzz testing (AFL++, libFuzzer, Atheris).",
        "Configure fuzzing harnesses, corpus, coverage, crash triage, ASan integration.",
        "testing", output_key="harness",
        required_tools=["shell_exec"]),
    _make_agent("LoadTester", "load-tester",
        "Load/stress tests (k6, Locust, JMeter).",
        "Design load tests: ramp-up, soak, spike, RPS, latency SLOs, breaking point analysis.",
        "testing", output_key="scenarios",
        max_tokens=300),
    _make_agent("SecurityPenTester", "security-pen-tester",
        "Penetration testing reconnaissance and exploitation.",
        "Perform pen tests: recon, scanning, exploitation, OWASP Top 10, post-exploitation.",
        "testing", output_key="findings",
        required_tools=["shell_exec"]),
    _make_agent("AccessibilityTester", "accessibility-tester",
        "A11y testing (axe, pa11y, VoiceOver).",
        "Test WCAG 2.1 AA: contrast, ARIA, keyboard, screen reader flows, focus order.",
        "testing", output_key="a11y_audit",
        required_tools=["shell_exec"]),
    _make_agent("VisualRegressionTester", "visual-regression-tester",
        "Visual regression (Percy, Chromatic, Playwright).",
        "Set up visual regression: baselines, threshold tuning, ignore regions, CI integration.",
        "testing", output_key="config",
        required_tools=["file_write"]),
]

# ---------------------------------------------------------------------------
# Documentation (8)
# ---------------------------------------------------------------------------

DOCS_AGENTS: List[Type[BaseSubAgent]] = [
    _make_agent("ApiDocGenerator", "api-doc-generator",
        "Generate API docs (OpenAPI, GraphQL SDL, gRPC).",
        "Generate OpenAPI 3.1 from code, or hand-author with examples and error responses.",
        "documentation", output_key="api_docs",
        required_tools=["file_write"]),
    _make_agent("ReadmeWriter", "readme-writer",
        "Write a strong README with quickstart, install, usage.",
        "Write a README: tagline, badges, install, quickstart, usage, config, contributing, license.",
        "documentation", output_key="readme",
        required_tools=["file_write"]),
    _make_agent("ChangelogGenerator", "changelog-generator",
        "Generate changelogs from conventional commits.",
        "Generate CHANGELOG.md from conventional commits, grouped by Added/Changed/Fixed/Removed.",
        "documentation", output_key="changelog",
        required_tools=["file_write"]),
    _make_agent("TutorialWriter", "tutorial-writer",
        "Step-by-step tutorials with code samples.",
        "Write progressive tutorials: clear goals, working code, checkpoints, troubleshooting.",
        "documentation", output_key="tutorial",
        required_tools=["file_write"]),
    _make_agent("ArchitectureDiagrammer", "architecture-diagrammer",
        "C4 / Mermaid architecture diagrams.",
        "Create C4 or Mermaid diagrams: context, container, component, sequence, deployment.",
        "documentation", output_key="diagrams",
        required_tools=["file_write"]),
    _make_agent("AdrWriter", "adr-writer",
        "Architecture Decision Records (ADR/Nygard).",
        "Write ADRs: status, context, decision, consequences, alternatives, follow-ups.",
        "documentation", output_key="adr",
        required_tools=["file_write"]),
    _make_agent("RunbookAuthor", "runbook-author",
        "Operational runbooks with steps, checks, rollback.",
        "Write runbooks: purpose, alerts, diagnosis steps, mitigation, rollback, comms, postmortem.",
        "documentation", output_key="runbook",
        required_tools=["file_write"]),
    _make_agent("FaqGenerator", "faq-generator",
        "Generate FAQs from docs, issues, support tickets.",
        "Generate FAQs: scope the audience, draft Q/A, link to canonical docs, keep concise.",
        "documentation", output_key="faq",
        required_tools=["file_write"]),
]

# ---------------------------------------------------------------------------
# Data (10)
# ---------------------------------------------------------------------------

DATA_AGENTS: List[Type[BaseSubAgent]] = [
    _make_agent("SqlOptimizer", "sql-optimizer",
        "Optimize SQL queries (EXPLAIN, indexes, rewrites).",
        "Read EXPLAIN plans, propose indexes, rewrite queries, avoid N+1, partition pruning.",
        "data", output_key="optimization",
        required_tools=["file_read", "shell_exec"]),
    _make_agent("DataMigrationPlanner", "data-migration-planner",
        "Plan DB migrations: online, dual-write, backout.",
        "Plan online migrations: dual-write, expand-contract, backout, validation queries.",
        "data", output_key="plan",
        max_tokens=300),
    _make_agent("SchemaValidator", "schema-validator",
        "Validate schemas: Avro, Protobuf, JSON Schema.",
        "Validate schemas: backward/forward compatibility, default evolution, breaking changes.",
        "data", output_key="validation",
        required_tools=["file_read"]),
    _make_agent("EtlPipelineBuilder", "etl-pipeline-builder",
        "Build ETL/ELT pipelines (Airflow, dbt, Spark).",
        "Design ELT/ETL: idempotency, partitioning, late-arriving data, DQ checks, retries.",
        "data", output_key="pipeline",
        max_tokens=300),
    _make_agent("DataQualityChecker", "data-quality-checker",
        "Data quality: completeness, validity, consistency, freshness.",
        "Define DQ checks: completeness, validity, uniqueness, consistency, freshness, anomaly.",
        "data", output_key="checks",
        max_tokens=300),
    _make_agent("SchemaEvolver", "schema-evolver",
        "Schema evolution: backward-compatible migrations.",
        "Plan schema evolution: backward/forward compatible, default values, dual-read/write.",
        "data", output_key="plan",
        max_tokens=300),
    _make_agent("QueryTuner", "query-tuner",
        "Tune queries: hints, plan stability, parameter sniffing.",
        "Tune: parameter sniffing, plan guides, optimizer hints, statistics, plan stability.",
        "data", output_key="tuning",
        max_tokens=300),
    _make_agent("IndexAdvisor", "index-advisor",
        "Recommend indexes (columnstore, covering, partial).",
        "Recommend indexes: B-tree, covering, partial, columnstore, expression; trade-off vs writes.",
        "data", output_key="indexes",
        max_tokens=300),
    _make_agent("PartitionStrategist", "partition-strategist",
        "Partitioning strategy: range/hash/list/composite.",
        "Design partitioning: range, hash, list, composite, time-bucketing, retention policies.",
        "data", output_key="strategy",
        max_tokens=300),
    _make_agent("BackupValidator", "backup-validator",
        "Validate backup integrity, restore drills.",
        "Validate backups: checksums, restore drills, point-in-time, corruption checks, offsite.",
        "data", output_key="plan",
        max_tokens=300),
]

# ---------------------------------------------------------------------------
# Security (8)
# ---------------------------------------------------------------------------

SECURITY_AGENTS: List[Type[BaseSubAgent]] = [
    _make_agent("OwaspScanner", "owasp-scanner",
        "OWASP Top 10 + API Top 10 scanner.",
        "Scan against OWASP Top 10 and API Security Top 10; report findings with CWE references.",
        "security", output_key="findings",
        required_tools=["shell_exec"]),
    _make_agent("SecretsScanner", "secrets-scanner",
        "Detect committed secrets (gitleaks, trufflehog).",
        "Scan for hardcoded secrets, API keys, tokens, private keys, .env leaks.",
        "security", output_key="leaks",
        required_tools=["shell_exec"]),
    _make_agent("DependencyVulnChecker", "dependency-vuln-checker",
        "CVE check (pip-audit, npm audit, OSV, Snyk).",
        "Check deps for known CVEs; suggest upgrades; align with CVSS and EPSS scores.",
        "security", output_key="cves",
        required_tools=["shell_exec"]),
    _make_agent("ThreatModeler", "threat-modeler",
        "Threat modeling (STRIDE, PASTA, attack trees).",
        "Build threat model: STRIDE, attack trees, mitigations, residual risk, prioritize.",
        "security", output_key="threat_model",
        max_tokens=300),
    _make_agent("SecurityPolicyWriter", "security-policy-writer",
        "Author security policies: BCP, IR, key mgmt.",
        "Author security policy: classification, access, encryption, IR, key management, training.",
        "security", output_key="policy",
        required_tools=["file_write"]),
    _make_agent("PiiDetector", "pii-detector",
        "Detect PII (email, phone, SSN, credit card, IP).",
        "Detect PII in text/logs/DBs; suggest masking/tokenization/encryption strategies.",
        "security", output_key="pii_findings",
        required_tools=["shell_exec"]),
    _make_agent("EncryptionAdvisor", "encryption-advisor",
        "Encryption: at rest, in transit, key mgmt.",
        "Recommend encryption: at rest (AES-GCM, envelope), in transit (TLS 1.3), key mgmt (KMS).",
        "security", output_key="advice",
        max_tokens=300),
    _make_agent("AuthFlowReviewer", "auth-flow-reviewer",
        "Auth/authz review: OAuth2/OIDC, JWT, SAML, RBAC.",
        "Review auth flows: OAuth2/OIDC grants, JWT hygiene, session, RBAC/ABAC, MFA.",
        "security", output_key="review",
        max_tokens=300),
]

# ---------------------------------------------------------------------------
# Frontend (7)
# ---------------------------------------------------------------------------

FRONTEND_AGENTS: List[Type[BaseSubAgent]] = [
    _make_agent("ReactComponentGenerator", "react-component-generator",
        "React components: hooks, TS, a11y, tests.",
        "Generate React components: TypeScript, hooks, a11y, ARIA, Storybook story, RTL test.",
        "frontend", output_key="component",
        required_skills=["frontend-design"],
        required_tools=["file_write"]),
    _make_agent("CssOptimizer", "css-optimizer",
        "Optimize CSS: dedup, purge, critical CSS.",
        "Optimize CSS: purge unused, dedupe, critical CSS, container queries, layer order.",
        "frontend", output_key="css",
        required_tools=["file_write"]),
    _make_agent("AccessibilityAuditor", "accessibility-auditor",
        "A11y audit: WCAG 2.1/2.2, axe-core.",
        "Audit UI: WCAG 2.1/2.2 AA, axe-core, color contrast, focus order, semantic markup.",
        "frontend", output_key="audit",
        required_tools=["shell_exec"]),
    _make_agent("PerformanceBudgetChecker", "performance-budget-checker",
        "Perf budgets: LCP, INP, CLS, JS size.",
        "Enforce budgets: LCP <2.5s, INP <200ms, CLS <0.1, JS <170KB, image sizes.",
        "frontend", output_key="report",
        max_tokens=300),
    _make_agent("BundleAnalyzer", "bundle-analyzer",
        "Bundle analysis: code-split, tree-shake, source maps.",
        "Analyze bundle: webpack/vite, code-splitting, dynamic imports, tree-shaking, source maps.",
        "frontend", output_key="analysis",
        max_tokens=300),
    _make_agent("SeoAuditor", "seo-auditor",
        "SEO audit: meta, schema, sitemaps, Core Web Vitals.",
        "Audit SEO: meta tags, OG, JSON-LD, sitemap, robots, Core Web Vitals, mobile-first.",
        "frontend", output_key="audit",
        max_tokens=300),
    _make_agent("PwaValidator", "pwa-validator",
        "PWA: manifest, service worker, install, offline.",
        "Validate PWA: manifest, service worker, install prompt, offline, push, background sync.",
        "frontend", output_key="pwa_report",
        max_tokens=300),
]

# ---------------------------------------------------------------------------
# Utility / extra (4) — to push total >100
# ---------------------------------------------------------------------------

UTILITY_AGENTS: List[Type[BaseSubAgent]] = [
    _make_agent("IncidentResponder", "incident-responder",
        "Incident response: triage, comms, mitigation, postmortem.",
        "Coordinate IR: severity, comms cadence, mitigation, status page, blameless postmortem.",
        "utility", output_key="plan",
        max_tokens=300),
    _make_agent("CapacityPlanner", "capacity-planner",
        "Capacity planning: headroom, scaling, cost.",
        "Plan capacity: headroom, growth projections, autoscaling, cost modeling, right-sizing.",
        "utility", output_key="plan",
        max_tokens=300),
    _make_agent("FinopsAnalyst", "finops-analyst",
        "FinOps: cloud cost analysis and optimization.",
        "Analyze cloud cost: identify waste, reserved/spot strategy, showback, unit economics.",
        "utility", output_key="report",
        max_tokens=300),
    _make_agent("PerformanceProfiler", "performance-profiler",
        "Performance profiling: flamegraphs, hotspots.",
        "Profile: flamegraphs (py-spy, async-profiler), hot path, allocations, N+1, locks.",
        "utility", output_key="profile",
        max_tokens=300),
]

# ---------------------------------------------------------------------------
# Combined registry
# ---------------------------------------------------------------------------

ALL_EXTENDED: List[Type[BaseSubAgent]] = (
    CODE_QUALITY_AGENTS
    + ARCHITECTURE_AGENTS
    + DEVOPS_AGENTS
    + TESTING_AGENTS
    + DOCS_AGENTS
    + DATA_AGENTS
    + SECURITY_AGENTS
    + FRONTEND_AGENTS
    + UTILITY_AGENTS
)

EXTENDED_AGENT_REGISTRY: dict[str, Type[BaseSubAgent]] = {
    cls.name: cls for cls in ALL_EXTENDED
}


def register_extended_agents(target: dict) -> int:
    """Merge EXTENDED_AGENT_REGISTRY into a target dict in place.

    Returns the number of new agents added (skipping names already present).
    """
    added = 0
    for name, cls in EXTENDED_AGENT_REGISTRY.items():
        if name not in target:
            target[name] = cls
            added += 1
    return added


__all__ = [
    "EXTENDED_AGENT_REGISTRY",
    "ALL_EXTENDED",
    "CODE_QUALITY_AGENTS",
    "ARCHITECTURE_AGENTS",
    "DEVOPS_AGENTS",
    "TESTING_AGENTS",
    "DOCS_AGENTS",
    "DATA_AGENTS",
    "SECURITY_AGENTS",
    "FRONTEND_AGENTS",
    "UTILITY_AGENTS",
    "register_extended_agents",
]
