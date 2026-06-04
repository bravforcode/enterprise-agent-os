---
name: json-repair-prompt
description: "When the LLM returns malformed JSON, ask it to return JSON only."
created_at: "2026-06-04T09:23:33Z"
updated_at: "2026-06-04T09:23:33Z"
version: 1
tags:
  - llm
  - json
  - parsing
---

## Context
An LLM call is supposed to return strict JSON.

## Rule
If the response fails to parse:
1. Strip leading/trailing code fences.
2. Locate the first `{` and last `}` and try parsing the substring.
3. If still broken, retry with a stricter system prompt.

## Why
LLMs often add prose around the JSON; a defensive parser saves a round trip.
