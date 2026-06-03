# Agent Instructions

## Auto-Routing (MANDATORY)

Every prompt → `AutoRouter().route(prompt)` → skills, RAG, agent, model, tools.

Flow: Cache → Route → Skills → Recall → Execute → Store.

## lean-ctx

Prefer lean-ctx MCP tools over native equivalents for token savings.

## RTK

All CLI commands must use `rtk` prefix.

## Skills

Skills auto-load via `skill` tool. Available: brainstorming, caveman, lean-ctx, systematic-debugging, rtk-tdd, web-search, mcp-builder, pdf, docx, pptx, xlsx, imagegen, and 80+ more.
