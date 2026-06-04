---
name: react-key-prop
description: "Always pass a stable `key` prop to list children."
created_at: "2026-06-04T10:40:00Z"
updated_at: "2026-06-04T10:40:00Z"
version: 1
tags:
  - react
  - frontend
---

When rendering arrays, give each child a unique, stable `key` based on its identity (e.g. id), not its index. Index keys cause state bugs when the list is reordered.
