---
title: LLM Observability and Agent Evaluation
kind: concept
tags:
- concept
- llm
- observability
- evaluation
---

# LLM Observability and Agent Evaluation
- The CV describes an observability architecture for multi-step agent workflows that captures token usage, model cost, latency, errors, model metadata, tool calls, execution paths, and agent outcomes.
- Telemetry schemas cover agent, graph, model, prompt, tool, and skill metadata, with redaction and controlled storage of sensitive information.
- Evaluation pipelines use PostgreSQL, pgvector, and DeepEval for agent assessment, dataset generation, failure analysis, and performance-informed model routing.
- Monitoring components include OpenTelemetry, Grafana, Prometheus, Loki, and distributed tracing pipelines.
- Primary experience: [[experience/teradata-agentic-ai]].
