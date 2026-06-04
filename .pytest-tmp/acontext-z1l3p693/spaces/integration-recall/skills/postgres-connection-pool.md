---
name: postgres-connection-pool
description: Use a connection pool (pgbouncer) in front of PostgreSQL.
created_at: "2026-06-04T11:11:45Z"
updated_at: "2026-06-04T11:11:45Z"
version: 1
tags:
  - postgres
  - ops
---

For serverless or high-concurrency workloads, put pgbouncer in transaction-pooling mode in front of PostgreSQL. Don't pool long-lived sessions — only short transactions.
