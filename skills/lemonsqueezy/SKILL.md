---
name: lemonsqueezy
description: LemonSqueezy API — 매출 조회, 주문 관리, 구독 확인
triggers:
  - 매출
  - 수익
  - revenue
  - sales
  - 주문
  - order
  - LemonSqueezy
  - 구독
  - subscription
  - 결제
  - payment
---

# LemonSqueezy API

## API 정보
- Base URL: https://api.lemonsqueezy.com/v1
- 인증: Bearer token (CredentialStore "lemonsqueezy"에서 가져올 것)
- Content-Type: application/vnd.api+json

## 주요 엔드포인트

### 주문
- GET /v1/orders — 주문 목록
- GET /v1/orders/{id} — 주문 상세

### 구독
- GET /v1/subscriptions — 구독 목록
- GET /v1/subscriptions/{id} — 구독 상세

### 제품
- GET /v1/products — 제품 목록
- GET /v1/stores — 스토어 정보

## 필터링
```
?filter[store_id]=xxx
?filter[created_at]=2026-01-01,2026-01-31
?filter[status]=paid
?page[size]=50
```

## 매출 조회 예시
```
GET /v1/orders?filter[created_at]=2026-01-01,2026-01-31&filter[status]=paid
Authorization: Bearer <token>
```

응답에서 data[].attributes.total (센트 단위) 합산하면 월 매출.

## 주의사항
- 금액은 센트 단위 (100 = $1.00)
- 날짜 필터 형식: YYYY-MM-DD,YYYY-MM-DD
- 페이지네이션: links.next로 다음 페이지
- Rate limit 있으므로 한 번에 너무 많이 호출하지 말 것
