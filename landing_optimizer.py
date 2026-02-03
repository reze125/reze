"""
REZE 랜딩페이지 최적화 — 전환율 추적 + LLM 카피 개선 제안.

역할:
- 주 1회: 전환율 수집 (현재: 수동 입력, 향후: analytics 연동)
- LLM으로 헤드라인/CTA 변형 생성
- 경쟁사 랜딩페이지 모니터링 (Tavily 검색)
- 전환율 하락 시 알림

★ 현실: Google Analytics / Plausible 연동 미구현.
  → 수동 입력 모드로 시작.
  → analytics 연동 후 자동 수집으로 전환.

SSOT: landing_metrics 테이블
"""

import json
from datetime import datetime
from typing import Optional

import config

import logging
logger = logging.getLogger("REZE.landing")


class LandingOptimizer:
    """랜딩페이지 전환율 최적화 엔진."""

    def __init__(self, ssot, call_llm_fn=None, alert_fn=None):
        self.ssot = ssot
        self.call_llm = call_llm_fn
        self.alert_fn = alert_fn

    async def record_metrics(self, product_name: str, visitors: int = 0,
                             signups: int = 0, page_url: str = "",
                             bounce_rate: float = 0.0,
                             avg_time: float = 0.0) -> dict:
        """
        랜딩페이지 메트릭 수동 입력.
        나중에 analytics API 연동 시 이 메서드를 자동 호출.

        Returns: {"id": int, "conversion_rate": float, "alert": bool}
        """
        conversion_rate = (signups / visitors * 100) if visitors > 0 else 0.0

        db = self.ssot._get_db()
        cur = db.execute(
            """INSERT INTO landing_metrics(product_name, page_url, visitors, signups,
               conversion_rate, bounce_rate, avg_time_on_page, measured_at)
               VALUES(?,?,?,?,?,?,?,?)""",
            (product_name, page_url, visitors, signups, conversion_rate,
             bounce_rate, avg_time, datetime.now(config.KST).isoformat())
        )
        db.commit()

        # 전환율 하락 감지
        alert = False
        prev = db.execute(
            """SELECT conversion_rate FROM landing_metrics
               WHERE product_name=? ORDER BY measured_at DESC LIMIT 1 OFFSET 1""",
            (product_name,)
        ).fetchone()

        if prev and prev[0] > 0 and conversion_rate < prev[0] * 0.7:
            alert = True
            logger.warning(
                f"Landing conversion drop: {product_name} "
                f"{prev[0]:.1f}% → {conversion_rate:.1f}%"
            )
            if self.alert_fn:
                try:
                    import asyncio
                    await self.alert_fn(
                        "warning", "landing_optimizer",
                        f"📉 전환율 하락: {product_name} "
                        f"{prev[0]:.1f}% → {conversion_rate:.1f}%"
                    )
                except Exception:
                    pass

        return {"id": cur.lastrowid, "conversion_rate": conversion_rate, "alert": alert}

    async def generate_variants(self, product_name: str) -> dict:
        """
        현재 랜딩페이지의 헤드라인/CTA 변형을 LLM으로 생성.
        주 1회 스케줄러에서 호출.
        """
        if not self.call_llm:
            return {"error": "LLM not available"}

        # 최근 메트릭
        db = self.ssot._get_db()
        metrics = db.execute(
            """SELECT * FROM landing_metrics
               WHERE product_name=? ORDER BY measured_at DESC LIMIT 5""",
            (product_name,)
        ).fetchall()
        metrics = [dict(m) for m in metrics]

        # 제품 정보
        product_info = config.SAAS_PRODUCTS.get(product_name.lower(), {})

        prompt = f"""랜딩페이지 최적화 전문가.

제품: {product_name} ({product_info.get('name', product_name)})
최근 전환율 데이터:
{json.dumps(metrics, ensure_ascii=False, indent=2) if metrics else "데이터 없음"}

목표: 전환율 3% 이상
대상: 영어권 SaaS 사용자
보스: 솔로 개발자

3가지 헤드라인 + CTA 변형 생성.
각 변형에 예상 효과 포함.

JSON:
{{"variants": [
  {{"headline": "헤드라인", "subheadline": "서브", "cta_text": "CTA 버튼 텍스트", "expected_impact": "예상 효과"}}
]}}
JSON만 반환."""

        try:
            result = await self.call_llm(prompt, role="reasoning")
            text = result.strip().replace("```json", "").replace("```", "").strip()
            data = json.loads(text)

            self.ssot.save_signal("landing_variants", json.dumps({
                "product": product_name,
                "variants": data.get("variants", []),
            }, ensure_ascii=False))

            return data

        except Exception as e:
            logger.warning(f"Variant generation failed: {e}")
            return {"error": str(e)}

    async def weekly_review(self) -> dict:
        """
        주간 랜딩페이지 리뷰.
        모든 제품의 전환율 트렌드 분석.
        """
        db = self.ssot._get_db()

        products_data = {}
        for product_key in config.SAAS_PRODUCTS:
            metrics = db.execute(
                """SELECT * FROM landing_metrics
                   WHERE product_name=? ORDER BY measured_at DESC LIMIT 4""",
                (product_key,)
            ).fetchall()
            if metrics:
                products_data[product_key] = [dict(m) for m in metrics]

        if not products_data:
            return {"message": "No landing metrics data yet"}

        review = {
            "week": datetime.now().strftime("%Y-W%U"),
            "products": {},
        }

        for product, metrics in products_data.items():
            latest = metrics[0] if metrics else {}
            review["products"][product] = {
                "latest_conversion": latest.get("conversion_rate", 0),
                "latest_visitors": latest.get("visitors", 0),
                "data_points": len(metrics),
            }

        self.ssot.save_signal("landing_weekly_review",
                              json.dumps(review, ensure_ascii=False))
        return review
