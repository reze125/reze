---
name: llm-optimization
description: LLM 최적화 — 비용 절감, 속도 개선
type: ops
triggers:
  - llm optimization
  - token
  - 토큰
  - prompt
  - 프롬프트
health_checks: []
fix_actions: []
---
# LLM Optimization

## Strategies
1. **Model Selection**: 태스크에 맞는 모델
2. **Caching**: plan_cache로 반복 호출 방지
3. **Prompt Optimization**: 간결한 프롬프트
4. **Batching**: 여러 요청 묶기

## REZE Provider Chain
```
Cerebras (빠름, 무료) → Groq (빠름) → Gemini → OpenRouter
```

## Token Budget
- Daily limit: 500,000 tokens
- Warning: 80% 도달 시
- Action: 모델 다운그레이드

## Prompt Best Practices
1. 명확한 지시
2. 예시 포함
3. 출력 형식 지정
4. 불필요한 설명 제거

## Monitoring
```sql
-- 일일 토큰 사용량
SELECT date, total_tokens FROM daily_budget ORDER BY date DESC LIMIT 7;
```
