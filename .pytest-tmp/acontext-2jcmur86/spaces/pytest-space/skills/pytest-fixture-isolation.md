---
name: pytest-fixture-isolation
description: Use tmp_path fixture for filesystem tests to avoid clobbering state.
created_at: "2026-06-04T09:23:33Z"
updated_at: "2026-06-04T09:23:33Z"
version: 1
tags:
  - pytest
  - testing
  - isolation
---

## Context
Writing pytest tests that touch the filesystem.

## Rule
Use the `tmp_path` fixture (or `tmp_path_factory`) for any disk write. Never write to the repo root or to `~/.graxia` from a unit test.

## Why
Tests must be hermetic — running them twice should give the same result.
