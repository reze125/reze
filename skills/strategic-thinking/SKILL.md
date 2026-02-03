---
name: strategic-thinking
description: 주간 데이터 분석 -> 다음 주 전략 수립
type: strategy
triggers:
  - strategy
  - weekly-plan
  - priorities
  - 전략
  - 주간계획
  - 우선순위
health_checks: []
fix_actions: []
---
# Strategic Thinking

매주 일요일 20시 실행. 이번 주 성과/실패/발견 종합 -> 다음 주 TOP 3 우선순위.

## 입력
- 주간 signals (blog_published, auto_fix, discoveries 등)
- 주간 discoveries (new_tool, competitor_change 등)
- 비즈니스 목표 (월 $3,100~$9,500)

## 출력
```json
{
  "retrospective": {
    "biggest_win": "...",
    "biggest_issue": "..."
  },
  "opportunities": ["..."],
  "risks": ["..."],
  "next_week_priorities": [
    {"rank": 1, "goal": "...", "actions": ["..."], "expected_outcome": "..."}
  ],
  "lessons": ["..."]
}
```

## 행동
- 우선순위 행동들 -> 태스크 큐 추가
- 교훈 -> signals에 저장 (학습 루프)

## Schedule
- 매주 일 20:00 KST
