"""
REZE v4.0 ULTIMATE Gumroad Operations
- Gumroad 4개 제품 운영 자동화
- 판매 분석, 가격 최적화, 리뷰 피드백 루프, 신제품 검증
"""

import json
import yaml
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Callable

import logging
logger = logging.getLogger("REZE.gumroad_ops")


class GumroadOperations:
    """Gumroad 제품 운영 자동화."""

    def __init__(self, call_llm_fn: Callable, ssot, capability_engine,
                 discord_notify: Callable = None, tavily_search: Callable = None):
        """
        Args:
            call_llm_fn: LLM 호출 함수
            ssot: SSOT 인스턴스
            capability_engine: CapabilityEngine 인스턴스
            discord_notify: Discord 알림 함수
            tavily_search: Tavily 검색 함수
        """
        self.call_llm = call_llm_fn
        self.ssot = ssot
        self.capability = capability_engine
        self.discord_notify = discord_notify
        self.tavily_search = tavily_search
        self.products = self._load_gumroad_config()

    def _load_gumroad_config(self) -> dict:
        """configs/services.yaml에서 Gumroad 설정 로드."""
        config_path = Path(__file__).parent / "configs" / "services.yaml"
        if config_path.exists():
            with open(config_path) as f:
                data = yaml.safe_load(f)
                return data.get("gumroad", {})
        return {}

    async def run_daily_checks(self) -> dict:
        """모든 Gumroad 제품에 대해 일일 체크 실행."""
        logger.info("Running Gumroad daily checks...")
        results = {}

        for name, config in self.products.items():
            if config.get("status") == "planned":
                results[name] = {"status": "planned", "note": "제품 준비 중"}
                continue

            logger.info(f"Checking Gumroad product: {name}")
            results[name] = {
                "sales": await self.sales_analysis(config),
                "market": await self._market_check(config),
            }

        # 종합 리포트
        await self._daily_report(results)
        return results

    async def sales_analysis(self, product: dict) -> dict:
        """판매 데이터 분석 → 가격 조정 제안."""
        product_name = product.get("name", "unknown")

        # SSOT에서 Gumroad 판매 데이터 가져오기
        revenue = self.ssot.get_gumroad_revenue(days=30)

        # 판매 추세 분석
        sales_7d = self.ssot.conn.execute("""
            SELECT COUNT(*) as cnt, COALESCE(SUM(price_cents), 0) as total
            FROM gumroad_sales
            WHERE created_at > datetime('now', '-7 days')
            AND refunded = 0
        """).fetchone()

        sales_30d = self.ssot.conn.execute("""
            SELECT COUNT(*) as cnt, COALESCE(SUM(price_cents), 0) as total
            FROM gumroad_sales
            WHERE created_at > datetime('now', '-30 days')
            AND refunded = 0
        """).fetchone()

        trends = {
            "7d_sales": sales_7d[0] if sales_7d else 0,
            "7d_revenue": (sales_7d[1] or 0) / 100.0 if sales_7d else 0,
            "30d_sales": sales_30d[0] if sales_30d else 0,
            "30d_revenue": (sales_30d[1] or 0) / 100.0 if sales_30d else 0,
            "weekly_avg": ((sales_30d[0] or 0) / 4.3) if sales_30d else 0
        }

        # 트렌드 분석
        if trends["7d_sales"] < trends["weekly_avg"] * 0.5:
            trends["trend"] = "declining"
            trends["action"] = "price_adjust_or_promote"
        elif trends["7d_sales"] > trends["weekly_avg"] * 1.5:
            trends["trend"] = "growing"
            trends["action"] = "maintain_momentum"
        else:
            trends["trend"] = "stable"
            trends["action"] = "none"

        return trends

    async def _market_check(self, product: dict) -> dict:
        """시장 조사."""
        if not self.tavily_search:
            return {"note": "No search capability"}

        search_queries = product.get("search_queries", [])
        if not search_queries:
            category = product.get("category", "digital product")
            search_queries = [f"{category} gumroad trends 2026"]

        findings = []
        for query in search_queries[:1]:  # 제품당 1회 검색
            try:
                results = await self.tavily_search(query)
                if results:
                    findings.extend(results[:2] if isinstance(results, list) else [results])
            except Exception as e:
                logger.warning(f"Gumroad market search failed: {e}")

        return {"findings": findings}

    async def sales_page_optimize(self, product: dict) -> dict:
        """판매 페이지 최적화 제안."""
        product_name = product.get("name", "unknown")

        # 현재 판매 데이터
        sales = await self.sales_analysis(product)

        # 경쟁 제품 분석
        competitor_info = []
        if self.tavily_search:
            category = product.get("category", "digital product")
            query = f"{category} gumroad best selling page examples"
            try:
                results = await self.tavily_search(query)
                competitor_info = results[:3] if isinstance(results, list) else [results]
            except:
                pass

        # LLM으로 최적화 제안
        prompt = f"""[판매 페이지 최적화]
제품: {product_name}
카테고리: {product.get('category', 'N/A')}
현재 가격: ${product.get('price', 0)}

현재 판매 데이터:
{json.dumps(sales, indent=2)}

경쟁 제품 정보:
{json.dumps(competitor_info, indent=2, default=str)[:1000]}

최적화 제안:
1. 헤드라인 개선
2. CTA 개선
3. 가격 조정 (필요 시)
4. 추가 개선 사항

JSON 형식:
{{
    "headline_suggestions": ["제안1", "제안2"],
    "cta_suggestions": ["제안1"],
    "price_recommendation": {{"action": "keep/increase/decrease", "suggested": 29}},
    "other_improvements": ["개선1"]
}}"""

        try:
            response = await self.call_llm(prompt, role="writing")
            text = response
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            return json.loads(text.strip())
        except:
            return {"error": "Analysis failed"}

    async def review_feedback_loop(self, product: dict) -> dict:
        """구매자 피드백 → 제품 업데이트 제안."""
        product_name = product.get("name", "unknown")

        # 실제로는 Gumroad API에서 리뷰를 가져와야 함
        # 여기서는 구조만 제공

        reviews = []  # Gumroad API에서 가져온 리뷰

        if not reviews:
            return {"note": "No reviews to analyze"}

        negative = [r for r in reviews if r.get("rating", 5) <= 3]
        if not negative:
            return {"note": "No negative reviews", "status": "healthy"}

        # 부정적 리뷰 분석
        prompt = f"""[리뷰 분석]
제품: {product_name}

부정적 리뷰:
{json.dumps(negative[:5], indent=2)}

분석:
1. 주요 불만 사항
2. 개선 가능한 부분
3. 우선순위 권장

JSON 형식:
{{"top_complaints": ["불만1"], "improvements": ["개선1"], "priority": "high/medium/low"}}"""

        try:
            response = await self.call_llm(prompt, role="analysis")
            text = response
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            return json.loads(text.strip())
        except:
            return {"error": "Review analysis failed"}

    async def new_product_validation(self, idea: dict) -> dict:
        """새 제품 아이디어 검증."""
        if not self.tavily_search:
            return {"note": "No search capability for validation"}

        topic = idea.get("topic", "digital product")

        # 시장 조사
        queries = [
            f"{topic} digital product demand gumroad",
            f"{topic} pricing strategy ebook",
            f"{topic} competitors market size"
        ]

        market_data = []
        for query in queries[:2]:
            try:
                results = await self.tavily_search(query)
                if results:
                    market_data.extend(results[:2] if isinstance(results, list) else [results])
            except:
                pass

        # LLM 검증
        prompt = f"""[신제품 검증]
아이디어: {idea.get('title', topic)}
설명: {idea.get('description', 'N/A')}
예상 가격: ${idea.get('price', 29)}
타겟: {idea.get('target_audience', 'N/A')}

시장 조사 결과:
{json.dumps(market_data, indent=2, default=str)[:1500]}

검증:
1. 시장 규모/수요
2. 경쟁 상황
3. 적정 가격대
4. 성공 가능성

JSON 형식:
{{
    "market_size": "large/medium/small",
    "competition": "high/medium/low",
    "suggested_price": 29,
    "success_probability": "high/medium/low",
    "go_no_go": "go/wait/no",
    "recommendations": ["권장사항"]
}}"""

        try:
            response = await self.call_llm(prompt, role="analysis")
            text = response
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            return json.loads(text.strip())
        except:
            return {"error": "Validation failed"}

    async def _daily_report(self, results: dict):
        """일일 Gumroad 리포트."""
        if not self.discord_notify:
            return

        report_lines = ["📦 Gumroad 일일 리포트"]

        total_7d_revenue = 0
        total_30d_revenue = 0

        for name, data in results.items():
            if data.get("status") == "planned":
                report_lines.append(f"⏳ {name}: 준비 중")
                continue

            sales = data.get("sales", {})
            revenue_7d = sales.get("7d_revenue", 0)
            revenue_30d = sales.get("30d_revenue", 0)
            trend = sales.get("trend", "unknown")

            total_7d_revenue += revenue_7d
            total_30d_revenue += revenue_30d

            trend_emoji = "📈" if trend == "growing" else ("📉" if trend == "declining" else "➡️")
            report_lines.append(f"{trend_emoji} {name}: ${revenue_7d:.0f}/7d | ${revenue_30d:.0f}/30d")

        report_lines.append(f"💰 총합: ${total_7d_revenue:.0f}/7d | ${total_30d_revenue:.0f}/30d")

        await self.discord_notify("\n".join(report_lines))

    async def weekly_price_ab_test(self) -> dict:
        """주간 가격 A/B 테스트 관리."""
        # A/B 테스트 상태 확인
        running_tests = self.ssot.get_running_ab_tests()
        gumroad_tests = [t for t in running_tests if "gumroad" in t.get("skill_name", "").lower()]

        results = {"running_tests": len(gumroad_tests), "actions": []}

        for test in gumroad_tests:
            # 충분한 데이터가 모였는지 확인
            if test.get("variant_a_count", 0) >= 50 and test.get("variant_b_count", 0) >= 50:
                # 테스트 완료
                self.ssot.complete_ab_test(test["id"])
                results["actions"].append({
                    "test_id": test["id"],
                    "action": "completed",
                    "winner": test.get("winner", "undetermined")
                })

        return results


# === 편의 함수 ===

async def run_gumroad_daily(call_llm_fn, ssot, capability_engine,
                            discord_notify=None, tavily_search=None):
    """Gumroad 일일 체크 실행."""
    ops = GumroadOperations(
        call_llm_fn=call_llm_fn,
        ssot=ssot,
        capability_engine=capability_engine,
        discord_notify=discord_notify,
        tavily_search=tavily_search
    )
    return await ops.run_daily_checks()
