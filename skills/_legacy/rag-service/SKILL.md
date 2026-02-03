---
name: rag-service
description: RAG-as-a-Service (port 8020, Qdrant vector DB)
type: service
triggers:
  - rag-service
  - rag
  - 벡터
  - vector search
health_checks:
  - name: api_health
    command: "curl -sf http://localhost:8020/health -o /dev/null && echo OK || echo FAIL"
    expect: "OK"
    severity: critical
  - name: qdrant_health
    command: "curl -sf http://localhost:6333/collections -o /dev/null && echo OK || echo FAIL"
    expect: "OK"
    severity: critical
fix_actions:
  - trigger: "api_health"
    command: "pm2 restart rag-service"
    verify: "sleep 5 && curl -sf http://localhost:8020/health -o /dev/null && echo OK"
  - trigger: "qdrant_health"
    command: "docker restart qdrant"
    verify: "sleep 10 && curl -sf http://localhost:6333/collections -o /dev/null && echo OK"
---
# RAG-Service

- API: PM2 rag-service, port 8020, /home/reze/rag-service/backend
- Vector DB: Docker qdrant, port 6333
- Domain: rag.runstate.dev
- Health: GET http://localhost:8020/health
- Restart: pm2 restart rag-service
- Qdrant: curl http://localhost:6333/collections
- Logs: pm2 logs rag-service --lines 50
