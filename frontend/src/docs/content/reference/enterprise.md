# Enterprise

Commercial licensing, professional support, and deployment services for the Heym platform.

## Overview

Heym is free to use and self-host under its source-available license. For organizations that need commercial licensing, production-grade deployment assistance, or dedicated support, the Enterprise plan provides hands-on services from the Heym team.

| Service | Description |
|---------|-------------|
| **Workflow Automation Support** | Architecture reviews, workflow design guidance, and hands-on help building production automations |
| **Tool Training** | Onboarding sessions and training for your team covering the workflow editor, AI nodes, agents, and integrations |
| **Heym Q&A** | Direct access to the Heym engineering team for platform questions, best practices, and troubleshooting |
| **Kubernetes Deployment** | Assistance with multi-worker-node setups, sidecar containers, scaling strategies, and cluster configuration |
| **Solution Consulting** | Custom solution design for your specific use case, including integration planning and architecture recommendations |
| **Priority Support & SLA** | Guaranteed response times and priority issue resolution |
| **Custom Development** | Feature development and modifications tailored to your organization's requirements |

## Automation Support

The Heym team helps you design, build, and optimize workflow automations for your business processes. This includes reviewing your automation requirements, recommending node configurations, and ensuring your workflows follow best practices for reliability and performance.

Support covers all node types including [LLM](../nodes/llm-node.md), [Agent](../nodes/agent-node.md), [HTTP](../nodes/http-node.md), and [Cron](../nodes/cron-node.md) triggers — as well as advanced patterns like [multi-agent orchestration](./agent-architecture.md), [Human-in-the-Loop](./human-in-the-loop.md) checkpoints, and [parallel execution](./parallel-execution.md) across branches.

## Tool Training

Hands-on training sessions tailored to your team's skill level and use cases:

- Workflow editor and [canvas features](./canvas-features.md)
- AI-powered nodes: [LLM](../nodes/llm-node.md), [Agent](../nodes/agent-node.md), [RAG](../nodes/rag-node.md)
- [Agent architecture](./agent-architecture.md) and multi-agent orchestration
- [Credentials](./credentials.md) management and [third-party integrations](./integrations.md)
- [Triggers](./triggers.md), [webhooks](./webhooks.md), and scheduling with [Cron](../nodes/cron-node.md)
- [Expression DSL](./expression-dsl.md) and [global variables](./global-variables.md)
- [Teams](./teams.md) collaboration and [credentials sharing](./credentials-sharing.md)
- [Portal](./portal.md) deployment for customer-facing chat interfaces
- [Traces](../tabs/traces-tab.md) and [Evals](../tabs/evals-tab.md) for AI workflow observability

## Kubernetes Deployment

The standard [Running & Deployment](../getting-started/running-and-deployment.md) guide covers Docker Compose for single-server production setups. Enterprise customers receive assistance with production Kubernetes deployments for high availability and horizontal scaling:

- **Multiple worker nodes** — Distributing Heym backend workers across multiple Kubernetes nodes for redundancy and load balancing
- **Sidecar containers** — Configuring sidecar patterns for log collection, monitoring agents, service meshes (Istio, Linkerd), and secret injection (Vault)
- **Resource planning** — CPU and memory requests/limits, pod disruption budgets, and horizontal pod autoscaling policies
- **Networking** — Ingress controller configuration, TLS termination, and internal service communication between backend, frontend, and database pods
- **Persistent storage** — Database and vector store volume provisioning with appropriate StorageClass and backup strategies
- **Monitoring** — Integration with Prometheus, Grafana, or your existing observability stack for container metrics, logs, and alerts

## Solution Consulting

Every organization has unique automation needs. The Heym team provides consulting to help you:

- Evaluate whether Heym fits your specific use case
- Design end-to-end automation architectures
- Plan integrations with your existing infrastructure and third-party services
- Debug complex workflows and resolve production issues
- Migrate from other automation platforms (n8n, Zapier, Make.com)

## Contact

Reach the enterprise team at **enterprise@heym.run** for licensing inquiries, pricing, or to schedule an introductory call.

## Related

- [Running & Deployment](../getting-started/running-and-deployment.md) — Production deployment with Docker Compose
- [Security](./security.md) — Platform security practices and configuration
- [Parallel Execution](./parallel-execution.md) — Multi-worker execution model
- [Teams](./teams.md) — Team collaboration and resource sharing
- [Full Feature Set](./features.md) — Complete overview of Heym capabilities
