"""
REZE v4.0 ULTIMATE Growth Engine
- 포트폴리오 성장 엔진
- 블로그 ↔ SaaS ↔ Gumroad 간 시너지
- 수익 대시보드 및 크로스셀 기회 발견
"""

import json
import yaml
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable

import logging
logger = logging.getLogger("REZE.growth")


class CrossPortfolioGrowth:
    """블로그 ↔ SaaS ↔ Gumroad 간 시너지 관리."""

    def __init__(self, call_llm_fn: Callable, ssot,
                 discord_notify: Callable = None, tavily_search: Callable = None):
        """
        Args:
            call_llm_fn: LLM 호출 함수
            ssot: SSOT 인스턴스
            discord_notify: Discord 알림 함수
            tavily_search: Tavily 검색 함수
        """
        self.call_llm = call_llm_fn
        self.ssot = ssot
        self.discord_notify = discord_notify
        self.tavily_search = tavily_search
        self.services = self._load_services()

    def _load_services(self) -> dict:
        """configs/services.yaml 로드."""
        config_path = Path(__file__).parent / "configs" / "services.yaml"
        if config_path.exists():
            with open(config_path) as f:
                return yaml.safe_load(f)
        return {}

    async def portfolio_revenue_dashboard(self) -> dict:
        """전체 포트폴리오 수익 대시보드."""
        logger.info("Generating portfolio revenue dashboard...")

        revenue = {
            "blogs": {},
            "saas": {},
            "gumroad": {},
            "total": 0,
            "timestamp": datetime.now().isoformat()
        }

        # 1) 블로그 어필리에이트 수익 (추정 또는 API)
        blogs = self.services.get("blogs", {})
        for name, config in blogs.items():
            if config.get("status") == "planned":
                continue
            # 실제로는 affiliate 대시보드 API에서 가져와야 함
            # 여기서는 추정값 사용
            revenue["blogs"][name] = await self._estimate_blog_revenue(name, config)

        # 2) SaaS MRR
        saas = self.services.get("saas", {})
        for name, config in saas.items():
            if config.get("status") == "planned":
                continue
            health = self.ssot.get_latest_saas_health(name)
            if health:
                h = health[0] if isinstance(health, list) else health
                mrr = (h.get("mrr_cents", 0) or 0) / 100.0
                revenue["saas"][name] = mrr
            else:
                revenue["saas"][name] = 0

        # 3) Gumroad 판매
        gumroad_data = self.ssot.get_gumroad_revenue(days=30)
        revenue["gumroad"]["total"] = gumroad_data.get("total_usd", 0) if gumroad_data else 0

        # 총합 계산
        revenue["total"] = (
            sum(revenue["blogs"].values()) +
            sum(revenue["saas"].values()) +
            revenue["gumroad"].get("total", 0)
        )

        # 목표 대비 진행률
        goals = self.services.get("goals", {})
        primary_goal = goals.get("primary", {})
        target = primary_goal.get("breakdown", {})
        total_target = sum(target.values()) if target else 5000

        revenue["goal_target"] = total_target
        revenue["progress"] = (revenue["total"] / total_target * 100) if total_target > 0 else 0

        # SSOT에 스냅샷 저장
        self.ssot.save_revenue_snapshot(
            blogs_revenue=sum(revenue["blogs"].values()),
            saas_revenue=sum(revenue["saas"].values()),
            gumroad_revenue=revenue["gumroad"].get("total", 0),
            goal_progress=revenue["progress"],
            breakdown=revenue
        )

        # Discord 리포트
        await self._send_revenue_report(revenue)

        logger.info(f"Revenue dashboard generated: ${revenue['total']:.0f}")
        return revenue

    async def _estimate_blog_revenue(self, name: str, config: dict) -> float:
        """블로그 수익 추정 (실제로는 API에서 가져와야 함)."""
        # biz_metrics 테이블에서 최근 기록 확인
        row = self.ssot.conn.execute("""
            SELECT value FROM biz_metrics
            WHERE metric_type = 'blog_revenue' AND metric_name = ?
            ORDER BY measured_at DESC LIMIT 1
        """, [name]).fetchone()

        if row:
            return row[0]

        # 기본값 (실제 연동 전까지)
        return 0.0

    async def _send_revenue_report(self, revenue: dict):
        """수익 리포트 Discord 발송."""
        if not self.discord_notify:
            return

        report = f"""💰 포트폴리오 수익 대시보드

📝 블로그: ${sum(revenue['blogs'].values()):.0f}
"""
        for name, amount in revenue['blogs'].items():
            if amount > 0:
                report += f"  - {name}: ${amount:.0f}\n"

        report += f"""
💻 SaaS MRR: ${sum(revenue['saas'].values()):.0f}
"""
        for name, amount in revenue['saas'].items():
            report += f"  - {name}: ${amount:.0f}\n"

        report += f"""
📦 Gumroad: ${revenue['gumroad'].get('total', 0):.0f}

═══════════════════
💵 총합: ${revenue['total']:.0f}
🎯 목표 달성률: {revenue['progress']:.1f}%
"""

        await self.discord_notify(report)

    async def blog_to_saas_funnel(self) -> dict:
        """블로그 트래픽 → SaaS 전환 파이프라인 분석."""
        opportunities = []

        blogs = self.services.get("blogs", {})
        saas = self.services.get("saas", {})

        for blog_name, blog_config in blogs.items():
            if blog_config.get("status") == "planned":
                continue

            blog_niche = blog_config.get("niche", "")

            for saas_name, saas_config in saas.items():
                if saas_config.get("status") == "planned":
                    continue

                # 관련성 체크
                relevance = await self._check_relevance(blog_niche, saas_name, saas_config)
                if relevance.get("relevant"):
                    opportunities.append({
                        "blog": blog_name,
                        "saas": saas_name,
                        "relevance": relevance.get("score", 0),
                        "suggestion": relevance.get("suggestion", "")
                    })

        # 우선순위 정렬
        opportunities.sort(key=lambda x: x.get("relevance", 0), reverse=True)

        # 상위 기회 알림
        if opportunities and self.discord_notify:
            top = opportunities[:3]
            await self.discord_notify(
                "💡 블로그→SaaS 전환 기회\n" +
                "\n".join(f"- {o['blog']} → {o['saas']}: {o['suggestion']}" for o in top)
            )

        return {"opportunities": opportunities}

    async def _check_relevance(self, blog_niche: str, saas_name: str, saas_config: dict) -> dict:
        """블로그와 SaaS 간 관련성 체크."""
        # 간단한 키워드 매칭
        relevance_map = {
            "AI tools": ["postpilot", "agenthub", "rag-service"],
            "no-code tools": ["browserpilot", "agenthub"],
            "automation": ["postpilot", "browserpilot", "agenthub"],
            "content": ["postpilot"],
            "developer": ["rag-service", "agenthub"],
        }

        for keyword, saas_list in relevance_map.items():
            if keyword.lower() in blog_niche.lower() and saas_name in saas_list:
                return {
                    "relevant": True,
                    "score": 80,
                    "suggestion": f"{blog_niche} 글에 {saas_name} CTA 삽입"
                }

        return {"relevant": False, "score": 0}

    async def cross_sell_opportunities(self) -> dict:
        """크로스셀링 기회 발견."""
        opportunities = []

        # 1) SaaS 사용자 → 다른 SaaS/Gumroad 추천
        saas = self.services.get("saas", {})
        for saas_name, config in saas.items():
            if config.get("status") == "planned":
                continue

            health = self.ssot.get_latest_saas_health(saas_name)
            if health:
                h = health[0] if isinstance(health, list) else health
                customers = h.get("total_customers", 0)
                if customers > 0:
                    opportunities.append({
                        "type": "saas_to_saas",
                        "source": saas_name,
                        "customers": customers,
                        "suggestions": self._get_cross_sell_suggestions(saas_name)
                    })

        # 2) Gumroad 구매자 → SaaS 할인 오퍼
        gumroad_sales = self.ssot.get_gumroad_revenue(days=30)
        if gumroad_sales and gumroad_sales.get("sales", 0) > 0:
            opportunities.append({
                "type": "gumroad_to_saas",
                "source": "gumroad_buyers",
                "customers": gumroad_sales.get("sales", 0),
                "suggestions": ["SaaS 30% 할인 쿠폰 제공", "번들 오퍼 제안"]
            })

        return {"opportunities": opportunities}

    def _get_cross_sell_suggestions(self, saas_name: str) -> list:
        """SaaS별 크로스셀 제안."""
        suggestions = {
            "postpilot": ["browserpilot 자동화 연동", "AI 자동화 가이드 (Gumroad)"],
            "quotepilot": ["비즈니스 자동화 가이드 (Gumroad)"],
            "browserpilot": ["postpilot 콘텐츠 파이프라인"],
            "agenthub": ["rag-service 지식베이스 연동"],
            "rag-service": ["agenthub 에이전트 빌더"],
        }
        return suggestions.get(saas_name, [])

    async def revenue_forecast(self, months: int = 3) -> dict:
        """수익 예측."""
        # 최근 수익 히스토리
        history = self.ssot.get_revenue_history(days=90)

        if len(history) < 7:
            return {"note": "Not enough data for forecast"}

        # 간단한 추세 분석
        recent_total = sum(r.get("total_revenue", 0) for r in history[:7]) / 7
        older_total = sum(r.get("total_revenue", 0) for r in history[-7:]) / 7 if len(history) >= 14 else recent_total

        growth_rate = ((recent_total - older_total) / older_total * 100) if older_total > 0 else 0

        # 예측
        forecast = []
        current = recent_total
        for month in range(1, months + 1):
            projected = current * (1 + growth_rate / 100)
            forecast.append({
                "month": month,
                "projected": projected
            })
            current = projected

        return {
            "current_daily_avg": recent_total,
            "growth_rate": growth_rate,
            "forecast": forecast
        }

    async def identify_growth_levers(self) -> dict:
        """성장 레버 식별."""
        prompt = """[성장 레버 분석]

현재 포트폴리오:
- 블로그 10개 (어필리에이트)
- SaaS 5개 (PostPilot, QuotePilot, BrowserPilot, AgentHub, RAG-as-a-Service)
- Gumroad 4개 (디지털 제품)

목표: 월수익 $5K

분석:
1. 가장 높은 ROI 레버 3개
2. 빠른 성과 (Quick Wins) 3개
3. 중장기 투자 2개
4. 리스크/의존도 분석

JSON 형식:
{{
    "high_roi_levers": [
        {{"lever": "레버1", "expected_impact": "$X/month", "effort": "low/medium/high"}}
    ],
    "quick_wins": ["빠른성과1"],
    "long_term": ["중장기1"],
    "risks": ["리스크1"]
}}"""

        try:
            response = await self.call_llm(prompt, role="analysis")
            text = response
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            return json.loads(text.strip())
        except:
            return {"error": "Analysis failed"}


# === 편의 함수 ===

async def generate_revenue_dashboard(call_llm_fn, ssot, discord_notify=None, tavily_search=None):
    """수익 대시보드 생성."""
    engine = CrossPortfolioGrowth(
        call_llm_fn=call_llm_fn,
        ssot=ssot,
        discord_notify=discord_notify,
        tavily_search=tavily_search
    )
    return await engine.portfolio_revenue_dashboard()


async def find_growth_opportunities(call_llm_fn, ssot, discord_notify=None, tavily_search=None):
    """성장 기회 발견."""
    engine = CrossPortfolioGrowth(
        call_llm_fn=call_llm_fn,
        ssot=ssot,
        discord_notify=discord_notify,
        tavily_search=tavily_search
    )

    results = {
        "blog_to_saas": await engine.blog_to_saas_funnel(),
        "cross_sell": await engine.cross_sell_opportunities(),
        "growth_levers": await engine.identify_growth_levers()
    }

    return results
