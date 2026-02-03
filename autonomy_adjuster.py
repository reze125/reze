"""
REZE 자율 등급 자동 조정.
성공률 기반으로 REVIEW -> AUTO 전환을 "제안"한다.
실제 전환은 보스 승인 필요.

2026 업계 표준: "Bounded Autonomy"
- 명확한 한계 + 에스컬레이션 경로 + 감사 추적
- 성과가 좋으면 한계를 점진적으로 확장
"""

import json
from datetime import datetime

import logging
logger = logging.getLogger("REZE.autonomy")


class AutonomyAdjuster:

    def __init__(self, get_db_fn, store_signal_fn):
        self.get_db = get_db_fn
        self.store_signal = store_signal_fn

    async def evaluate_autonomy(self) -> dict:
        """
        최근 30일 성과를 분석하여 자율 등급 조정 제안.

        기준:
        - 자기 진화 성공률 > 80% -> "low risk 진화는 AUTO로 전환 제안"
        - 블로그 발행 후 검증 effective 비율 > 70% -> "블로그 발행 AUTO 제안"
        - 실패율 > 30% -> "해당 영역 REVIEW로 복귀 제안"

        Returns: {"proposals": [...], "current_stats": {...}}
        """
        db = self.get_db()

        # 진화 성공률
        evo_total = db.execute(
            "SELECT COUNT(*) FROM evolutions WHERE created_at > datetime('now', '-30 days') AND status IN ('success', 'failed')"
        ).fetchone()[0]
        evo_success = db.execute(
            "SELECT COUNT(*) FROM evolutions WHERE created_at > datetime('now', '-30 days') AND status = 'success'"
        ).fetchone()[0]
        evo_rate = (evo_success / evo_total * 100) if evo_total > 0 else 0

        # 발견 검증 effective 비율
        verify_total = db.execute(
            """SELECT COUNT(*) FROM discoveries
               WHERE created_at > datetime('now', '-30 days')
               AND status = 'verified'"""
        ).fetchone()[0]
        verify_effective = db.execute(
            """SELECT COUNT(*) FROM discoveries
               WHERE created_at > datetime('now', '-30 days')
               AND status = 'verified'
               AND verification_result LIKE '%"effective": true%'"""
        ).fetchone()[0]
        verify_rate = (verify_effective / verify_total * 100) if verify_total > 0 else 0

        # 교훈 수
        lesson_count = db.execute(
            "SELECT COUNT(*) FROM signals WHERE kind='lesson_learned' AND created_at > datetime('now', '-30 days')"
        ).fetchone()[0]

        stats = {
            "evolution_total": evo_total,
            "evolution_success": evo_success,
            "evolution_rate": round(evo_rate, 1),
            "verification_total": verify_total,
            "verification_effective": verify_effective,
            "verification_rate": round(verify_rate, 1),
            "lessons_30d": lesson_count,
        }

        # 제안 생성
        proposals = []

        if evo_rate >= 80 and evo_total >= 10:
            proposals.append({
                "action": "자기 진화 low-risk를 REVIEW에서 AUTO로 전환",
                "reason": f"진화 성공률 {evo_rate:.0f}% ({evo_success}/{evo_total})",
                "risk": "low",
                "requires_approval": True,
            })

        if verify_rate >= 70 and verify_total >= 20:
            proposals.append({
                "action": "블로그 발행 검수를 자동 통과로 전환",
                "reason": f"검증 effective 비율 {verify_rate:.0f}%",
                "risk": "medium",
                "requires_approval": True,
            })

        if evo_rate < 50 and evo_total >= 5:
            proposals.append({
                "action": "자기 진화를 일시 중지하고 실패 원인 분석",
                "reason": f"진화 성공률 {evo_rate:.0f}% (위험)",
                "risk": "high",
                "requires_approval": False,  # 자동 적용
                "auto_action": "pause_evolution",
            })

        self.store_signal("autonomy_evaluation", json.dumps({
            "stats": stats,
            "proposals": proposals,
        }))

        logger.info(f"Autonomy eval: evo={evo_rate:.0f}%, verify={verify_rate:.0f}%, proposals={len(proposals)}")

        return {"stats": stats, "proposals": proposals}
