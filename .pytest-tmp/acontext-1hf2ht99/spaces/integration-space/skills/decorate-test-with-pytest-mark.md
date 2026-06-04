---
name: decorate-test-with-pytest-mark
description: <= 140 chars
created_at: "2026-06-04T09:41:10Z"
updated_at: "2026-06-04T09:41:10Z"
source_session: integration-sess-1
version: 1
tags:
  - pytest
---

@pytest.mark.slow
# Test that slow tests are run on CI
pytest -c pytest.ini
