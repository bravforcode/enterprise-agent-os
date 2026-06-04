---
name: docker-build-cache
description: Use BuildKit cache mounts to speed up Docker builds.
created_at: "2026-06-04T11:11:45Z"
updated_at: "2026-06-04T11:11:45Z"
version: 1
tags:
  - docker
  - performance
---

Add `--mount=type=cache,target=/root/.cache/pip` to RUN steps that install Python packages. This keeps pip's download cache between builds and cuts install time by 50-80%.
