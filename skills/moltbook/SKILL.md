---
name: moltbook
description: Moltbook 텔레그램 봇 — 자유 대화, 커뮤니티
type: comm
triggers:
  - moltbook
  - telegram
  - 텔레그램
  - bot
  - 봇
health_checks:
  - name: bot_process
    command: "pm2 list --no-color | grep -c moltbook || echo 0"
    verify_check: "int(output) >= 1"
    severity: warning
fix_actions:
  - trigger: "bot_process"
    command: "pm2 restart moltbook"
    verify: "pm2 list --no-color | grep -c moltbook"
---
# Moltbook Telegram Bot

## Overview
자유 대화 텔레그램 봇. 커뮤니티 참여 및 인게이지먼트.

## Location
- Script: ~/reze-agent/moltbook_bot.py
- PM2: moltbook

## Features
1. 자유 대화
2. AI 관련 질문 응답
3. 커뮤니티 알림

## Commands
```bash
# 시작
pm2 start moltbook_bot.py --name moltbook --interpreter python3

# 로그
pm2 logs moltbook --lines 50

# 재시작
pm2 restart moltbook
```

## Configuration
- Telegram Bot Token: .env
- Allowed chats: 설정된 채팅방만
