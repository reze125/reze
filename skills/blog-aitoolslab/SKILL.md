---
name: blog-aitoolslab
description: AI Tools Lab 블로그 발행 — articles 테이블에 글 INSERT (PostgreSQL)
triggers:
  - 블로그
  - blog
  - 발행
  - publish
  - aitoolslab
  - AI Tools Lab
  - 리뷰
  - review
  - 비교
  - comparison
  - vs
  - 포스트
  - post
  - 글
  - article
  - 뉴스
  - news
  - 리스티클
  - listicle
  - 디스커버리
  - discovery
---

# AI Tools Lab Blog

## 구조
- **프레임워크**: Next.js (TypeScript)
- **경로**: /home/reze/ai-tools-lab/
- **데이터**: PostgreSQL (Docker quotepilot-db)
- **PM2**: ai-tools-lab (port 3005)
- **URL**: https://aitoolslab.runstate.dev/blog

## DB 접속
```
host: localhost
port: 5433
database: aitoolslab
user: quotepilot
password: config.BLOG_DB 또는 CredentialStore "blog_db"
```

## articles 테이블 스키마

| 컬럼 | 타입 | 필수 | 설명 |
|------|------|------|------|
| id | SERIAL | PK | 자동 생성 |
| slug | VARCHAR(200) | ✅ | URL 경로 (unique, lowercase-hyphen) |
| title | VARCHAR(500) | ✅ | 글 제목 |
| content | TEXT | ✅ | 마크다운 본문 |
| excerpt | VARCHAR(500) | - | 요약 (자동 생성 가능) |
| category | VARCHAR(100) | - | AI Writing, AI Coding 등 |
| article_type | VARCHAR(20) | ✅ | vs, review, listicle, discovery, news |
| featured_image_url | VARCHAR(500) | - | 대표 이미지 URL |
| meta_title | VARCHAR(200) | - | SEO 제목 |
| meta_description | VARCHAR(300) | - | SEO 설명 |
| status | VARCHAR(20) | ✅ | draft / published |
| published_at | TIMESTAMP | - | 발행 시각 (published일 때 설정) |
| created_at | TIMESTAMP | - | 생성 시각 (자동) |
| updated_at | TIMESTAMP | - | 수정 시각 (자동, 트리거) |

### article_type 종류
- **vs**: 도구 비교 (예: ChatGPT vs Claude)
- **review**: 단일 도구 리뷰 (예: Cursor Review)
- **listicle**: 목록형 (예: Best 5 AI Writing Tools)
- **discovery**: 신규 도구 발견 (예: Gemini First Look)
- **news**: 뉴스/업데이트 (예: AI Coding News This Week)

## 발행 절차

### 1. 글 생성 (LLM 사용)
마크다운 형식으로 글 작성. 구조 예시:

```markdown
## At a glance
| | Tool A | Tool B | Winner |
|---|---|---|---|

## [비교 포인트 1]
본문...

## [비교 포인트 2]
본문...

## Which should you choose?
**Choose Tool A if:** ...
**Choose Tool B if:** ...
```

### 2. DB INSERT

```sql
INSERT INTO articles (
  slug, title, content, excerpt, category, article_type,
  meta_title, meta_description, status, published_at
) VALUES (
  'chatgpt-vs-claude',
  'ChatGPT vs Claude: Which AI Chatbot Wins?',
  '## At a glance
| | ChatGPT | Claude | Winner |
...(마크다운 본문)...',
  'I tested both ChatGPT and Claude with business prompts...',
  'AI Chatbots',
  'vs',
  'ChatGPT vs Claude: Which AI Chatbot Wins?',
  'Detailed comparison of ChatGPT and Claude for business use.',
  'published',
  NOW()
);
```

### 3. 빌드 & 배포 (선택)
```bash
cd ~/ai-tools-lab && npm run build && pm2 restart ai-tools-lab
```
- SSG이므로 빌드 필요. 단, ISR 설정 시 자동 갱신.

## 예시 INSERT (타입별)

### VS 비교
```sql
INSERT INTO articles (slug, title, content, category, article_type, status, published_at)
VALUES (
  'jasper-vs-copy-ai',
  'Jasper vs Copy.ai: Which AI Writer Should You Choose?',
  '## At a glance
| | Jasper | Copy.ai | Winner |
|---|---|---|---|
| Price | $49/mo | $36/mo | Copy.ai |
| Best for | Long-form | Short-form | - |

## Writing Quality
Jasper produces more nuanced content...

## Pricing
Copy.ai wins on value...',
  'AI Writing',
  'vs',
  'published',
  NOW()
);
```

### Review
```sql
INSERT INTO articles (slug, title, content, category, article_type, status, published_at)
VALUES (
  'cursor-review',
  'Cursor Review: Is This AI Code Editor Worth It?',
  '## Quick Verdict
| | |
|---|---|
| Rating | 4.5/5 |
| Price | $20/mo |
| Best for | VS Code users wanting AI |

✅ Pros: Fast completions, VS Code compatible
❌ Cons: Free tier limited

## What I Tested
...',
  'AI Coding',
  'review',
  'published',
  NOW()
);
```

### Listicle
```sql
INSERT INTO articles (slug, title, content, category, article_type, status, published_at)
VALUES (
  'best-5-ai-writing-tools-2026',
  'Best 5 AI Writing Tools in 2026',
  '## Quick Picks
| Rank | Tool | Best for | Price |
|---|---|---|---|
| 🥇 | Jasper | Long-form | $49/mo |
| 🥈 | Copy.ai | Short-form | $36/mo |

## 1. Jasper — Best Overall
...',
  'AI Writing',
  'listicle',
  'published',
  NOW()
);
```

## 조회 쿼리

```sql
-- 발행된 글 목록
SELECT id, slug, title, article_type, published_at
FROM articles WHERE status = 'published'
ORDER BY published_at DESC;

-- 특정 타입 글
SELECT * FROM articles
WHERE article_type = 'vs' AND status = 'published';

-- slug로 조회
SELECT * FROM articles WHERE slug = 'chatgpt-vs-claude';

-- 카테고리별
SELECT * FROM articles WHERE category = 'AI Writing';
```

## 주의사항

1. **slug 규칙**: lowercase, 하이픈만, 100자 이내, unique
2. **content**: 마크다운 형식 (H2 헤더, 테이블, 리스트 지원)
3. **status**: 'draft'로 저장 후 검토 → 'published'로 UPDATE 가능
4. **published_at**: published 상태일 때만 설정 (정렬 기준)
5. **빌드**: Next.js SSG이므로 새 글 추가 후 빌드 권장

## 관련 테이블

- **tools**: 도구 상세 정보 (rating, pricing, pros/cons)
- **categories**: 카테고리 목록
- **comparisons**: 비교 데이터 (legacy, 현재 미사용)
