---
name: configure-pytest-to-run-slow-tests-on-ci
description: <= 140 chars
created_at: "2026-06-04T10:40:00Z"
updated_at: "2026-06-04T10:40:00Z"
source_session: integration-sess-1
version: 1
tags:
  - pytest
---

Use `-m slow` or `-m 'not slow'` to select slow tests, and add `addopts = -m 'not slow'` to pytest.ini.
