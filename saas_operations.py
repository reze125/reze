"""
REZE v4.0 ULTIMATE SaaS Operations
- SaaS 5개의 운영 자동화
- 퍼널 분석, 이탈 감지, 결제 실패 처리, 경쟁사 모니터링
"""

import json
import asyncio
import yaml
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Callable

import logging
logger = logging.getLogger("REZE.saas_ops")


class SaaSOperations:
    """SaaS 운영 자동화."""

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
        self.services = self._load_saas_config()

    def _load_saas_config(self) -> dict:
        """configs/services.yaml에서 SaaS 설정 로드."""
        config_path = Path(__file__).parent / "configs" / "services.yaml"
        if config_path.exists():
            with open(config_path) as f:
                data = yaml.safe_load(f)
                return data.get("saas", {})
        return {}

    async def run_daily_checks(self) -> dict:
        """모든 SaaS에 대해 일일 체크 실행."""
        logger.info("Running SaaS daily checks...")
        results = {}

        for name, config in self.services.items():
            if config.get("status") == "planned":
                continue

            logger.info(f"Checking SaaS: {name}")
            results[name] = {
                "health": await self._health_check(name, config),
                "funnel": await self.funnel_analysis(config),
                "churn": await self.churn_detection(config),
            }

        # 종합 리포트
        await self._daily_report(results)
        return results

    async def _health_check(self, name: str, config: dict) -> dict:
        """헬스체크."""
        health_url = config.get("health_url")
        if not health_url:
            return {"status": "no_url"}

        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(health_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    return {
                        "status": "healthy" if resp.status == 200 else "unhealthy",
                        "code": resp.status
                    }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def funnel_analysis(self, service: dict) -> dict:
        """가입 → 활성화 → 결제 퍼널 분석."""
        funnel = service.get("funnel", {})
        if not funnel:
            return {"note": "No funnel config"}

        # 실제로는 API를 통해 데이터를 가져와야 함
        # 여기서는 SSOT에서 집계
        service_name = service.get("name", "unknown")

        # SaaS 헬스 데이터에서 추정
        health = self.ssot.get_latest_saas_health(service_name)
        if not health:
            return {"note": "No health data"}

        health = health[0] if isinstance(health, list) and health else health

        # 퍼널 지표 계산 (가용 데이터 기준)
        total_customers = health.get("total_customers", 0)
        active_subs = health.get("active_subs", 0)

        conversion = {
            "total_customers": total_customers,
            "active_subs": active_subs,
            "conversion_rate": (active_subs / total_customers * 100) if total_customers > 0 else 0
        }

        # 병목 분석
        bottleneck = None
        if conversion["conversion_rate"] < 5:
            bottleneck = "activation"
        elif conversion["conversion_rate"] < 20:
            bottleneck = "payment"

        return {
            "conversion": conversion,
            "bottleneck": bottleneck
        }

    async def churn_detection(self, service: dict) -> list:
        """이탈 감지."""
        churn_indicator = service.get("funnel", {}).get("churn_indicator")
        if not churn_indicator:
            return []

        # 실제로는 SaaS API를 통해 이탈 위험 사용자를 가져와야 함
        # 여기서는 시뮬레이션

        # SSOT에서 SaaS 헬스 데이터 추세 확인
        service_name = service.get("name", "unknown")
        health_history = self.ssot.conn.execute("""
            SELECT active_subs, measured_at FROM saas_health
            WHERE product_name = ?
            ORDER BY measured_at DESC LIMIT 7
        """, [service_name]).fetchall()

        if len(health_history) < 2:
            return []

        # 감소 추세 확인
        current = health_history[0][0] if health_history[0] else 0
        previous = health_history[-1][0] if health_history[-1] else 0

        at_risk_users = []
        if current < previous:
            churn_rate = ((previous - current) / previous * 100) if previous > 0 else 0
            at_risk_users.append({
                "type": "trend_decline",
                "churn_rate": churn_rate,
                "current_subs": current,
                "previous_subs": previous
            })

        return at_risk_users

    async def churn_detection_all(self) -> dict:
        """전체 SaaS 이탈 감지."""
        results = {}
        for name, config in self.services.items():
            if config.get("status") == "planned":
                continue
            results[name] = await self.churn_detection(config)

        # 이탈 위험 알림
        at_risk = {k: v for k, v in results.items() if v}
        if at_risk and self.discord_notify:
            msg = "⚠️ SaaS 이탈 위험 감지\n"
            for name, risks in at_risk.items():
                for risk in risks:
                    if risk.get("type") == "trend_decline":
                        msg += f"- {name}: 구독 감소 {risk['churn_rate']:.1f}%\n"
            await self.discord_notify(msg)

        return results

    async def payment_failure_handler(self, service: dict) -> dict:
        """결제 실패 자동 처리."""
        payment_source = service.get("revenue", {}).get("source")
        if not payment_source:
            return {"note": "No payment source config"}

        # 실제로는 Stripe/LemonSqueezy API를 통해 결제 실패 데이터를 가져와야 함
        # 여기서는 구조만 제공

        failed_payments = []  # API에서 가져온 실패 결제 목록

        retried = []
        escalated = []

        for payment in failed_payments:
            success = False
            for attempt in range(3):
                # 재시도 로직 (실제 구현 필요)
                # success = await self._retry_payment(payment)
                if success:
                    retried.append(payment)
                    break
                await asyncio.sleep(1)  # 실제로는 하루 대기

            if not success:
                escalated.append(payment)

        # 에스컬레이션
        if escalated and self.discord_notify:
            await self.discord_notify(
                f"💳 결제 실패 (3회 재시도 후): {len(escalated)}건\n"
                + "\n".join(f"- ${p.get('amount', 0)/100:.2f}" for p in escalated[:5])
            )

        return {
            "retried": len(retried),
            "escalated": len(escalated)
        }

    async def payment_failure_handler_all(self) -> dict:
        """전체 SaaS 결제 실패 처리."""
        results = {}
        for name, config in self.services.items():
            if config.get("status") == "planned":
                continue
            results[name] = await self.payment_failure_handler(config)
        return results

    async def competitor_price_monitor(self, service: dict) -> dict:
        """경쟁 SaaS 가격/기능 모니터링."""
        competitors = service.get("competitors", [])
        if not competitors:
            return {"note": "No competitors defined"}

        findings = []

        for competitor in competitors[:3]:  # 최대 3개
            if not self.tavily_search:
                continue

            query = f"{competitor.get('name', '')} pricing features {datetime.now().year}"
            try:
                results = await self.tavily_search(query)
                if results:
                    findings.append({
                        "competitor": competitor.get("name"),
                        "results": results[:2] if isinstance(results, list) else [results]
                    })
            except Exception as e:
                logger.warning(f"Competitor search failed: {competitor.get('name')} - {e}")

        # 변동 감지 및 알림
        if findings:
            # LLM으로 분석
            analysis = await self._analyze_competitor_changes(service, findings)
            if analysis.get("significant_changes"):
                if self.discord_notify:
                    await self.discord_notify(
                        f"🔍 경쟁사 변동: {service.get('name', 'Unknown')}\n"
                        f"{analysis.get('summary', 'N/A')}"
                    )

        return {
            "competitors_checked": len(findings),
            "findings": findings
        }

    async def _analyze_competitor_changes(self, service: dict, findings: list) -> dict:
        """경쟁사 변화 분석."""
        prompt = f"""[경쟁사 분석]
우리 서비스: {service.get('name', 'Unknown')}

경쟁사 정보:
{json.dumps(findings, indent=2, ensure_ascii=False, default=str)[:2000]}

분석:
1. 가격 변동이 있는가?
2. 새로운 기능이 추가되었는가?
3. 우리에게 시사하는 점은?

JSON 응답:
{{"significant_changes": true/false, "summary": "요약", "recommendations": ["권장사항"]}}"""

        try:
            response = await self.call_llm(prompt, role="analysis")
            text = response
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            return json.loads(text.strip())
        except:
            return {"significant_changes": False, "summary": "분석 실패"}

    async def feature_usage_analysis(self, service: dict) -> dict:
        """기능 사용 통계 → 개발 우선순위 제안."""
        # 실제로는 SaaS의 analytics API를 통해 가져와야 함
        # 여기서는 feature_requests 테이블 기반 분석

        service_name = service.get("name", "unknown")

        requests = self.ssot.conn.execute("""
            SELECT category, COUNT(*) as cnt FROM feature_requests
            WHERE product_name = ?
            GROUP BY category
            ORDER BY cnt DESC
        """, [service_name]).fetchall()

        if not requests:
            return {"note": "No feature request data"}

        return {
            "request_summary": [{"category": r[0], "count": r[1]} for r in requests],
            "top_request": requests[0][0] if requests else None
        }

    async def _daily_report(self, results: dict):
        """일일 SaaS 리포트."""
        if not self.discord_notify:
            return

        report_lines = ["📊 SaaS 일일 리포트"]

        for name, data in results.items():
            health = data.get("health", {})
            funnel = data.get("funnel", {})
            churn = data.get("churn", [])

            status_emoji = "✅" if health.get("status") == "healthy" else "❌"
            conversion = funnel.get("conversion", {})

            line = f"{status_emoji} {name}: "
            if conversion:
                line += f"전환율 {conversion.get('conversion_rate', 0):.1f}%"
            if churn:
                line += f" | 이탈위험 {len(churn)}건"

            report_lines.append(line)

        await self.discord_notify("\n".join(report_lines))


# === 편의 함수 ===

async def run_saas_daily(call_llm_fn, ssot, capability_engine,
                         discord_notify=None, tavily_search=None):
    """SaaS 일일 체크 실행."""
    ops = SaaSOperations(
        call_llm_fn=call_llm_fn,
        ssot=ssot,
        capability_engine=capability_engine,
        discord_notify=discord_notify,
        tavily_search=tavily_search
    )
    return await ops.run_daily_checks()
