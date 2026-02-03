---
name: discord
description: Discord 알림 — 웹훅, 채널별 메시지
type: comm
triggers:
  - discord
  - 디스코드
  - webhook
  - alert
  - notification
health_checks: []
fix_actions: []
---
# Discord Integration

## Webhooks
| Channel | Purpose | Webhook |
|---------|---------|---------|
| #reze-daily | 데일리/주간 리포트 | DISCORD_WEBHOOK_DAILY |
| #reze-alert | 장애 알림, LOCK 승인 요청 | DISCORD_WEBHOOK_ALERT |
| #reze-blog | 블로그 발행 알림 | DISCORD_WEBHOOK_BLOG |

## Message Format
```python
import aiohttp

async def send_discord(webhook_url: str, message: str):
    async with aiohttp.ClientSession() as session:
        await session.post(webhook_url, json={"content": message})
```

## Alert Levels
- Info: 일반 알림
- Warning: 주의 필요
- Critical: 즉시 조치 필요
- LOCK: 승인 요청

## Best Practices
1. 메시지 길이 2000자 이내
2. 중요도에 따른 채널 분리
3. 멘션은 Critical에만
4. 코드는 백틱으로 감싸기
