---
name: documentation
description: 문서화 — 코드, API, 스킬 문서
type: meta
triggers:
  - documentation
  - 문서
  - docs
  - readme
health_checks: []
fix_actions: []
---
# Documentation

## Document Types
1. **SKILL.md**: 스킬별 지식
2. **README**: 프로젝트 개요
3. **API Docs**: 엔드포인트 문서
4. **Handover**: 인수인계 문서

## SKILL.md Structure
```yaml
---
name: skill-name
description: 설명
type: category
triggers: [키워드]
health_checks: [...]
fix_actions: [...]
---
# Title
## Overview
## Commands
## Best Practices
```

## Naming Convention
- lowercase-hyphen
- 명확하고 간결하게
- 영어/한국어 혼용 가능

## Maintenance
- 변경 시 문서 업데이트
- 분기별 전체 리뷰
