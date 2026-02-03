"""
REZE SaaS 모니터 — LemonSqueezy 구독/주문/고객 추적.

역할:
- 5개 SaaS 헬스체크 + 매출 추적
- MRR/ARR 자동 계산
- past_due 구독 즉시 Discord 알림
- 신규 가입 감지 → 이메일 트리거 연동
- 월간 제품별 성과 비교 리포트

API: LemonSqueezy v1 (JSON:API, 300 calls/min)
SSOT: saas_health 테이블

★ reze_biz.py의 BizTracker를 확장한다 (중복 아님).
  BizTracker = 전체 주문 합산만
  SaaSMonitor = 구독 상태별 분류 + MRR + 이탈 감지 + 알림
"""

import json
import aiohttp
from datetime import datetime
from typing import Optional

import config

import logging
logger = logging.getLogger("REZE.saas_monitor")

# LemonSqueezy API 상수
LS_BASE = "https://api.lemonsqueezy.com/v1"
LS_HEADERS_TEMPLATE = {
    "Accept": "application/vnd.api+json",
    "Content-Type": "application/vnd.api+json",
}


class SaaSMonitor:
    """LemonSqueezy 기반 SaaS 구독/매출 모니터."""

    def __init__(self, ssot, alert_fn=None, call_llm_fn=None):
        """
        ssot: SSOT 인스턴스
        alert_fn: async fn(severity, source, message) — AlertManager.send
        call_llm_fn: async fn(prompt, role) — LLM 호출 헬퍼
        """
        self.ssot = ssot
        self.alert_fn = alert_fn
        self.call_llm = call_llm_fn
        self.api_key = config.LEMONSQUEEZY_API_KEY

    def _headers(self) -> dict:
        return {**LS_HEADERS_TEMPLATE, "Authorization": f"Bearer {self.api_key}"}

    def _enabled(self) -> bool:
        return bool(self.api_key)

    # === API 호출 ===

    async def _api_get(self, endpoint: str, params: dict = None) -> Optional[dict]:
        """LemonSqueezy GET 요청. 페이지네이션 자동 처리."""
        if not self._enabled():
            logger.warning("LemonSqueezy API key not set")
            return None

        all_data = []
        url = f"{LS_BASE}{endpoint}"

        try:
            async with aiohttp.ClientSession() as session:
                while url:
                    async with session.get(
                        url, headers=self._headers(),
                        params=params if url == f"{LS_BASE}{endpoint}" else None,
                        timeout=aiohttp.ClientTimeout(total=20)
                    ) as resp:
                        if resp.status == 401:
                            logger.error("LemonSqueezy: 인증 실패 (API key 확인)")
                            return None
                        if resp.status == 429:
                            logger.warning("LemonSqueezy: Rate limited")
                            return {"data": all_data}  # 지금까지 수집한 것 반환
                        if resp.status != 200:
                            logger.warning(f"LemonSqueezy API {resp.status}: {endpoint}")
                            return None

                        body = await resp.json()
                        all_data.extend(body.get("data", []))

                        # 페이지네이션 (최대 5페이지)
                        next_url = body.get("links", {}).get("next")
                        if next_url and len(all_data) < 500:
                            url = next_url
                            params = None  # next_url에 params 포함됨
                        else:
                            url = None

            return {"data": all_data}

        except aiohttp.ClientError as e:
            logger.error(f"LemonSqueezy API error: {e}")
            return None

    # === 핵심 기능 ===

    async def collect_subscriptions(self) -> dict:
        """
        전체 구독 조회 → 상태별 분류 → MRR 계산 → SSOT 저장.
        매일 1회 스케줄러에서 호출.

        Returns: {
            "active": int, "past_due": int, "cancelled": int, "paused": int,
            "mrr_cents": int, "products": {product_name: {...}}
        }
        """
        result = await self._api_get("/subscriptions", {"page[size]": "100"})
        if not result:
            return {"error": "API unavailable", "active": 0, "mrr_cents": 0}

        subs = result.get("data", [])
        logger.info(f"Fetched {len(subs)} subscriptions")

        # 상태별 분류
        status_counts = {"active": 0, "past_due": 0, "cancelled": 0, "paused": 0,
                         "expired": 0, "unpaid": 0}
        mrr_cents = 0
        products = {}
        past_due_emails = []

        for sub in subs:
            attrs = sub.get("attributes", {})
            status = attrs.get("status", "unknown")
            product_name = attrs.get("product_name", "unknown")
            user_email = attrs.get("user_email", "")

            # 상태 카운트
            if status in status_counts:
                status_counts[status] += 1

            # MRR 계산 (active만)
            if status == "active":
                # variant_price가 월간 금액 (cents)
                price = attrs.get("variant_price", 0) or 0
                interval = attrs.get("billing_anchor", 1)
                # 연간 구독이면 /12
                if attrs.get("variant_name", "").lower().find("annual") >= 0:
                    mrr_cents += int(price / 12)
                else:
                    mrr_cents += int(price)

            # past_due 감지
            if status == "past_due" and user_email:
                past_due_emails.append({
                    "email": user_email,
                    "product": product_name,
                    "renews_at": attrs.get("renews_at", ""),
                })

            # 제품별 집계
            if product_name not in products:
                products[product_name] = {"active": 0, "past_due": 0, "cancelled": 0,
                                          "paused": 0, "mrr_cents": 0}
            if status in products[product_name]:
                products[product_name][status] += 1
            if status == "active":
                products[product_name]["mrr_cents"] += int(attrs.get("variant_price", 0) or 0)

        # SSOT 저장 (전체)
        self.ssot.save_saas_health(
            product_name="__all__",
            active=status_counts["active"],
            past_due=status_counts["past_due"],
            cancelled=status_counts["cancelled"],
            paused=status_counts["paused"],
            mrr_cents=mrr_cents,
            total_revenue_cents=0,  # 주문 API에서 별도 수집
            metadata=json.dumps({"products": products}, ensure_ascii=False)
        )

        # 제품별 SSOT 저장
        for pname, pdata in products.items():
            self.ssot.save_saas_health(
                product_name=pname,
                active=pdata["active"],
                past_due=pdata["past_due"],
                cancelled=pdata["cancelled"],
                paused=pdata["paused"],
                mrr_cents=pdata["mrr_cents"],
            )

        # past_due 알림
        if past_due_emails and self.alert_fn:
            msg = f"⚠️ 결제 실패 {len(past_due_emails)}건:\n"
            for pd in past_due_emails[:5]:
                msg += f"  - {pd['product']}: {pd['email']}\n"
            try:
                await self.alert_fn("warning", "saas_monitor", msg)
            except Exception as e:
                logger.warning(f"Alert failed: {e}")

        # 신호 저장
        self.ssot.save_signal("saas_subscription_check", json.dumps({
            "total": len(subs),
            **status_counts,
            "mrr_usd": mrr_cents / 100.0,
            "arr_usd": mrr_cents * 12 / 100.0,
            "past_due_count": len(past_due_emails),
        }))

        logger.info(
            f"SaaS: {status_counts['active']} active, "
            f"{status_counts['past_due']} past_due, "
            f"MRR ${mrr_cents/100:.2f}"
        )

        return {
            **status_counts,
            "mrr_cents": mrr_cents,
            "mrr_usd": mrr_cents / 100.0,
            "products": products,
            "past_due_details": past_due_emails,
        }

    async def collect_orders(self) -> dict:
        """최근 주문 수집 → 총 매출 계산."""
        result = await self._api_get("/orders", {"page[size]": "100"})
        if not result:
            return {"error": "API unavailable"}

        orders = result.get("data", [])
        total_cents = 0
        paid_count = 0
        refunded_count = 0

        for order in orders:
            attrs = order.get("attributes", {})
            status = attrs.get("status", "")
            total = int(attrs.get("total", 0) or 0)

            if status == "paid":
                total_cents += total
                paid_count += 1
            elif status == "refunded":
                refunded_count += 1

        self.ssot.log_biz_metric(
            "lemonsqueezy", "total_revenue",
            total_cents / 100.0, "USD",
            json.dumps({"paid": paid_count, "refunded": refunded_count})
        )

        logger.info(f"Orders: {paid_count} paid (${total_cents/100:.2f}), {refunded_count} refunded")
        return {
            "total_cents": total_cents,
            "total_usd": total_cents / 100.0,
            "paid_count": paid_count,
            "refunded_count": refunded_count,
        }

    async def collect_customers(self) -> dict:
        """고객 수 + 총 매출 집계."""
        result = await self._api_get("/customers", {"page[size]": "100"})
        if not result:
            return {"error": "API unavailable"}

        customers = result.get("data", [])
        total_customers = len(customers)
        total_revenue = sum(
            int(c.get("attributes", {}).get("total_revenue_currency", 0) or 0)
            for c in customers
        )

        logger.info(f"Customers: {total_customers}, lifetime revenue ${total_revenue/100:.2f}")
        return {
            "total_customers": total_customers,
            "lifetime_revenue_cents": total_revenue,
            "lifetime_revenue_usd": total_revenue / 100.0,
        }

    async def daily_check(self) -> dict:
        """
        매일 실행되는 종합 체크.
        스케줄러에서 이 메서드를 호출.
        """
        logger.info("=== SaaS Daily Check Start ===")

        sub_data = await self.collect_subscriptions()
        order_data = await self.collect_orders()
        customer_data = await self.collect_customers()

        summary = {
            "subscriptions": sub_data,
            "orders": order_data,
            "customers": customer_data,
            "timestamp": datetime.now(config.KST).isoformat(),
        }

        # Discord 일일 SaaS 리포트
        if self.alert_fn and not sub_data.get("error"):
            msg = (
                f"📊 **SaaS Daily**\n"
                f"구독: {sub_data.get('active', 0)} active, "
                f"{sub_data.get('past_due', 0)} past_due\n"
                f"MRR: ${sub_data.get('mrr_usd', 0):.2f}\n"
                f"고객: {customer_data.get('total_customers', 0)}명\n"
                f"총매출: ${order_data.get('total_usd', 0):.2f}"
            )
            try:
                await self.alert_fn("info", "saas_daily", msg)
            except Exception:
                pass

        logger.info("=== SaaS Daily Check Complete ===")
        return summary

    async def monthly_report(self) -> dict:
        """
        월간 SaaS 성과 분석 + LLM 전략 제안.
        cost_review_job에서 호출.
        """
        if not self.call_llm:
            return {"error": "LLM not available"}

        # 최근 헬스 데이터
        health_data = self.ssot.get_latest_saas_health()

        # 최근 30일 이탈 데이터
        db = self.ssot._get_db()
        churn_signals = db.execute(
            """SELECT COUNT(*) FROM saas_health
               WHERE cancelled_subs > 0 AND measured_at > datetime('now', '-30 days')"""
        ).fetchone()[0]

        prompt = f"""SaaS 월간 성과 분석.

현재 상태:
{json.dumps(health_data, ensure_ascii=False, indent=2)}

마스터플랜: 5개 SaaS로 월 $1,500~4,000
이탈 신호: {churn_signals}건

분석:
1. 가장 건강한 제품?
2. 즉시 조치 필요한 제품?
3. MRR 성장 전략 3가지?
4. 이탈 방지 제안?

JSON:
{{"healthiest_product": "이름", "at_risk_product": "이름",
  "growth_strategies": ["전략1", "전략2", "전략3"],
  "churn_prevention": ["방법1", "방법2"],
  "estimated_mrr_next_month": "$X"}}
JSON만 반환."""

        strategy = await self.call_llm(prompt, role="reasoning")

        text = strategy.strip().replace("```json", "").replace("```", "").strip()
        try:
            strategy_data = json.loads(text)
        except Exception:
            strategy_data = {"raw": text[:500]}

        report = {
            "health_data": health_data,
            "churn_signals": churn_signals,
            "strategy": strategy_data,
        }

        self.ssot.save_signal("saas_monthly_report", json.dumps(report, ensure_ascii=False)[:5000])
        return report
