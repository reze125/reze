---
name: infra-ops
description: "인프라 운영 엔진. Docker, Nginx, PM2, SSL, 서버 모니터링, 백업."
type: meta-skill
triggers:
  - docker
  - nginx
  - pm2
  - ssl
  - 서버
  - 디스크
  - 백업
  - 인프라
  - container
  - 컨테이너
  - memory
  - 메모리
  - cpu
  - disk
  - firewall
  - systemd
  - cron
health_checks:
  - name: docker_status
    command: "docker ps --format '{{.Names}}' | wc -l"
    verify_check: "int(output) >= 5"
  - name: disk_usage
    command: "df / --output=pcent | tail -1 | tr -d ' %'"
    verify_check: "int(output) < 85"
  - name: memory_usage
    command: "free | grep Mem | awk '{printf \"%.0f\", $3/$2*100}'"
    verify_check: "int(output) < 90"
fix_actions:
  - trigger: disk_usage
    command: "docker system prune -f && journalctl --vacuum-time=7d"
---

# Infra-Ops Meta-Skill

인프라 운영 자동화. 서버 상태 모니터링, 컨테이너 관리, 백업, SSL 갱신.

## 핵심 워크플로우

### 컨테이너 관리
1. `docker ps` 상태 주기적 확인
2. unhealthy 컨테이너 자동 재시작
3. 사용하지 않는 이미지/볼륨 정리

### 서버 모니터링
1. 디스크 사용량 85% 초과 시 알림 + 정리
2. 메모리 사용량 90% 초과 시 알림
3. CPU 부하 모니터링

### SSL 갱신
1. certbot으로 만료 7일 전 자동 갱신
2. nginx reload

### 백업
1. PostgreSQL daily dump
2. 중요 config 파일 백업
3. 7일 이상 백업 삭제

## 안전 규칙
- rm -rf 금지 (FORBIDDEN)
- 서버 재부팅은 보스 승인 필요
- 방화벽 변경은 LOCK 행동
