---
name: daily-report
description: 데일리 리포트 생성 — 오늘 한 일, 서비스 상태, 리소스
type: comm
triggers:
  - daily report
  - 데일리 리포트
  - 일일 리포트
  - 리포트
health_checks: []
fix_actions: []
---
# Daily Report

## Schedule
- 매일 21:00 KST 자동 생성
- Discord #reze-daily 채널로 전송

## Report Format
```
REZE 데일리 리포트 — 2026-02-03

━━━ 오늘 한 일 (FREE) ━━━
- 발행: "ChatGPT vs Claude" (점수: 87)
- 자동수리: postpilot-backend (pm2 restart)
- 자기진화: caching 적용

━━━ 서비스 ━━━
9/9 정상

━━━ 리소스 ━━━
토큰: 45,000 / 500,000
디스크: 45%
메모리: 62%

━━━ 승인 대기 (LOCK) ━━━
(없음)
```

## Data Sources
- signals 테이블: blog_published, auto_fix_success, self_evolution_success
- SSOT: 토큰 사용량
- health_check: 서비스 상태
- system: 디스크, 메모리
