---
name: configure-pytest-markers
description: <= 140 chars
created_at: "2026-06-04T11:46:59Z"
updated_at: "2026-06-04T11:46:59Z"
source_session: integration-sess-1
version: 1
tags:
  - pytest
---

Use `-m slow` to select slow tests, or `-m 'not slow'` to skip them. Add `addopts = -m 'not slow'` to pytest.ini for the default.

Add a custom marker in pytest.ini under the [pytest] section with `markers = slow: marks tests as slow (deselect with '-m "not slow"')`. Then decorate the test with `@pytest.mark.slow`.
