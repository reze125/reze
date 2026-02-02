---
name: rag-service
description: RAG-as-a-Service (port 8020, Qdrant vector DB)
triggers:
  - rag-service
  - rag
  - 벡터
  - vector search
---
# RAG-Service

- API: PM2 rag-service, port 8020, /home/reze/rag-service/backend
- Vector DB: Docker qdrant, port 6333
- Domain: rag.runstate.dev
- Health: GET http://localhost:8020/health
- Restart: pm2 restart rag-service
- Qdrant: curl http://localhost:6333/collections
- Logs: pm2 logs rag-service --lines 50
