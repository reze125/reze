---
name: docker-infra
description: Docker 인프라 관리 (21 컨테이너)
type: infra
triggers:
  - docker
  - 컨테이너
  - container
  - n8n
  - dify
  - flowise
  - listmonk
  - paintingan
health_checks:
  - name: docker_daemon
    command: "docker info > /dev/null 2>&1 && echo OK || echo FAIL"
    expect: "OK"
    severity: critical
  - name: n8n_health
    command: "curl -sf http://localhost:5678 -o /dev/null && echo OK || echo FAIL"
    expect: "OK"
    severity: warning
  - name: dify_health
    command: "curl -sf http://localhost:3001 -o /dev/null && echo OK || echo FAIL"
    expect: "OK"
    severity: warning
  - name: qdrant_health
    command: "curl -sf http://localhost:6333/collections -o /dev/null && echo OK || echo FAIL"
    expect: "OK"
    severity: warning
fix_actions:
  - trigger: "n8n_health"
    command: "docker restart n8n"
    verify: "sleep 10 && curl -sf http://localhost:5678 -o /dev/null && echo OK"
  - trigger: "dify_health"
    command: "docker restart dify-api dify-web"
    verify: "sleep 15 && curl -sf http://localhost:3001 -o /dev/null && echo OK"
  - trigger: "qdrant_health"
    command: "docker restart qdrant"
    verify: "sleep 10 && curl -sf http://localhost:6333/collections -o /dev/null && echo OK"
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
