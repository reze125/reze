---
name: nextjs
description: Next.js 개발 — React, TypeScript, SSG/SSR
type: dev
triggers:
  - nextjs
  - next.js
  - react
  - typescript
  - frontend
health_checks: []
fix_actions: []
---
# Next.js Development

## Projects
| Project | Path | Port |
|---------|------|------|
| ai-tools-lab | ~/ai-tools-lab | 3005 |
| postpilot-frontend | ~/postpilot/frontend | 3000 |
| nocodetoolslab | ~/nocodetoolslab | 3006 |

## Common Commands
```bash
# 개발
npm run dev

# 빌드
npm run build
npm run start

# PM2로 실행
pm2 start npm --name "app" -- start
```

## Structure
```
app/
  layout.tsx
  page.tsx
  blog/
    [slug]/page.tsx
components/
public/
styles/
```

## Key Concepts
- App Router (Next.js 13+)
- Server Components
- Static Site Generation (SSG)
- Incremental Static Regeneration (ISR)
