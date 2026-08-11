---
title: Enterprise Agentic AI Platform
kind: project
tags:
- project
- agentic-ai
- llm
- teradata
---

# Enterprise Agentic AI Platform

An internal enterprise Agentic AI platform developed for production use at Teradata. The platform supports agent development, execution, evaluation, observability, and reusable skill integration.

## Capabilities
- LangGraph-based LLM workflows
- Structured tool execution and MCP-based integrations
- Reusable agent skills and skill discovery
- Retrieval-Augmented Generation
- Agent onboarding, deployment, versioning, and operations
- Initial architecture supporting five production agents
- Python and FastAPI backend services
- Docker Compose and Kubernetes environments

## Observability and evaluation
- OpenTelemetry-based capture of token usage, model cost, latency, errors, model metadata, tool calls, execution paths, and agent outcomes
- Grafana, Prometheus, Loki, and distributed tracing integrations
- PostgreSQL, pgvector, and DeepEval evaluation and analytics pipelines
- Dataset generation, failure analysis, and performance-informed model-routing decisions
- Telemetry schemas for agent, graph, model, prompt, tool, and skill metadata
- Redaction and controlled storage of sensitive information

## Related pages
- [[skills/llm-observability|LLM Evaluation and Observability]]
- [[skills/production-ai-engineering|Production AI Engineering]]
- [[concepts/agentic-ai-platform-design|Agentic AI Platform Design]]
- Source: [[sources/cv-ogc-ai|CV — Othón González]]
