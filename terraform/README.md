# Enterprise Agent OS - Production Deployment

This directory contains production deployment configuration for Agent OS.

## Architecture

```
Internet
   │
   ▼
[Route 53] → [CloudFront/CDN]
   │
   ▼
[ALB / NGINX Ingress]
   │
   ▼
[Kubernetes Cluster (EKS)]
   │
   ├── agent-os-api (3-20 pods, autoscaling)
   │   ├── FastAPI + Uvicorn
   │   ├── Redis client (cache)
   │   ├── PostgreSQL client (async)
   │   └── Qdrant client (vectors)
   │
   ├── PostgreSQL (RDS, Multi-AZ, encrypted)
   ├── Redis (ElastiCache, cluster mode)
   └── Qdrant (Qdrant Cloud or self-hosted)
```

## Quick Start

### Prerequisites
- Terraform >= 1.6
- Helm >= 3.13
- kubectl >= 1.28
- AWS CLI configured

### 1. Provision infrastructure
```bash
cd terraform
terraform init
terraform plan -out=tfplan
terraform apply tfplan
```

### 2. Configure kubectl
```bash
aws eks update-kubeconfig --region us-east-1 --name agent-os-eks
```

### 3. Install NGINX ingress + cert-manager
```bash
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm repo add cert-manager https://charts.jetstack.io
helm repo update
helm install ingress-nginx ingress-nginx/ingress-nginx
helm install cert-manager cert-manager/cert-manager --set installCRDs=true
```

### 4. Install Agent OS
```bash
cd ..
helm install agent-os ./helm/agent-os \
  --namespace agent-os \
  --create-namespace \
  --set secrets.databaseUrl="postgresql+asyncpg://user:pass@host:5432/agentos" \
  --set secrets.redisUrl="redis://host:6379/0" \
  --set secrets.jwtSecret="<random-256-bit>" \
  --set secrets.llmApiKey="<your-llm-key>"
```

### 5. Verify
```bash
kubectl get pods -n agent-os
curl https://api.agent-os.example.com/health
```

## High Availability Features

- **Multi-AZ deployment**: Pods distributed across 3 AZs
- **Database**: RDS Multi-AZ with automated failover
- **Cache**: Redis cluster with automatic failover
- **Autoscaling**: HPA scales 3-20 pods based on CPU/memory
- **Pod Disruption Budget**: Ensures minimum 1 pod during updates
- **Network Policies**: Strict ingress/egress rules
- **Security**: Non-root containers, read-only filesystem, dropped capabilities
- **TLS**: Let's Encrypt automatic certificate management
- **Rate limiting**: 100 req/min at ingress level

## Disaster Recovery

- **RDS**: Automated daily backups, 7-day retention, point-in-time recovery
- **Redis**: Daily snapshots, 5-day retention
- **Persistent volumes**: EBS gp3 with snapshots
- **State**: Terraform state in S3 with DynamoDB locking

## Cost Optimization

- **Right-sizing**: Default `db.r6g.large` for ~100 RPS
- **Spot instances**: Configure for non-prod environments
- **Auto-scaling**: Scale down to 3 pods during low traffic
- **Redis eviction**: `allkeys-lru` for automatic cache management
- **Log retention**: 30 days in CloudWatch

## Monitoring

- **Metrics**: Prometheus scrapes `/metrics` endpoint
- **Logs**: Structured JSON to stdout, shipped via Fluent Bit
- **Traces**: OpenTelemetry-compatible
- **Alerts**: PagerDuty integration via AlertManager
