"""
REZE 수익 추적.
블로그 트래픽, 어필리에이트 클릭, 수익을 추적하고 전략을 자동 조정.

주요 지표:
- 블로그별 발행 수
- 발견/기회 수
- 진화 성공률
"""

import json
from datetime import datetime

import logging
logger = logging.getLogger("REZE.revenue")


class RevenueTracker:

    def __init__(self, get_db_fn, store_signal_fn, call_llm_fn):
        self.get_db = get_db_fn
        self.store_signal = store_signal_fn
        self.call_llm = call_llm_fn

    async def monthly_report(self) -> dict:
        """
        월간 수익 리포트 생성.
        """
        db = self.get_db()

        # 이번 달 블로그 발행
        blogs = db.execute(
            "SELECT COUNT(*) FROM signals WHERE kind='blog_published' AND created_at > datetime('now', '-30 days')"
        ).fetchone()[0]

        # 이번 달 진화
        evolutions = db.execute(
            "SELECT COUNT(*) FROM evolutions WHERE created_at > datetime('now', '-30 days')"
        ).fetchone()[0]

        # 이번 달 교훈
        lessons = db.execute(
            "SELECT COUNT(*) FROM signals WHERE kind='lesson_learned' AND created_at > datetime('now', '-30 days')"
        ).fetchone()[0]

        # 이번 달 발견
        discoveries = db.execute(
            "SELECT COUNT(*) FROM discoveries WHERE created_at > datetime('now', '-30 days')"
        ).fetchone()[0]

        # 소스별 발견 분포
        source_dist = db.execute(
            """SELECT source_skill, COUNT(*) as cnt FROM discoveries
               WHERE created_at > datetime('now', '-30 days')
               GROUP BY source_skill ORDER BY cnt DESC"""
        ).fetchall()

        report = {
            "month": datetime.now().strftime("%Y-%m"),
            "blogs_published": blogs,
            "evolutions": evolutions,
            "lessons": lessons,
            "discoveries": discoveries,
            "source_distribution": {row[0]: row[1] for row in source_dist if row[0]},
        }

        # LLM에게 전략 조정 요청
        strategy = await self.call_llm(
            f"""REZE 월간 실적 분석.

{json.dumps(report, ensure_ascii=False, indent=2)}

마스터플랜: 10개 블로그 + Gumroad 4개 제품 = 월 $3,100~9,500
현재: 블로그 2개 (AI Tools Lab, NoCode Tools Lab)

질문:
1. 가장 ROI 높은 활동은?
2. 가장 비효율적인 활동은?
3. 다음 달 우선순위 3가지?
4. 새 블로그를 추가할 타이밍인가?

JSON:
{{
    "high_roi_activities": ["활동"],
    "low_roi_activities": ["활동"],
    "next_month_priorities": ["우선순위 1", "우선순위 2", "우선순위 3"],
    "should_add_blog": true/false,
    "suggested_niche": "추천 니치 (해당 시)",
    "estimated_monthly_revenue": "$X"
}}
JSON만 반환.
""",
            role="reasoning"
        )

        # JSON 파싱
        text = strategy.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]

        try:
            strategy_data = json.loads(text.strip())
        except:
            strategy_data = {"raw": strategy[:500]}

        report["strategy"] = strategy_data

        self.store_signal("monthly_revenue_report", json.dumps(report, ensure_ascii=False))

        return report
