---
name: image-gen
description: 이미지 생성 — 블로그 썸네일, 다이어그램
type: content
triggers:
  - image
  - 이미지
  - thumbnail
  - 썸네일
  - diagram
health_checks:
  - name: paintingan_health
    command: "curl -sf http://localhost:8201/health -o /dev/null && echo OK || echo FAIL"
    expect: "OK"
    severity: info
fix_actions: []
---
# Image Generation

## Tools
- Paintingan (self-hosted): port 8201
- DALL-E (API)
- Midjourney (manual)

## Use Cases
1. **Blog Thumbnails**: 글 대표 이미지
2. **Comparison Tables**: 도구 비교 시각화
3. **Diagrams**: 아키텍처, 플로우

## Thumbnail Guidelines
- Size: 1200x630 (OG image)
- Format: PNG/WebP
- Style: Clean, professional
- Include tool logos (with permission)

## Storage
- Path: ~/ai-tools-lab/public/images/
- URL: /images/{slug}.png
