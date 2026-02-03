---
name: self-learning
description: REZE 자기 학습 — 성공 패턴 저장, plan_cache
type: self
triggers:
  - self-learning
  - 자기학습
  - learning
  - plan cache
health_checks: []
fix_actions: []
---
# Self-Learning

## Plan Cache
성공한 실행 계획을 저장해서 다음에 비슷한 태스크에 재사용.

```sql
-- plan_cache 테이블
CREATE TABLE plan_cache (
  id INTEGER PRIMARY KEY,
  keywords TEXT,           -- 태스크 키워드
  task_pattern TEXT,       -- 태스크 패턴
  plan_json TEXT,          -- 실행 계획 JSON
  success_count INTEGER,   -- 성공 횟수
  fail_count INTEGER,      -- 실패 횟수
  last_used TEXT
);
```

## Learning Loop
1. 태스크 수신
2. 키워드 추출
3. plan_cache에서 유사 패턴 검색
4. 있으면 재사용, 없으면 새로 생성
5. 결과에 따라 success_count/fail_count 업데이트

## Improvement Areas
- 반복 장애 → 근본 원인 분석
- 자주 쓰는 패턴 → 최적화
- 실패 패턴 → 회피 전략
