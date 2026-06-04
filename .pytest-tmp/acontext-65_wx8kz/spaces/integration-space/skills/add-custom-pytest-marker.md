---
name: add-custom-pytest-marker
description: <= 140 chars
created_at: "2026-06-04T09:23:51Z"
updated_at: "2026-06-04T09:23:51Z"
source_session: integration-sess-1
version: 1
tags:
  - pytest
---

Register the marker in pytest.ini under the [pytest] section with `markers = slow: marks tests as slow (deselect with '-m "not slow"')`. Then decorate the test with `@pytest.mark.slow`.
