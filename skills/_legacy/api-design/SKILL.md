---
name: api-design
description: REST API 설계 — 엔드포인트, 인증, 에러 처리
type: dev
triggers:
  - api
  - rest
  - endpoint
  - 엔드포인트
health_checks: []
fix_actions: []
---
# REST API Design

## Principles
1. RESTful 리소스 기반 URL
2. HTTP 메서드 적절히 사용
3. 일관된 응답 형식
4. 버전 관리

## URL Convention
```
GET    /v1/users          # 목록
GET    /v1/users/:id      # 상세
POST   /v1/users          # 생성
PUT    /v1/users/:id      # 전체 수정
PATCH  /v1/users/:id      # 부분 수정
DELETE /v1/users/:id      # 삭제
```

## Response Format
```json
{
  "success": true,
  "data": {...},
  "error": null,
  "meta": {
    "page": 1,
    "total": 100
  }
}
```

## Error Format
```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "NOT_FOUND",
    "message": "User not found"
  }
}
```

## Authentication
- Bearer Token (JWT)
- API Key (X-API-Key header)
