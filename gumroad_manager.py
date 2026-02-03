"""
REZE Gumroad 매니저 — 4개 디지털 제품 관리.

역할:
- 매일: 판매 조회 → 제품별 집계
- 주 1회: 제품 설명/가격 최적화 제안
- Gumroad Ping webhook → 신규 판매 Discord 알림
- 월간: 제품별 성과 비교

API: Gumroad v2 (REST, Bearer token)
SSOT: gumroad_sales 테이블
FastAPI 라우트: /webhook/gumroad

★ 블로커: Gumroad OAuth access_token + Stripe 여권 인증 필요.
  token 미설정 시 graceful degradation.
"""

import json
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Request
import aiohttp

import config

import logging
logger = logging.getLogger("REZE.gumroad")

router = APIRouter(prefix="/webhook", tags=["webhook"])

GR_BASE = "https://api.gumroad.com/v2"


class GumroadManager:
    """Gumroad 디지털 제품 관리."""

    def __init__(self, ssot, alert_fn=None, call_llm_fn=None):
        self.ssot = ssot
        self.alert_fn = alert_fn
        self.call_llm = call_llm_fn
        self.token = config.GUMROAD_ACCESS_TOKEN

    def _enabled(self) -> bool:
        return bool(self.token)

    async def _api_get(self, endpoint: str, params: dict = None) -> Optional[dict]:
        """Gumroad GET 요청."""
        if not self._enabled():
            logger.warning("Gumroad access token not set")
            return None

        url = f"{GR_BASE}{endpoint}"
        all_params = {"access_token": self.token}
        if params:
            all_params.update(params)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, params=all_params,
                    timeout=aiohttp.ClientTimeout(total=20)
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.warning(f"Gumroad API {resp.status}: {body[:200]}")
                        return None
                    return await resp.json()
        except aiohttp.ClientError as e:
            logger.error(f"Gumroad API error: {e}")
            return None

    # === 핵심 기능 ===

    async def collect_products(self) -> list[dict]:
        """전체 제품 목록 조회."""
        result = await self._api_get("/products")
        if not result or not result.get("success"):
            return []

        products = result.get("products", [])
        logger.info(f"Gumroad: {len(products)} products")
        return products

    async def collect_sales(self, days: int = 30) -> dict:
        """
        최근 N일 판매 수집 → SSOT 저장.
        매일 스케줄러에서 호출.
        """
        after_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        page = 1
        all_sales = []

        while True:
            result = await self._api_get("/sales", {
                "after": after_date,
                "page": str(page),
            })
            if not result or not result.get("success"):
                break

            sales = result.get("sales", [])
            if not sales:
                break

            all_sales.extend(sales)
            page += 1

            if page > 10:  # 안전 제한
                break

        # SSOT 저장 (중복 무시 — sale_id UNIQUE)
        new_count = 0
        for sale in all_sales:
            sale_id = sale.get("id", "")
            if not sale_id:
                continue

            product_id = sale.get("product_id", "")
            product_name = sale.get("product_name", "Unknown")
            email = sale.get("email", "")
            price = int(float(sale.get("price", 0)) * 100)  # dollars → cents
            currency = sale.get("currency", "usd").lower()
            timestamp = sale.get("created_at", "")
            refunded = sale.get("refunded", False)

            row_id = self.ssot.save_gumroad_sale(
                sale_id, product_id, product_name, email,
                price, currency, timestamp,
                json.dumps({"refunded": refunded})
            )
            if row_id:
                new_count += 1

            # 환불 처리
            if refunded:
                db = self.ssot._get_db()
                db.execute(
                    "UPDATE gumroad_sales SET refunded=1 WHERE sale_id=?",
                    (sale_id,)
                )
                db.commit()

        # 집계
        revenue = self.ssot.get_gumroad_revenue(days)

        self.ssot.save_signal("gumroad_sales_check", json.dumps({
            "period_days": days,
            "total_sales": revenue["sales"],
            "total_usd": revenue["total_usd"],
            "new_recorded": new_count,
        }))

        logger.info(
            f"Gumroad: {revenue['sales']} sales, "
            f"${revenue['total_usd']:.2f} ({days}d), "
            f"{new_count} new"
        )

        return {
            "sales_count": revenue["sales"],
            "total_usd": revenue["total_usd"],
            "new_recorded": new_count,
        }

    async def daily_check(self) -> dict:
        """매일 실행되는 Gumroad 체크."""
        logger.info("=== Gumroad Daily Check Start ===")

        if not self._enabled():
            logger.info("Gumroad: token not set, skipping")
            return {"status": "disabled"}

        products = await self.collect_products()
        sales = await self.collect_sales(days=30)

        summary = {
            "products_count": len(products),
            "sales": sales,
            "timestamp": datetime.now(config.KST).isoformat(),
        }

        # Discord 알림
        if self.alert_fn and sales.get("total_usd", 0) > 0:
            try:
                await self.alert_fn(
                    "info", "gumroad_daily",
                    f"📦 **Gumroad**: {sales.get('sales_count', 0)} sales, "
                    f"${sales.get('total_usd', 0):.2f} (30d)"
                )
            except Exception:
                pass

        logger.info("=== Gumroad Daily Check Complete ===")
        return summary

    async def handle_ping(self, data: dict) -> dict:
        """
        Gumroad Ping (신규 판매 알림) 처리.
        Settings → Notification URL에서 설정.
        """
        sale_id = data.get("sale_id", "")
        product_name = data.get("product_name", "Unknown")
        email = data.get("email", "")
        price = data.get("price", "0")
        currency = data.get("currency", "usd")

        logger.info(f"Gumroad Ping: {product_name} — ${price} — {email}")

        # SSOT 저장
        price_cents = int(float(str(price).replace("$", "").replace(",", "")) * 100)
        self.ssot.save_gumroad_sale(
            sale_id or f"ping_{datetime.now().timestamp():.0f}",
            data.get("product_id", ""),
            product_name, email, price_cents, currency
        )

        # Discord 알림
        if self.alert_fn:
            try:
                await self.alert_fn(
                    "info", "gumroad",
                    f"💰 **Gumroad 판매!** {product_name} — ${price} — {email}"
                )
            except Exception:
                pass

        self.ssot.save_signal("gumroad_ping", json.dumps({
            "product": product_name,
            "price": price,
            "email": email[:3] + "***" if email else "",
        }))

        return {"status": "ok", "sale_id": sale_id}

    async def monthly_report(self) -> dict:
        """월간 Gumroad 성과 분석."""
        if not self.call_llm:
            return self.ssot.get_gumroad_revenue(30)

        revenue = self.ssot.get_gumroad_revenue(30)
        prev_revenue = self.ssot.get_gumroad_revenue(60)

        prompt = f"""Gumroad 월간 분석.

이번 달: {revenue['sales']}건, ${revenue['total_usd']:.2f}
지난 60일: {prev_revenue['sales']}건, ${prev_revenue['total_usd']:.2f}

4개 디지털 제품 판매 중. 목표: 월 $600~2,500
현재 블로커: Stripe 여권 인증 대기 (아직 live 아닐 수 있음)

분석:
1. 성장률?
2. 가격 최적화 제안?
3. 제품 번들 전략?

JSON:
{{"growth_rate": "X%", "pricing_suggestions": ["제안"],
  "bundle_ideas": ["아이디어"], "next_actions": ["행동"]}}
JSON만 반환."""

        try:
            result = await self.call_llm(prompt, role="reasoning")
            text = result.strip().replace("```json", "").replace("```", "").strip()
            strategy = json.loads(text)
        except Exception:
            strategy = {"raw": "분석 실패"}

        report = {**revenue, "strategy": strategy}
        self.ssot.save_signal("gumroad_monthly_report",
                              json.dumps(report, ensure_ascii=False)[:5000])
        return report


# === Singleton ===
_gumroad_instance: Optional[GumroadManager] = None


def get_gumroad() -> Optional[GumroadManager]:
    return _gumroad_instance


def init_gumroad(ssot, alert_fn=None, call_llm_fn=None):
    global _gumroad_instance
    _gumroad_instance = GumroadManager(ssot, alert_fn, call_llm_fn)
    return _gumroad_instance


# === FastAPI Webhook 엔드포인트 ===

@router.post("/gumroad")
async def gumroad_webhook(request: Request):
    """
    Gumroad Ping 수신 엔드포인트.
    POST /webhook/gumroad

    Body: form-encoded 또는 JSON
    """
    content_type = request.headers.get("content-type", "")

    if "json" in content_type:
        data = await request.json()
    else:
        form = await request.form()
        data = dict(form)

    gumroad = get_gumroad()
    if not gumroad:
        return {"error": "Gumroad manager not initialized"}

    result = await gumroad.handle_ping(data)
    return result
