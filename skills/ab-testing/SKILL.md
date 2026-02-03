---
name: ab-testing
description: A/B 테스트 — 실험, 최적화
type: ops
triggers:
  - ab test
  - a/b
  - experiment
  - 실험
health_checks: []
fix_actions: []
---
# A/B Testing

## Use Cases
1. **Blog**: 제목, 메타 설명
2. **Email**: 제목, CTA
3. **SaaS**: UI, 가격

## Framework
1. **Hypothesis**: 무엇을 테스트할지
2. **Variants**: A (control), B (treatment)
3. **Metrics**: 측정 지표
4. **Duration**: 테스트 기간
5. **Analysis**: 결과 분석

## Example
```
Hypothesis: 제목에 숫자가 있으면 CTR 증가
A: "Best AI Writing Tools"
B: "7 Best AI Writing Tools"
Metric: Click-through rate
Duration: 1 week
```

## Statistical Significance
최소 95% 신뢰도 확보 후 결정.
