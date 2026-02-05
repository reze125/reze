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

## AI Tools Lab (Astro)

AI Tools Lab은 Astro 기반 정적 블로그로 발행 프로세스가 다르다.

### 발행 워크플로우
1. **리서치**: Tavily로 AI 도구 관련 최신 정보 검색
2. **글 작성**: frontmatter 템플릿 + 마크다운 (configs/aitoolslab.yaml 참조)
3. **파일 저장**: `~/ai-tools-lab/src/content/blog/{slug}.md`
4. **빌드/배포**: `~/reze-agent/scripts/publish-blog.sh {slug}.md`
5. **알림**: Discord BLOG 채널에 발행 알림

### frontmatter 필수 필드
```yaml
---
title: "제목"
description: "설명"
pubDate: "YYYY-MM-DD"
category: "카테고리ID"
tags: ["tag1", "tag2"]
author: "AI Tools Lab"
readTime: "5 min read"
featured: false
---
```

### 스케줄링
- 매일 00:05: blog_daily_schedule_job이 aitoolslab.yaml의 weekly_schedule 확인
- daemon_task_processor가 5분마다 예정된 발행 실행
- 일요일 09:00: 주간 성과 리뷰 (GA4 트래픽 분석)
- 월요일 08:00: 시장 리서치 → 콘텐츠 아이디어 큐

### GA4 연동
- Property ID: 523247021
- 서비스 계정: ~/reze-agent/credentials/ga4-service-account.json
- 트래픽, 인기 페이지, 체류시간 등 조회 가능

### 스크린샷 자동 캡처

AI 도구 리뷰/비교 글 작성 시 공식 사이트 스크린샷을 자동으로 캡처한다.

#### 사용법
```python
# 도구 사용
screenshot: {"url": "https://cursor.sh", "tool_name": "Cursor"}

# 결과 예시
OK: Screenshot saved
Path: /home/reze/ai-tools-lab/public/screenshots/cursor-screenshot.png
Web: /screenshots/cursor-screenshot.png
Markdown: ![Cursor](/screenshots/cursor-screenshot.png)
```

#### 마크다운 삽입
글 본문에서 다음과 같이 사용:
```markdown
## Cursor 인터페이스

![Cursor](/screenshots/cursor-screenshot.png)

Cursor는 VS Code 기반의 AI 코딩 에디터로...
```

#### 필수 규칙
- **review** 글: 최소 1장 스크린샷 (도구 메인 화면)
- **compare** 글: 비교 대상 도구별 1장씩
- 스크린샷 위치: 개요/Overview 섹션 직후
- 파일명 형식: `{tool-slug}-screenshot.png`
- 저장 위치: `~/ai-tools-lab/public/screenshots/`
