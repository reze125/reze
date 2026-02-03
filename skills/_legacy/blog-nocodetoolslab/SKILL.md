---
name: blog-nocodetoolslab
description: NoCode Tools Lab 블로그 — 노코드 도구 리뷰/비교
type: blog
triggers:
  - nocodetoolslab
  - nocode
  - 노코드
  - low-code
  - zapier
  - make
  - airtable
health_checks:
  - name: site_health
    command: "curl -sf http://localhost:3006 -o /dev/null && echo OK || echo FAIL"
    expect: "OK"
    severity: warning
fix_actions: []
---
# NoCode Tools Lab Blog

## Overview
노코드/로우코드 도구 리뷰 및 비교 블로그

## Structure
- Framework: Next.js
- Path: ~/nocodetoolslab/
- Port: 3006 (예정)
- URL: nocodetoolslab.runstate.dev

## Content Types
- **vs**: Zapier vs Make, Airtable vs Notion
- **review**: 개별 도구 리뷰
- **listicle**: Best 5 Automation Tools
- **tutorial**: 사용법 가이드

## Target Keywords
- zapier vs make
- best nocode tools
- airtable alternatives
- automation tools comparison
