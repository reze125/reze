"""
Metacognitive Monitoring — REZE v6.0 SOVEREIGN
자기 판단 정확도 추적, 편향 감지, 신뢰도 보정

REZE의 판단이 얼마나 정확한지 추적하고,
과신/과소평가 편향을 감지하여 보정합니다.

가동 조건: decision_log >= 20건
"""

import json
import logging
from datetime import datetime
from collections import defaultdict
from typing import Optional, Dict, List, Any

logger = logging.getLogger("reze.evolve.metacognition")


class MetacognitiveMonitor:
    """
    메타인지 모니터링.
    판단 기록 → 결과 평가 → 보정 계수 계산.
    """

    def __init__(self, ssot):
        """
        Args:
            ssot: SSOT 인스턴스
        """
        self.ssot = ssot
        self.conn = ssot.conn if hasattr(ssot, 'conn') else ssot

    async def is_active(self) -> bool:
        """활성화 조건 확인: decision_log >= 20"""
        try:
            row = self.conn.execute(
                "SELECT COUNT(*) as cnt FROM decision_log"
            ).fetchone()
            return row[0] >= 20
        except:
            return False

    def log_decision(
        self,
        domain: str,
        decision: str,
        confidence: float,
        reasoning: str = "",
        metadata: dict = None
    ) -> str:
        """
        판단 기록.

        Args:
            domain: 판단 영역 (hunt, pipeline, strategy, crisis)
            decision: 판단 내용
            confidence: 신뢰도 (0.0 ~ 1.0)
            reasoning: 판단 근거
            metadata: 추가 정보

        Returns:
            decision_id
        """
        did = f"dec_{domain}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"

        try:
            self.conn.execute("""
                INSERT INTO decision_log
                (decision_id, domain, decision, confidence, reasoning,
                 metadata, outcome, created_at)
                VALUES (?, ?, ?, ?, ?, ?, NULL, ?)
            """, (
                did, domain, decision, confidence, reasoning,
                json.dumps(metadata or {}),
                datetime.utcnow().isoformat()
            ))
            self.conn.commit()

            logger.debug(
                "Metacog: logged %s [%s] conf=%.2f",
                did, domain, confidence
            )
        except Exception as e:
            logger.error("Failed to log decision: %s", e)

        return did

    def record_outcome(
        self,
        decision_id: str,
        outcome: str,
        actual_score: float = None
    ):
        """
        판단 결과 기록.

        Args:
            decision_id: 판단 ID
            outcome: 결과 (success, failure, partial)
            actual_score: 실제 점수 (선택)
        """
        try:
            self.conn.execute("""
                UPDATE decision_log
                SET outcome = ?, actual_score = ?, evaluated_at = ?
                WHERE decision_id = ?
            """, (
                outcome, actual_score,
                datetime.utcnow().isoformat(),
                decision_id
            ))
            self.conn.commit()

            logger.debug("Metacog: recorded outcome %s -> %s", decision_id, outcome)
        except Exception as e:
            logger.error("Failed to record outcome: %s", e)

    async def compute_calibration(self, domain: str = None) -> Dict:
        """
        보정 곡선 계산.
        신뢰도 버킷별 실제 성공률을 계산하여 ECE(Expected Calibration Error) 산출.

        Args:
            domain: 특정 도메인만 분석 (None이면 전체)

        Returns:
            보정 분석 결과
        """
        # 평가된 판단만 조회
        if domain:
            rows = self.conn.execute("""
                SELECT confidence, outcome, actual_score, domain
                FROM decision_log
                WHERE outcome IS NOT NULL AND domain = ?
                ORDER BY created_at DESC
                LIMIT 500
            """, (domain,)).fetchall()
        else:
            rows = self.conn.execute("""
                SELECT confidence, outcome, actual_score, domain
                FROM decision_log
                WHERE outcome IS NOT NULL
                ORDER BY created_at DESC
                LIMIT 500
            """).fetchall()

        if not rows:
            return {"status": "no_data", "domain": domain or "all"}

        # 신뢰도 버킷별 집계
        buckets = defaultdict(lambda: {"pred": [], "actual": []})

        for row in rows:
            conf = row[0]
            outcome = row[1]
            bucket = round(conf * 10) / 10  # 0.1 단위 버킷

            buckets[bucket]["pred"].append(conf)
            buckets[bucket]["actual"].append(1.0 if outcome == "success" else 0.0)

        # 버킷별 통계
        calibration = {}
        total_error = 0
        total_n = 0

        for bucket, data in sorted(buckets.items()):
            n = len(data["actual"])
            avg_pred = sum(data["pred"]) / n
            avg_actual = sum(data["actual"]) / n

            calibration[f"{bucket:.1f}"] = {
                "predicted": round(avg_pred, 3),
                "actual": round(avg_actual, 3),
                "error": round(avg_pred - avg_actual, 3),
                "count": n
            }

            total_error += abs(avg_pred - avg_actual) * n
            total_n += n

        # ECE (Expected Calibration Error)
        ece = total_error / total_n if total_n > 0 else 0

        # 편향 감지
        avg_conf = sum(r[0] for r in rows) / len(rows)
        avg_success = sum(1 for r in rows if r[1] == "success") / len(rows)

        biases = []
        if avg_conf - avg_success > 0.15:
            biases.append({
                "type": "overconfidence",
                "severity": round(avg_conf - avg_success, 3),
                "description": "판단 신뢰도가 실제 성공률보다 높음"
            })
        elif avg_success - avg_conf > 0.15:
            biases.append({
                "type": "underconfidence",
                "severity": round(avg_success - avg_conf, 3),
                "description": "판단 신뢰도가 실제 성공률보다 낮음"
            })

        # 품질 등급
        if ece < 0.05:
            quality = "excellent"
        elif ece < 0.10:
            quality = "good"
        elif ece < 0.20:
            quality = "fair"
        else:
            quality = "poor"

        return {
            "domain": domain or "all",
            "total_decisions": len(rows),
            "ece": round(ece, 4),
            "quality": quality,
            "avg_confidence": round(avg_conf, 3),
            "avg_success_rate": round(avg_success, 3),
            "buckets": calibration,
            "biases": biases,
            "analyzed_at": datetime.utcnow().isoformat()
        }

    async def get_correction_factor(
        self,
        domain: str,
        raw_confidence: float
    ) -> float:
        """
        보정된 신뢰도 계산.

        Args:
            domain: 판단 영역
            raw_confidence: 원래 신뢰도

        Returns:
            보정된 신뢰도
        """
        calibration = await self.compute_calibration(domain)

        if calibration.get("status") == "no_data":
            return raw_confidence

        bucket = f"{round(raw_confidence * 10) / 10:.1f}"
        buckets = calibration.get("buckets", {})

        if bucket in buckets:
            # 예측값과 실제값의 평균으로 보정
            actual = buckets[bucket]["actual"]
            corrected = (raw_confidence + actual) / 2
            return round(corrected, 3)

        return raw_confidence

    async def generate_report(self) -> Dict:
        """메타인지 종합 리포트 생성"""
        report = {
            "generated_at": datetime.utcnow().isoformat(),
            "domains": {}
        }

        # 도메인별 분석
        for domain in ["hunt", "pipeline", "strategy", "crisis"]:
            report["domains"][domain] = await self.compute_calibration(domain)

        # 전체 분석
        report["overall"] = await self.compute_calibration()

        # 최근 판단 통계
        try:
            recent = self.conn.execute("""
                SELECT domain, COUNT(*) as cnt,
                       AVG(confidence) as avg_conf,
                       SUM(CASE WHEN outcome='success' THEN 1 ELSE 0 END) as wins
                FROM decision_log
                WHERE created_at > datetime('now', '-7 days')
                GROUP BY domain
            """).fetchall()

            report["recent_7d"] = {
                r[0]: {
                    "count": r[1],
                    "avg_confidence": round(r[2] or 0, 3),
                    "success_count": r[3] or 0
                }
                for r in recent
            }
        except:
            report["recent_7d"] = {}

        return report

    def get_recent_decisions(self, limit: int = 20) -> List[Dict]:
        """최근 판단 목록"""
        try:
            rows = self.conn.execute("""
                SELECT decision_id, domain, decision, confidence,
                       outcome, created_at, evaluated_at
                FROM decision_log
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,)).fetchall()

            return [
                {
                    "id": r[0],
                    "domain": r[1],
                    "decision": r[2][:100] if r[2] else "",
                    "confidence": r[3],
                    "outcome": r[4],
                    "created_at": r[5],
                    "evaluated": r[6] is not None
                }
                for r in rows
            ]
        except:
            return []

    async def suggest_improvements(self) -> List[str]:
        """개선 제안 생성"""
        report = await self.generate_report()
        suggestions = []

        overall = report.get("overall", {})

        # ECE 기반 제안
        ece = overall.get("ece", 0)
        if ece > 0.15:
            suggestions.append(
                f"전체 보정 오차(ECE)가 {ece:.1%}로 높습니다. "
                "판단 시 더 보수적인 신뢰도를 사용하세요."
            )

        # 편향 기반 제안
        for bias in overall.get("biases", []):
            if bias["type"] == "overconfidence":
                suggestions.append(
                    f"과신 편향 감지: 신뢰도를 {bias['severity']:.1%} 낮추는 것을 권장합니다."
                )
            elif bias["type"] == "underconfidence":
                suggestions.append(
                    f"과소평가 편향 감지: 판단에 더 확신을 가져도 됩니다."
                )

        # 도메인별 제안
        for domain, data in report.get("domains", {}).items():
            if data.get("quality") == "poor":
                suggestions.append(
                    f"'{domain}' 영역의 판단 정확도가 낮습니다. "
                    "해당 영역의 판단 기준을 재검토하세요."
                )

        return suggestions
