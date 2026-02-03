---
name: saas-engine
description: "SaaS 제품 운영 엔진. 모니터링, 리포트, 장애 대응, 사용자 분석."
type: meta-skill
triggers:
  - saas
  - postpilot
  - quotepilot
  - browserpilot
  - agenthub
  - rag
  - 모니터링
  - 사용자
  - 구독
  - mrr
  - churn
  - stripe
  - lemon
health_checks:
  - name: saas_api
    command: "curl -s -o /dev/null -w '%{http_code}' http://localhost:8030/health 2>/dev/null || echo 'N/A'"
    expect: "200"
fix_actions:
  - trigger: saas_api
    command: "pm2 restart quotepilot-api"
---

# SaaS Engine Meta-Skill

SaaS 제품 운영 자동화. config YAML에서 대상 제품 정보를 읽는다.

## 핵심 워크플로우

### 모니터링
1. health_check_url 주기적 확인
2. DB 연결 상태 점검
3. 결제 시스템 (Stripe/Lemon Squeezy) 상태 확인
4. 이상 감지 시 Discord 즉시 알림 + 자동 재시작 시도

### 리포트 생성
1. DB에서 주요 메트릭 수집 (MRR, 신규 사용자, churn, conversion)
2. 전월/전주 대비 비교
3. QUALITY_GATES['saas_report'] 통과 필수
4. 반드시 action_items (다음 행동 제안) 포함

### 장애 대응
1. 서비스 다운 감지 -> 자동 재시작 (pm2 restart / docker restart)
2. DB 연결 실패 -> PostgreSQL 재시작 시도
3. 2회 실패 시 보스에게 에스컬레이션

## config 참조
configs/_template.yaml 복사해서 새 SaaS 추가.
