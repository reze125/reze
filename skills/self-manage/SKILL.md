---
name: self-manage
description: "자기 관리 엔진. 자기진화, 학습, 프롬프트 최적화, 워크플로우 분석."
type: meta-skill
triggers:
  - 진화
  - 학습
  - 최적화
  - 반성
  - 목표
  - 전략
  - self
  - evolution
  - learning
  - optimize
  - reflection
  - goal
health_checks: []
fix_actions: []
---

# Self-Manage Meta-Skill

자기 개선. 학습 루프, 프롬프트 최적화, 워크플로우 개선, 목표 관리.

## 핵심 워크플로우

### 자기진화 (SelfEvolution)
1. 새 기술 발견 시 평가
2. 적용 가치 판단
3. git backup -> 코드 수정 -> health check -> 커밋/롤백

### 프롬프트 최적화
1. 최근 14일 성과 데이터 분석
2. 점수 낮은 스킬 프롬프트 개선
3. A/B 테스트

### 워크플로우 분석
1. 크론잡 성과 데이터 분석
2. 빈도/순서 최적화 제안
3. 불필요한 작업 제거 제안

### 목표 관리
1. 상위 목표 -> 중간 목표 -> 실행 태스크 분해
2. 주간 진행 리뷰
3. 차단 요소 파악 + 해결 제안

## 반성 패턴
모든 태스크 완료 후:
1. 교훈 추출
2. 성공 패턴 -> plan_cache 저장
3. 실패 패턴 -> reflections 저장
