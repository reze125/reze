"""
REZE v4.0 ULTIMATE Meta Cognition
- 메타인지 리뷰: "내가 뭘 잘하고 뭘 못하는지" 분석
- 약점 집중 학습 전략
- ICML 2025 메타인지 학습 패턴 적용
"""

import json
from datetime import datetime, timedelta
from typing import Callable

import logging
logger = logging.getLogger("REZE.metacog")


class MetaCognitionReview:
    """
    메타인지 리뷰.
    - 역량별 성과 분석
    - 서비스별 성과 분석
    - 강점/약점 식별
    - 학습 전략 조정
    """

    def __init__(self, call_llm_fn: Callable, ssot, discord_notify: Callable = None):
        """
        Args:
            call_llm_fn: LLM 호출 함수
            ssot: SSOT 인스턴스
            discord_notify: Discord 알림 함수
        """
        self.call_llm = call_llm_fn
        self.ssot = ssot
        self.discord_notify = discord_notify

    async def weekly_meta_review(self) -> dict:
        """매주 일요일 실행: 메타인지 리뷰."""
        logger.info("Starting weekly meta-cognition review...")

        # 1) 역량별 성과 분석
        capability_scores = await self._analyze_capability_performance()

        # 2) 서비스별 성과 분석
        service_scores = await self._analyze_service_performance()

        # 3) LLM 메타 분석
        meta_analysis = await self._llm_meta_analysis(capability_scores, service_scores)

        # 4) 약점 집중 학습 스케줄 등록
        if meta_analysis.get("weakest_capabilities"):
            await self._schedule_focused_learning(meta_analysis["weakest_capabilities"])

        # 5) SSOT에 리뷰 저장
        week_start = (datetime.now() - timedelta(days=datetime.now().weekday())).strftime("%Y-%m-%d")
        self.ssot.save_meta_review(
            week_start=week_start,
            capability_scores=capability_scores,
            service_scores=service_scores,
            strengths=meta_analysis.get("strongest_capabilities", []),
            weaknesses=meta_analysis.get("weakest_capabilities", []),
            focus_areas=meta_analysis.get("focus_areas", [])
        )

        # 6) 리포트 발송
        await self._send_meta_report(meta_analysis)

        logger.info("Meta-cognition review completed")
        return meta_analysis

    async def _analyze_capability_performance(self) -> dict:
        """역량별 성과 분석."""
        capabilities = ["collect", "analyze", "create", "execute",
                       "verify", "communicate", "optimize", "learn"]

        scores = {}
        for cap in capabilities:
            # plan_cache_v4에서 해당 역량 사용 기록 조회
            results = self.ssot.get_capability_results(cap, days=7)

            if not results:
                scores[cap] = {
                    "usage_count": 0,
                    "success_rate": 0,
                    "avg_score": 0,
                    "note": "No data"
                }
                continue

            # 성공률 계산
            success_count = sum(1 for r in results if r.get("score", 0) >= 7.0)
            success_rate = (success_count / len(results) * 100) if results else 0

            # 평균 점수
            avg_score = sum(r.get("score", 0) for r in results) / len(results) if results else 0

            scores[cap] = {
                "usage_count": len(results),
                "success_rate": success_rate,
                "avg_score": avg_score
            }

        return scores

    async def _analyze_service_performance(self) -> dict:
        """서비스별 성과 분석."""
        scores = {}

        # 등록된 서비스들
        services = self.ssot.get_known_services()

        for service in services[:20]:  # 최대 20개
            results = self.ssot.get_service_results(service, days=7)

            if not results:
                scores[service] = {
                    "task_count": 0,
                    "completed": 0,
                    "attention_level": "none"
                }
                continue

            completed = sum(1 for r in results if r.get("status") == "done")
            failed = sum(1 for r in results if r.get("status") == "failed")

            scores[service] = {
                "task_count": len(results),
                "completed": completed,
                "failed": failed,
                "attention_level": "high" if len(results) > 5 else ("medium" if len(results) > 2 else "low")
            }

        return scores

    async def _llm_meta_analysis(self, capability_scores: dict, service_scores: dict) -> dict:
        """LLM 기반 메타 분석."""
        prompt = f"""[역할] 당신은 REZE 에이전트의 메타인지 엔진입니다.

[이번 주 역량별 성과]
{json.dumps(capability_scores, indent=2, ensure_ascii=False)}

[이번 주 서비스별 성과]
{json.dumps(service_scores, indent=2, ensure_ascii=False)}

[분석 요청]
1. 가장 강한 역량 3개 + 근거
2. 가장 약한 역량 3개 + 근거 + 개선 방법
3. 방치되고 있는 서비스 (attention 부족)
4. 이번 주 놓친 기회
5. 다음 주 집중해야 할 것 top 3
6. 학습 전략 조정 제안

JSON 형식:
{{
    "strongest_capabilities": [
        {{"capability": "이름", "reason": "근거", "score": 8.5}}
    ],
    "weakest_capabilities": [
        {{"capability": "이름", "reason": "근거", "improvement": "개선방법"}}
    ],
    "neglected_services": ["서비스1"],
    "missed_opportunities": ["기회1"],
    "focus_areas": [
        {{"area": "집중영역", "reason": "이유", "actions": ["액션1"]}}
    ],
    "learning_strategy": {{
        "changes": ["변경1"],
        "priorities": ["우선순위1"]
    }},
    "overall_health": "excellent/good/needs_improvement/critical"
}}"""

        try:
            response = await self.call_llm(prompt, role="analysis")
            text = response
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            return json.loads(text.strip())
        except Exception as e:
            logger.error(f"Meta analysis failed: {e}")
            return {
                "error": str(e),
                "overall_health": "unknown"
            }

    async def _schedule_focused_learning(self, weaknesses: list):
        """약점 집중 학습 스케줄 등록."""
        for weakness in weaknesses[:3]:
            capability = weakness.get("capability", "unknown")
            improvement = weakness.get("improvement", "연습")

            # 태스크 큐에 학습 태스크 등록
            self.ssot.enqueue_task(
                task_type="learning",
                target_service=capability,
                action="focused_practice",
                parameters={
                    "capability": capability,
                    "improvement_plan": improvement,
                    "reason": weakness.get("reason", "")
                },
                priority=60,
                frequency="daily"
            )

            logger.info(f"Scheduled focused learning for: {capability}")

    async def _send_meta_report(self, analysis: dict):
        """메타인지 리포트 Discord 발송."""
        if not self.discord_notify:
            return

        health = analysis.get("overall_health", "unknown")
        health_emoji = {
            "excellent": "🟢",
            "good": "🟡",
            "needs_improvement": "🟠",
            "critical": "🔴"
        }.get(health, "⚪")

        report = f"""📊 주간 메타인지 리뷰 {health_emoji}

💪 강점:
"""
        for s in analysis.get("strongest_capabilities", [])[:3]:
            report += f"- {s.get('capability')}: {s.get('reason', 'N/A')[:50]}\n"

        report += """
⚠️ 약점:
"""
        for w in analysis.get("weakest_capabilities", [])[:3]:
            report += f"- {w.get('capability')}: {w.get('improvement', 'N/A')[:50]}\n"

        report += """
🎯 다음 주 집중 영역:
"""
        for f in analysis.get("focus_areas", [])[:3]:
            report += f"- {f.get('area')}\n"

        if analysis.get("neglected_services"):
            report += f"\n🚨 방치된 서비스: {', '.join(analysis['neglected_services'][:5])}"

        await self.discord_notify(report)

    async def quick_self_assessment(self) -> dict:
        """빠른 자기 평가 (일일)."""
        # 오늘의 성과 요약
        today_results = self.ssot.conn.execute("""
            SELECT status, COUNT(*) as cnt FROM task_queue
            WHERE created_at > datetime('now', '-1 day')
            GROUP BY status
        """).fetchall()

        summary = {r[0]: r[1] for r in today_results}

        # 오늘의 반성 체크
        reflections = self.ssot.get_recent_reflections_v4(limit=3)

        # 간단한 평가
        total = sum(summary.values())
        done = summary.get("done", 0)
        failed = summary.get("failed", 0)

        if total == 0:
            score = "N/A"
            message = "오늘 처리한 태스크 없음"
        elif done / total >= 0.8:
            score = "A"
            message = "우수한 하루!"
        elif done / total >= 0.6:
            score = "B"
            message = "괜찮은 하루"
        elif done / total >= 0.4:
            score = "C"
            message = "개선 필요"
        else:
            score = "D"
            message = "많은 태스크 실패"

        return {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "tasks_total": total,
            "tasks_done": done,
            "tasks_failed": failed,
            "score": score,
            "message": message,
            "recent_reflections": len(reflections)
        }


# === 편의 함수 ===

async def run_weekly_meta_review(call_llm_fn, ssot, discord_notify=None):
    """주간 메타인지 리뷰 실행."""
    review = MetaCognitionReview(
        call_llm_fn=call_llm_fn,
        ssot=ssot,
        discord_notify=discord_notify
    )
    return await review.weekly_meta_review()


async def quick_assessment(call_llm_fn, ssot, discord_notify=None):
    """빠른 자기 평가."""
    review = MetaCognitionReview(
        call_llm_fn=call_llm_fn,
        ssot=ssot,
        discord_notify=discord_notify
    )
    return await review.quick_self_assessment()
