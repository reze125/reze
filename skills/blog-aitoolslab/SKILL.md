---
name: blog-aitoolslab
description: AI Tools Lab 블로그 관리 — 도구 등록, 비교 글 발행 (PostgreSQL)
triggers:
  - 블로그
  - blog
  - 발행
  - publish
  - aitoolslab
  - AI Tools Lab
  - 도구 리뷰
  - tool review
  - 비교
  - comparison
  - vs
  - 포스트
  - post
  - 글
  - article
---

# AI Tools Lab Blog

## 구조
- 프레임워크: Next.js (TypeScript)
- 경로: /home/reze/ai-tools-lab/
- 데이터: PostgreSQL (Docker quotepilot-db)
- PM2: ai-tools-lab

## DB 접속
```
host: localhost
port: 5433
database: aitoolslab
user: quotepilot
```
CredentialStore에서 "blog_db" 키로 비밀번호 참조하거나 config.BLOG_DB 사용.

## 테이블 스키마

### tools
| 컬럼 | 설명 |
|------|------|
| id | SERIAL PRIMARY KEY |
| slug | 고유 URL 경로 (예: chatgpt) |
| name | 도구명 |
| tagline | 한줄 소개 |
| description | 상세 설명 |
| pricing_model | free/freemium/paid/enterprise |
| pricing_detail | 가격 상세 |
| rating_overall | 전체 평점 |
| rating_ease | 사용 편의성 |
| rating_features | 기능 |
| rating_value | 가성비 |
| pros | TEXT[] (장점 배열) |
| cons | TEXT[] (단점 배열) |
| features_list | JSONB (기능 목록) |
| affiliate_url | 제휴 링크 |
| affiliate_tag | 제휴 태그 |

### comparisons
| 컬럼 | 설명 |
|------|------|
| id | SERIAL PRIMARY KEY |
| slug | 고유 URL (예: chatgpt-vs-claude) |
| tool1_id | FK → tools.id |
| tool2_id | FK → tools.id |
| title | 비교 글 제목 |
| verdict | 최종 판정 |
| comparison_points | JSONB (항목별 비교) |
| winner_overall | tool1/tool2/tie |

### categories
| 컬럼 | 설명 |
|------|------|
| id | SERIAL PRIMARY KEY |
| slug | 카테고리 URL |
| name | 카테고리명 |
| description | 설명 |
| parent_id | 상위 카테고리 |
| tool_count | 도구 수 |

## 발행 절차
1. **도구 등록**: tools 테이블에 INSERT (slug 중복 체크 필수)
2. **비교 글**: comparisons 테이블에 INSERT (tool1_id, tool2_id 유효성 확인)
3. **카테고리**: 필요 시 categories에 INSERT

## 예시 INSERT

```sql
-- 도구 등록
INSERT INTO tools (slug, name, tagline, description, pricing_model, rating_overall, pros, cons)
VALUES (
  'cursor-ai',
  'Cursor AI',
  'AI-First Code Editor',
  'VS Code 포크 기반 AI 코딩 에디터...',
  'freemium',
  4.5,
  ARRAY['빠른 AI 자동완성', 'VS Code 호환'],
  ARRAY['무료 플랜 제한적', '큰 프로젝트에서 느림']
);

-- 비교 글
INSERT INTO comparisons (slug, tool1_id, tool2_id, title, verdict, winner_overall, comparison_points)
VALUES (
  'cursor-vs-copilot',
  (SELECT id FROM tools WHERE slug='cursor-ai'),
  (SELECT id FROM tools WHERE slug='github-copilot'),
  'Cursor vs GitHub Copilot: Which AI Code Editor Wins?',
  'Cursor offers deeper AI integration while Copilot has broader ecosystem support.',
  'tool1',
  '{"pricing": "Copilot is cheaper", "features": "Cursor has more AI features"}'::jsonb
);
```

## 주의사항
- slug는 반드시 lowercase + 하이픈만 사용
- INSERT 전 SELECT로 slug 중복 확인
- comparison_points는 유효한 JSONB
- tool_count는 수동 업데이트 필요할 수 있음
