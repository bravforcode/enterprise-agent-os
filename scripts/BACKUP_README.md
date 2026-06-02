# Graxia Tool — Backup & Disaster Recovery

## Overview

Graxia Tool uses multiple data stores that need regular backups:

| Store | Data | Backup Script | Frequency |
|-------|------|---------------|-----------|
| PostgreSQL | Cache, audit logs, cost records, tenants | `backup_postgres.sh` | Daily |
| Qdrant | Vector memories | `backup_qdrant.sh` | Daily |
| Redis | Prompt cache, rate limit counters | Ephemeral (rebuilt) | N/A |
| Obsidian Vault | User notes | Git/Syncthing | Continuous |

## Quick Start

```bash
# Backup everything
./scripts/backup_postgres.sh
./scripts/backup_qdrant.sh

# Restore from backup
./scripts/restore_postgres.sh ./backups/postgres_2026-01-15_120000.sql.gz
```

## Automated Backups (Kubernetes CronJob)

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: graxia-backup
spec:
  schedule: "0 2 * * *"  # 2 AM daily
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: backup
            image: graxia-tool:latest
            command: ["/scripts/backup_postgres.sh"]
            volumeMounts:
            - name: backups
              mountPath: /backups
          restartPolicy: OnFailure
          volumes:
          - name: backups
            persistentVolumeClaim:
              claimName: graxia-backups
```

## Backup Retention

- Daily backups: kept 30 days
- Weekly backups: kept 12 weeks
- Monthly backups: kept 12 months

## Disaster Recovery

| Scenario | Recovery Time | Steps |
|----------|---------------|-------|
| Single pod failure | < 1 min | K8s auto-restart |
| Database corruption | 5-30 min | Restore from latest backup |
| Full region loss | 1-4 hours | Restore from cross-region replica |
| Accidental data loss | 5-30 min | Point-in-time recovery |

## Cross-Region Replication

For production:
- PostgreSQL: use AWS RDS read replicas or streaming replication
- Qdrant: enable distributed mode with 3+ nodes across regions
- Backups: copy to S3/GCS with cross-region replication
