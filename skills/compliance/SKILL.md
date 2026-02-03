---
name: compliance
description: GDPR, 쿠키 동의, 면책조항, 개인정보보호 준수
type: security
triggers:
  - gdpr
  - cookie
  - privacy
  - disclaimer
  - 개인정보
  - 면책조항
  - 쿠키
health_checks:
  - name: privacy_page_exists
    command: "curl -s -o /dev/null -w '%{http_code}' https://aitoolslab.runstate.dev/privacy 2>/dev/null || echo 000"
    expect: "200"
    severity: warning
fix_actions: []
---
# Compliance

블로그/SaaS 법적 요구사항 준수.

## 필수 페이지
- Privacy Policy (개인정보처리방침)
- Terms of Service (이용약관)
- Cookie Policy (쿠키 정책)
- Affiliate Disclosure (어필리에이트 공시)

## 블로그 요구사항
1. **어필리에이트 공시**: 모든 어필리에이트 링크 포함 글에 명시
   - "이 글에는 어필리에이트 링크가 포함되어 있습니다."
2. **쿠키 배너**: GDPR 준수 쿠키 동의 배너
3. **개인정보**: GA 등 추적 도구 명시

## SaaS 요구사항
1. **Terms of Service**: 서비스 이용약관
2. **Privacy Policy**: 데이터 수집/처리 명시
3. **Data Retention**: 데이터 보관 기간

## 체크리스트
- [ ] AI Tools Lab: Privacy, Terms, Cookie
- [ ] NoCode Tools Lab: Privacy, Terms, Cookie
- [ ] QuotePilot: Privacy, Terms
- [ ] PostPilot: Privacy, Terms
