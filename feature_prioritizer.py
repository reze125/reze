"""
REZE 기능 우선순위 — 피드백 수집 + LLM 분류 + Impact×Effort 매트릭스.

역할:
- 피드백 수동 입력 / webhook 수신
- LLM으로 카테고리 분류 (bug / feature_request / question / praise)
- Impact vs Effort 점수 자동 산정
- 월간 "이번 달 만들어야 할 것" 리포트

★ 현재 자동 피드백 수집 시스템 없음 → 수동 입력 + FastAPI 엔드포인트
  나중에 이메일 파싱이나 인앱 피드백 위젯 추가 가능

SSOT: feature_requests 테이블
"""

import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

import config

import logging
logger = logging.getLogger("REZE.feature_prioritizer")

router = APIRouter(prefix="/feedback", tags=["feedback"])


class FeaturePrioritizer:
    """피드백 분류 + 우선순위 엔진."""

    def __init__(self, ssot, call_llm_fn=None):
        self.ssot = ssot
        self.call_llm = call_llm_fn

    async def classify_feedback(self, product_name: str, title: str,
                                description: str = "", user_email: str = "",
                                source: str = "manual") -> dict:
        """
        피드백을 받아서 LLM으로 분류 + 우선순위 산정.

        Returns: {
            "id": int, "category": str, "impact": int, "effort": int,
            "priority_score": float, "analysis": str
        }
        """
        # SSOT에 저장
        req_id = self.ssot.save_feature_request(
            product_name, title, description, source, "unclassified", user_email
        )

        # LLM 분류
        if self.call_llm:
            prompt = f"""피드백을 분류하고 우선순위를 산정하라.

제품: {product_name}
제목: {title}
설명: {description or "없음"}

분류 기준:
- category: bug | feature_request | question | praise | complaint
- impact: 1-10 (사용자에게 미치는 영향)
- effort: 1-10 (구현 난이도, 높을수록 어려움)

맥락: 솔로 개발자, 5개 SaaS 운영, 시간 극도로 제한됨.
"quick win" (impact 높고 effort 낮은 것) 우선.

JSON:
{{"category": "분류", "impact": 점수, "effort": 점수, "analysis": "한줄 분석"}}
JSON만 반환."""

            try:
                result = await self.call_llm(prompt, role="fast")
                text = result.strip().replace("```json", "").replace("```", "").strip()
                data = json.loads(text)

                category = data.get("category", "feature_request")
                impact = min(max(int(data.get("impact", 5)), 1), 10)
                effort = min(max(int(data.get("effort", 5)), 1), 10)
                # 우선순위 = impact / effort (높을수록 좋음)
                priority = round(impact / max(effort, 1), 2)
                analysis = data.get("analysis", "")[:500]

                # SSOT 업데이트
                db = self.ssot._get_db()
                db.execute(
                    """UPDATE feature_requests
                       SET category=?, impact_score=?, effort_score=?,
                           priority_score=?, llm_analysis=?, status='classified'
                       WHERE id=?""",
                    (category, impact, effort, priority, analysis, req_id)
                )
                db.commit()

                return {
                    "id": req_id,
                    "category": category,
                    "impact": impact,
                    "effort": effort,
                    "priority_score": priority,
                    "analysis": analysis,
                }

            except Exception as e:
                logger.warning(f"LLM classification failed: {e}")

        return {"id": req_id, "category": "unclassified", "impact": 5, "effort": 5,
                "priority_score": 1.0, "analysis": "LLM 분류 실패"}

    async def monthly_report(self) -> dict:
        """
        월간 피드백 리포트 + "이번 달 만들어야 할 것" 제안.
        """
        db = self.ssot._get_db()

        # 최근 30일 피드백
        requests = db.execute(
            """SELECT * FROM feature_requests
               WHERE created_at > datetime('now', '-30 days')
               ORDER BY priority_score DESC"""
        ).fetchall()
        requests = [dict(r) for r in requests]

        # 카테고리별 통계
        stats = {}
        for r in requests:
            cat = r.get("category", "unknown")
            stats[cat] = stats.get(cat, 0) + 1

        # Top 5 quick wins (높은 priority_score)
        quick_wins = [
            {"product": r["product_name"], "title": r["title"],
             "priority": r["priority_score"], "category": r["category"]}
            for r in requests[:5]
        ]

        report = {
            "total_feedback": len(requests),
            "by_category": stats,
            "quick_wins": quick_wins,
            "month": datetime.now().strftime("%Y-%m"),
        }

        # LLM 전략 분석
        if self.call_llm and requests:
            prompt = f"""피드백 월간 분석.

피드백 {len(requests)}건:
{json.dumps(quick_wins, ensure_ascii=False, indent=2)}

카테고리 분포: {json.dumps(stats)}

질문:
1. 가장 긴급한 것 3가지?
2. 이번 달 무시해도 되는 것?
3. 제품별 건강도?

JSON:
{{"urgent_items": ["항목"], "ignore_items": ["항목"],
  "product_health": {{"제품": "상태"}}}}
JSON만 반환."""
            try:
                result = await self.call_llm(prompt, role="reasoning")
                text = result.strip().replace("```json", "").replace("```", "").strip()
                report["strategy"] = json.loads(text)
            except Exception:
                report["strategy"] = {"raw": "분석 실패"}

        self.ssot.save_signal("feature_monthly_report",
                              json.dumps(report, ensure_ascii=False)[:5000])
        return report

    def get_priority_board(self, product_name: str = None) -> list[dict]:
        """
        우선순위 보드 — 분류된 피드백을 priority_score 내림차순.
        """
        db = self.ssot._get_db()
        if product_name:
            rows = db.execute(
                """SELECT * FROM feature_requests
                   WHERE product_name=? AND status != 'done'
                   ORDER BY priority_score DESC LIMIT 20""",
                (product_name,)
            ).fetchall()
        else:
            rows = db.execute(
                """SELECT * FROM feature_requests
                   WHERE status != 'done'
                   ORDER BY priority_score DESC LIMIT 20"""
            ).fetchall()
        return [dict(r) for r in rows]


# === Singleton ===
_prioritizer_instance: Optional[FeaturePrioritizer] = None


def get_prioritizer() -> Optional[FeaturePrioritizer]:
    return _prioritizer_instance


def init_prioritizer(ssot, call_llm_fn=None):
    global _prioritizer_instance
    _prioritizer_instance = FeaturePrioritizer(ssot, call_llm_fn)
    return _prioritizer_instance


# === FastAPI 엔드포인트 ===

class FeedbackRequest(BaseModel):
    product_name: str
    title: str
    description: str = ""
    user_email: str = ""
    source: str = "api"


@router.post("/submit")
async def submit_feedback(req: FeedbackRequest):
    """피드백 제출 → 자동 분류."""
    prioritizer = get_prioritizer()
    if not prioritizer:
        return {"error": "Prioritizer not initialized"}

    result = await prioritizer.classify_feedback(
        req.product_name, req.title, req.description,
        req.user_email, req.source
    )
    return result


@router.get("/board")
async def priority_board(product: str = None):
    """우선순위 보드 조회."""
    prioritizer = get_prioritizer()
    if not prioritizer:
        return {"error": "Prioritizer not initialized"}

    items = prioritizer.get_priority_board(product)
    return {"items": items, "count": len(items)}
