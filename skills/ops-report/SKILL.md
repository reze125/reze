---
name: ops-report
description: "운영 리포트 엔진. 일일/주간 보고서 생성, Discord 전송."
type: meta-skill
triggers:
  - 리포트
  - 보고서
  - 일일
  - 주간
  - 요약
  - 현황
  - report
  - daily
  - weekly
  - summary
health_checks: []
fix_actions: []
---

# Ops-Report Meta-Skill

운영 보고서 자동 생성 및 전송.

## 핵심 워크플로우

### 일일 리포트
1. 오늘 완료한 태스크 수집
2. 오늘 발행한 블로그 글
3. 오늘 발생한 에러/장애
4. 자동 수리 현황
5. 토큰 사용량
6. 보스 승인 대기 항목

### 주간 리포트
1. 주간 태스크 통계 (성공률)
2. 주간 블로그 발행 현황
3. 주간 매출/MRR 변화
4. 주간 트래픽 변화
5. 다음 주 계획

### 품질 기준
- QUALITY_GATES['discord_report'] 통과
- 최대 500단어
- 반드시 숫자 데이터 포함
- 요약 섹션 필수

### 전송
- Discord 웹훅으로 전송
- 채널별 분리 (daily, alert, blog)
