---
name: email-outreach
description: 이메일 마케팅 — Listmonk, 뉴스레터
type: growth
triggers:
  - email
  - newsletter
  - 뉴스레터
  - listmonk
  - outreach
health_checks:
  - name: listmonk_health
    command: "curl -sf http://localhost:9000 -o /dev/null && echo OK || echo FAIL"
    expect: "OK"
    severity: warning
fix_actions:
  - trigger: "listmonk_health"
    command: "docker restart listmonk"
    verify: "sleep 10 && curl -sf http://localhost:9000 -o /dev/null && echo OK"
---
# Email Outreach

## Platform
- Listmonk (self-hosted)
- Port: 9000
- URL: listmonk.runstate.dev

## Lists
| List | Purpose | Subscribers |
|------|---------|-------------|
| AI Tools Lab | 블로그 업데이트 | TBD |
| Product Updates | SaaS 업데이트 | TBD |

## Email Types
1. **Newsletter**: 주간 AI 소식
2. **New Post**: 새 블로그 알림
3. **Product Update**: 기능 업데이트

## Best Practices
- 주 1회 발송
- 가치 있는 콘텐츠만
- Unsubscribe 쉽게
- A/B 테스트 제목
