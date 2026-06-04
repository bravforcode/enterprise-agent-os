---
name: python-venv-activation
description: Always use a venv before pip install on Windows.
created_at: "2026-06-04T09:40:56Z"
updated_at: "2026-06-04T09:40:56Z"
version: 1
tags:
  - python
  - windows
  - setup
---

## Context
Working on a Windows dev box.

## Rule
Activate the project's venv before running `pip install`:

```
.venv\Scripts\activate
```

## Why
Global pip installs pollute the system Python and break other tools.
