# Crypto Radar Terraform

Этот каталог фиксирует границу IaC для production/staging инфраструктуры.
В MVP локальный стек запускается через Docker Compose, а Kubernetes ресурсы
описаны Helm chart в `infra/helm/crypto-radar`.

Планируемые managed-компоненты:

- PostgreSQL для бизнес-данных.
- Redis Cluster для hot state.
- NATS JetStream для событий.
- ClickHouse для market data и аналитики.
- Kubernetes для backend API, realtime gateway и workers.
- OpenTelemetry, Prometheus, Grafana, Loki для observability.
