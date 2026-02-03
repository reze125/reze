---
name: reze-core
description: REZE 코어 시스템 — 아키텍처, 설정, 확장
type: self
triggers:
  - reze
  - core
  - 코어
  - architecture
health_checks:
  - name: core_health
    command: "curl -sf http://localhost:8300/health -o /dev/null && echo OK || echo FAIL"
    expect: "OK"
    severity: critical
fix_actions:
  - trigger: "core_health"
    command: "pm2 restart reze"
    verify: "sleep 5 && curl -sf http://localhost:8300/health -o /dev/null && echo OK"
---
# REZE Core System

## Architecture
```
reze_daemon.py     # FastAPI 서버 + 스케줄러
reze_core.py       # ReAct 에이전트
reze_permissions.py # 권한 시스템 (FORBIDDEN)
reze_tools.py      # 도구 실행
reze_self_healing.py # 자가 치유
ssot.py            # SQLite 저장소
config.py          # 설정
skills/            # 스킬 지식
```

## Key Components
1. **ModelRouter**: 프로바이더 폴백 체인
2. **CircuitBreaker**: 에러 시 프로바이더 차단
3. **ToolExecutor**: 도구 실행 (shell, python, http)
4. **SkillsManager**: 스킬 로딩 및 매칭

## API Endpoints
- GET /health — 헬스체크
- POST /run — 태스크 실행
- GET /tasks — 태스크 목록
- GET /status/{id} — 태스크 상태

## Configuration
- Port: 8300
- API Key: REZE_API_KEY
- Token Budget: 500,000/day
