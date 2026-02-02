---
name: docker-infra
description: Docker 인프라 관리 (21 컨테이너)
triggers:
  - docker
  - 컨테이너
  - container
  - n8n
  - dify
  - flowise
  - listmonk
  - paintingan
---
# Docker Infrastructure (21 containers)

## Core Services
- n8n: port 5678, n8n.runstate.dev
- Dify: dify-api, dify-worker, dify-web (port 3001), dify-redis, dify-weaviate, dify-sandbox
- Flowise: port 3033

## Vector DBs
- Qdrant: port 6333
- ChromaDB: port 8010

## Databases
- quotepilot-db: PostgreSQL port 5433
- listmonk-db: PostgreSQL (listmonk 전용)

## Other
- Listmonk: port 9000 (이메일 마케팅)
- Paintingan: ports 8200-8201 (AI 아트)
- wordpress-shop: port 8080

## Commands
- 전체 상태: docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
- 로그: docker logs --tail 50 {container_name}
- 재시작: docker restart {container_name}
- 정리: docker system prune -f
