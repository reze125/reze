---
name: server-management
description: 서버 인프라 관리 — Docker 컨테이너, PM2 프로세스, 시스템 리소스 모니터링
type: infra
triggers:
  - 서버
  - server
  - docker
  - container
  - 컨테이너
  - pm2
  - process
  - 프로세스
  - 디스크
  - disk
  - 메모리
  - memory
  - CPU
  - cpu
  - 시스템
  - system
  - 포트
  - port
  - 로그
  - log
health_checks:
  - name: disk_usage
    command: "df / --output=pcent | tail -1 | tr -d ' %'"
    verify_check: "int(output) < 85"
    severity: warning
  - name: memory_usage
    command: "free | grep Mem | awk '{printf \"%.0f\", $3/$2*100}'"
    verify_check: "int(output) < 90"
    severity: warning
  - name: pm2_running
    command: "pm2 list --no-color | grep -c online"
    verify_check: "int(output) >= 5"
    severity: critical
fix_actions:
  - trigger: "disk_usage"
    command: "docker system prune -f --volumes 2>/dev/null; find /tmp -type f -mtime +7 -delete 2>/dev/null; echo done"
    verify: "df / --output=pcent | tail -1 | tr -d ' %'"
---

# Server Management

## 서버 구성
- OS: Ubuntu 24, Python 3.12.3
- 위치: /home/reze/

## Docker 컨테이너 (19개)
| 이름 | 포트 | 용도 |
|------|------|------|
| n8n | 5678 | 워크플로우 자동화 |
| dify | 3001 | AI 플랫폼 |
| flowise | 3033 | AI 플로우 빌더 |
| qdrant | 6333 | 벡터 DB |
| chromadb | 8010 | 벡터 DB |
| listmonk | 9000 | 이메일 마케팅 |
| quotepilot-db | 5433 | PostgreSQL |
| paintingan-api | 8201 | 이미지 생성 |

## PM2 프로세스 (9개)
| 이름 | 용도 |
|------|------|
| ai-tools-lab | AI Tools Lab 블로그 (Next.js) |
| postpilot-api, postpilot-web | PostPilot SaaS |
| browserpilot-api | BrowserPilot SaaS |
| agenthub-api | AgentHub 마켓플레이스 |
| quotepilot-api | QuotePilot SaaS |
| rag-service | RAG-as-a-Service |
| rapidapi-* | RapidAPI 서비스 |

## 자주 쓰는 명령
```bash
# 전체 상태
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
docker stats --no-stream
pm2 list

# 리소스
df -h
free -h
top -bn1 | head -20

# 특정 컨테이너 로그
docker logs <container> --tail 50 --since 1h

# 프로세스 재시작
pm2 restart <name>
docker restart <container>
```

## 주의사항
- docker restart 전에 반드시 docker logs로 상태 확인
- pm2 restart 시 --update-env 옵션 고려
- 디스크 80% 이상이면 docker system prune 고려
- 메모리 90% 이상이면 가장 많이 쓰는 컨테이너 확인
