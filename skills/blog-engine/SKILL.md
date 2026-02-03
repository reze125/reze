---
name: blog-engine
description: "블로그 자동 운영 통합 엔진. 글 작성, SEO, 발행, 경쟁사 분석, 어필리에이트까지."
type: meta-skill
triggers:
  - 블로그
  - 글 작성
  - 기사
  - article
  - blog
  - seo
  - 키워드
  - 발행
  - wordpress
  - aitoolslab
  - nocodetoolslab
  - emailstack
  - elearningstack
  - financehub
  - vpnranker
  - hostingdeals
  - passwordmanager
  - websitebuilder
  - projectmanagement
health_checks:
  - name: blog_api
    command: "curl -s -o /dev/null -w '%{http_code}' https://aitoolslab.com/api/health 2>/dev/null || echo 'N/A'"
    expect: "200"
fix_actions:
  - trigger: blog_api
    command: "pm2 restart ai-tools-lab"
---

# Blog Engine Meta-Skill

너는 블로그 자동 운영 시스템이다. config YAML에서 대상 블로그 정보를 받아 작업한다.

## 핵심 워크플로우

### 글 작성
1. **키워드 리서치**: Tavily로 config.seo.primary_keywords 관련 검색
2. **경쟁사 분석**: config.seo.competitor_sites의 최신 글 분석
3. **초안 작성**: config.content.tone에 맞춰 {config.content.min_words}~{config.content.max_words} 단어
4. **SEO 최적화**: title tag, meta description, H2 구조, internal links
5. **어필리에이트 삽입**: config.affiliate.link_density 개수만큼 자연스럽게
6. **품질 검증**: QUALITY_GATES['blog_article'] 통과 필수
7. **WordPress 발행**: REST API로 발행, 슬러그/카테고리/태그 자동 설정

### 모니터링
- config.monitoring.health_check_url 주기적 확인
- 발행 실패 시 자동 재시도 (최대 2회)
- 일일 보고서에 발행 현황 포함

## 품질 기준
- 최소 {config.quality.min_score}점 (cross_review)
- 비교 표준: {config.quality.comparison_standard} 수준
- TechRadar/Zapier 수준이 아니면 재작성

## config 참조
이 스킬은 configs/ 디렉토리의 YAML 파일에서 대상별 설정을 읽는다.
새 블로그 추가 = configs/_template.yaml 복사 + 값 수정. 코드 변경 0.
