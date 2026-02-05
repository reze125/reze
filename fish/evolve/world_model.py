"""
Predictive World Models — REZE v6.0 SOVEREIGN
행동 전 시뮬레이션

"이 글 쓰면 트래픽 얼마나?" 예측하여
go/no-go 판단을 지원합니다.

가동 조건: hunt_log >= 100 + traffic 데이터 20건
"""

import json
import logging
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger("reze.evolve.world_model")


@dataclass
class Prediction:
    """예측 결과"""
    prediction_id: str
    action_type: str
    predicted_outcome: Dict
    confidence: float
    model_version: str
    created_at: str


class WorldModel:
    """
    예측 세계 모델.
    과거 데이터 기반 통계 예측 + LLM 판단 앙상블.
    """

    def __init__(self, ssot, llm_router=None):
        """
        Args:
            ssot: SSOT 인스턴스
            llm_router: LLM 라우터
        """
        self.ssot = ssot
        self.conn = ssot.conn if hasattr(ssot, 'conn') else ssot
        self.llm = llm_router

    async def is_active(self) -> bool:
        """활성화 조건 확인: hunt_log >= 100 + traffic 데이터"""
        try:
            # hunt_log 카운트
            hunt_count = self.conn.execute(
                "SELECT COUNT(*) FROM hunt_log"
            ).fetchone()[0]

            # traffic 데이터 카운트
            traffic_count = self.conn.execute("""
                SELECT COUNT(*) FROM hunt_log
                WHERE traffic_result IS NOT NULL AND traffic_result > 0
            """).fetchone()[0]

            return hunt_count >= 100 and traffic_count >= 20

        except:
            # hunt_memory 폴백
            try:
                count = self.conn.execute(
                    "SELECT COUNT(*) FROM hunt_memory"
                ).fetchone()[0]
                return count >= 100
            except:
                return False

    async def predict_hunt_outcome(
        self,
        niche: str,
        strategy: str,
        keyword: str,
        title: str
    ) -> Prediction:
        """
        사냥 결과 예측.

        Args:
            niche: 니치
            strategy: 전략
            keyword: 키워드
            title: 제목

        Returns:
            Prediction 객체
        """
        pred_id = f"pred_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"

        # 1. 통계 기반 예측
        stats_pred = await self._predict_from_stats(niche, strategy)

        # 2. LLM 기반 예측
        llm_pred = await self._predict_from_llm(niche, strategy, keyword, title, stats_pred)

        # 3. 앙상블
        if llm_pred and stats_pred:
            predicted = {
                "expected_quality": (
                    stats_pred["expected_quality"] * 0.4 +
                    llm_pred.get("expected_quality", 5) * 0.6
                ),
                "success_probability": (
                    stats_pred["success_probability"] * 0.4 +
                    llm_pred.get("success_probability", 0.5) * 0.6
                ),
            }
            confidence = (stats_pred["confidence"] + llm_pred.get("confidence", 0.5)) / 2
            model_version = "ensemble_v1"

        elif stats_pred:
            predicted = stats_pred
            confidence = stats_pred["confidence"] * 0.7
            model_version = "stats_v1"

        else:
            # 폴백
            predicted = {
                "expected_quality": 5.0,
                "success_probability": 0.5,
            }
            confidence = 0.1
            model_version = "fallback"

        # DB에 기록
        try:
            self.conn.execute("""
                INSERT INTO predictions
                (prediction_id, action_type, niche, strategy, keyword, title,
                 predicted_outcome, confidence, model_version, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                pred_id, "hunt", niche, strategy, keyword, title,
                json.dumps(predicted),
                confidence,
                model_version,
                datetime.utcnow().isoformat()
            ))
            self.conn.commit()
        except Exception as e:
            logger.error("Failed to save prediction: %s", e)

        return Prediction(
            prediction_id=pred_id,
            action_type="hunt",
            predicted_outcome=predicted,
            confidence=confidence,
            model_version=model_version,
            created_at=datetime.utcnow().isoformat()
        )

    async def _predict_from_stats(
        self,
        niche: str,
        strategy: str
    ) -> Optional[Dict]:
        """과거 데이터 기반 통계 예측"""
        try:
            # hunt_log 사용
            row = self.conn.execute("""
                SELECT COUNT(*) as total,
                       AVG(quality_score) as avg_quality,
                       AVG(CASE WHEN status='success' THEN 1.0 ELSE 0.0 END) as success_rate
                FROM hunt_log
                WHERE niche = ? AND strategy = ?
                  AND created_at > datetime('now', '-60 days')
            """, (niche, strategy)).fetchone()

            if row and row[0] >= 5:
                return {
                    "expected_quality": round(row[1] or 5, 1),
                    "success_probability": round(row[2] or 0.5, 2),
                    "confidence": min(row[0] / 50.0, 0.9),
                    "sample_size": row[0]
                }

        except:
            pass

        # hunt_memory 폴백
        try:
            row = self.conn.execute("""
                SELECT COUNT(*) as total,
                       AVG(score) as avg_score,
                       AVG(success) as success_rate
                FROM hunt_memory
                WHERE strategy = ?
                  AND created_at > datetime('now', '-60 days')
            """, (strategy,)).fetchone()

            if row and row[0] >= 5:
                return {
                    "expected_quality": round((row[1] or 0.5) * 10, 1),
                    "success_probability": round(row[2] or 0.5, 2),
                    "confidence": min(row[0] / 50.0, 0.9),
                    "sample_size": row[0]
                }

        except:
            pass

        return None

    async def _predict_from_llm(
        self,
        niche: str,
        strategy: str,
        keyword: str,
        title: str,
        stats: Optional[Dict]
    ) -> Optional[Dict]:
        """LLM 기반 예측"""
        if not self.llm:
            return None

        prompt = f"""Predict the outcome of this content:
Niche: {niche}
Strategy: {strategy}
Keyword: {keyword}
Title: {title}
Historical stats: {json.dumps(stats) if stats else 'No data'}

Respond in JSON:
{{
  "expected_quality": 1-10,
  "success_probability": 0.0-1.0,
  "confidence": 0.0-1.0,
  "reasoning": "brief explanation"
}}"""

        try:
            response = await self.llm.call(
                "cerebras",
                [{"role": "user", "content": prompt}],
                max_tokens=500
            )

            text = response.text if hasattr(response, 'text') else str(response)
            return json.loads(self._extract_json(text))

        except:
            return None

    def _extract_json(self, text: str) -> str:
        """텍스트에서 JSON 추출"""
        if "```json" in text:
            return text.split("```json")[1].split("```")[0].strip()

        start = text.find("{")
        end = text.rfind("}") + 1

        if start >= 0 and end > start:
            return text[start:end]

        return "{}"

    async def evaluate_prediction(
        self,
        prediction_id: str,
        actual_outcome: Dict
    ):
        """
        예측 평가.
        실제 결과와 비교하여 예측 오차 기록.

        Args:
            prediction_id: 예측 ID
            actual_outcome: 실제 결과 {"quality_score": X, "success": bool}
        """
        try:
            row = self.conn.execute(
                "SELECT predicted_outcome FROM predictions WHERE prediction_id = ?",
                (prediction_id,)
            ).fetchone()

            if not row:
                return

            predicted = json.loads(row[0])

            # 오차 계산
            errors = []
            for key in predicted:
                if key in actual_outcome:
                    pred_val = float(predicted[key])
                    actual_val = float(actual_outcome[key])
                    error = abs(pred_val - actual_val) / max(pred_val, 1)
                    errors.append(error)

            mae = sum(errors) / len(errors) if errors else 1.0

            # 평가 기록
            self.conn.execute("""
                INSERT INTO prediction_evaluations
                (prediction_id, actual_outcome, prediction_error, evaluated_at)
                VALUES (?, ?, ?, ?)
            """, (
                prediction_id,
                json.dumps(actual_outcome),
                mae,
                datetime.utcnow().isoformat()
            ))
            self.conn.commit()

            logger.debug("Prediction %s evaluated: MAE=%.3f", prediction_id, mae)

        except Exception as e:
            logger.error("Failed to evaluate prediction: %s", e)

    async def should_proceed(
        self,
        prediction: Prediction,
        threshold: float = 0.4
    ) -> Tuple[bool, str]:
        """
        예측 기반 진행 여부 판단.

        Args:
            prediction: 예측 결과
            threshold: 성공 확률 임계값

        Returns:
            (진행 여부, 이유)
        """
        prob = prediction.predicted_outcome.get("success_probability", 0.5)

        # 신뢰도가 낮으면 진행 (탐색적)
        if prediction.confidence < 0.3:
            return True, "Low confidence prediction - proceed cautiously for learning"

        # 임계값 비교
        if prob >= threshold:
            return True, f"P(success) = {prob:.1%} >= {threshold:.1%} threshold"
        else:
            return False, f"P(success) = {prob:.1%} < {threshold:.1%} threshold"

    def get_model_accuracy(self) -> Dict:
        """모델 정확도 통계"""
        try:
            rows = self.conn.execute("""
                SELECT p.model_version,
                       COUNT(*) as count,
                       AVG(e.prediction_error) as avg_error
                FROM predictions p
                JOIN prediction_evaluations e ON p.prediction_id = e.prediction_id
                GROUP BY p.model_version
            """).fetchall()

            return {
                r[0]: {
                    "count": r[1],
                    "avg_error": round(r[2] or 0, 3)
                }
                for r in rows
            }
        except:
            return {}

    def get_recent_predictions(self, limit: int = 20) -> list:
        """최근 예측 목록"""
        try:
            rows = self.conn.execute("""
                SELECT p.prediction_id, p.niche, p.strategy, p.keyword,
                       p.predicted_outcome, p.confidence, p.model_version,
                       p.created_at, e.prediction_error
                FROM predictions p
                LEFT JOIN prediction_evaluations e ON p.prediction_id = e.prediction_id
                ORDER BY p.created_at DESC
                LIMIT ?
            """, (limit,)).fetchall()

            return [
                {
                    "id": r[0],
                    "niche": r[1],
                    "strategy": r[2],
                    "keyword": r[3],
                    "predicted": json.loads(r[4] or "{}"),
                    "confidence": r[5],
                    "model": r[6],
                    "created_at": r[7],
                    "error": r[8]
                }
                for r in rows
            ]
        except:
            return []
