"""
EVENT HORIZON v3.0 — A/B Experiment Framework
콘텐츠 실험 시스템

가설 기반 실험으로 콘텐츠 성과 최적화.
제목, CTA, 레이아웃, 발행 시간 등 테스트.
"""

import logging
import json
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from enum import Enum

logger = logging.getLogger("reze.fish.experiment")


class ExperimentType(Enum):
    """실험 유형"""
    TITLE = "title"             # 제목 A/B
    CTA = "cta"                 # CTA 버튼/텍스트
    LAYOUT = "layout"           # 레이아웃
    TIMING = "timing"           # 발행 시간
    CONTENT_LENGTH = "length"   # 콘텐츠 길이
    IMAGE = "image"             # 이미지 유무/스타일
    META = "meta"               # 메타 설명


class ExperimentStatus(Enum):
    """실험 상태"""
    DRAFT = "draft"
    RUNNING = "running"
    COMPLETED = "completed"
    STOPPED = "stopped"


@dataclass
class Variant:
    """실험 변형"""
    name: str                   # A, B, C, ...
    value: Any                  # 실제 값
    impressions: int = 0
    conversions: int = 0
    revenue: float = 0.0

    @property
    def conversion_rate(self) -> float:
        return self.conversions / max(self.impressions, 1)

    @property
    def revenue_per_impression(self) -> float:
        return self.revenue / max(self.impressions, 1)


@dataclass
class Experiment:
    """실험"""
    id: int = 0
    name: str = ""
    hypothesis: str = ""
    experiment_type: ExperimentType = ExperimentType.TITLE
    variants: List[Variant] = field(default_factory=list)
    metrics: List[str] = field(default_factory=list)  # ["ctr", "conversions", "revenue"]
    status: ExperimentStatus = ExperimentStatus.DRAFT
    winner_variant: str = ""
    confidence: float = 0.0
    started_at: str = ""
    ended_at: str = ""
    created_at: str = ""
    target_content: str = ""    # 대상 콘텐츠 (슬러그)


@dataclass
class ExperimentResult:
    """실험 결과"""
    experiment: Experiment
    winner: Optional[Variant]
    confidence: float
    improvement: float          # 기준 대비 개선율 (%)
    recommendation: str


class ExperimentEngine:
    """
    A/B 실험 엔진.
    가설 기반 실험으로 콘텐츠 성과 최적화.
    """

    # 최소 표본 크기
    MIN_SAMPLE_SIZE = 100

    # 신뢰도 임계값
    CONFIDENCE_THRESHOLD = 0.95

    def __init__(self, ssot):
        self.ssot = ssot

    # ═══════════════════════════════════════════════════════════════════════
    # 실험 생성
    # ═══════════════════════════════════════════════════════════════════════

    def create_experiment(
        self,
        name: str,
        hypothesis: str,
        experiment_type: ExperimentType,
        variants: List[Dict],
        metrics: List[str] = None,
        target_content: str = ""
    ) -> Optional[int]:
        """새 실험 생성"""
        try:
            variants_json = json.dumps([
                {"name": v.get("name", f"V{i}"), "value": v.get("value")}
                for i, v in enumerate(variants)
            ])
            metrics_json = json.dumps(metrics or ["ctr", "conversions"])

            cursor = self.ssot.conn.execute("""
                INSERT INTO experiment
                (name, hypothesis, experiment_type, variants, metrics, status)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                name,
                hypothesis,
                experiment_type.value,
                variants_json,
                metrics_json,
                ExperimentStatus.DRAFT.value
            ))
            self.ssot.conn.commit()

            exp_id = cursor.lastrowid
            logger.info("Experiment: Created '%s' (id=%d)", name, exp_id)
            return exp_id

        except Exception as e:
            logger.error("Failed to create experiment: %s", e)
            return None

    def start_experiment(self, experiment_id: int) -> bool:
        """실험 시작"""
        try:
            self.ssot.conn.execute("""
                UPDATE experiment
                SET status = ?, started_at = datetime('now')
                WHERE id = ?
            """, (ExperimentStatus.RUNNING.value, experiment_id))
            self.ssot.conn.commit()

            logger.info("Experiment: Started id=%d", experiment_id)
            return True
        except Exception as e:
            logger.error("Failed to start experiment: %s", e)
            return False

    def stop_experiment(self, experiment_id: int) -> bool:
        """실험 중지"""
        try:
            self.ssot.conn.execute("""
                UPDATE experiment
                SET status = ?, ended_at = datetime('now')
                WHERE id = ?
            """, (ExperimentStatus.STOPPED.value, experiment_id))
            self.ssot.conn.commit()

            logger.info("Experiment: Stopped id=%d", experiment_id)
            return True
        except Exception as e:
            logger.error("Failed to stop experiment: %s", e)
            return False

    # ═══════════════════════════════════════════════════════════════════════
    # 실험 조회
    # ═══════════════════════════════════════════════════════════════════════

    def get_experiment(self, experiment_id: int) -> Optional[Experiment]:
        """실험 조회"""
        try:
            row = self.ssot.conn.execute("""
                SELECT id, name, hypothesis, experiment_type, variants,
                       metrics, status, winner_variant, confidence,
                       started_at, ended_at, created_at
                FROM experiment WHERE id = ?
            """, (experiment_id,)).fetchone()

            if row:
                variants_data = json.loads(row[4] or "[]")
                variants = [
                    Variant(name=v["name"], value=v["value"])
                    for v in variants_data
                ]

                return Experiment(
                    id=row[0],
                    name=row[1],
                    hypothesis=row[2],
                    experiment_type=ExperimentType(row[3]),
                    variants=variants,
                    metrics=json.loads(row[5] or "[]"),
                    status=ExperimentStatus(row[6]),
                    winner_variant=row[7] or "",
                    confidence=row[8] or 0,
                    started_at=row[9] or "",
                    ended_at=row[10] or "",
                    created_at=row[11] or "",
                )
        except Exception as e:
            logger.error("Failed to get experiment: %s", e)
        return None

    def get_running_experiments(self) -> List[Experiment]:
        """실행 중인 실험 목록"""
        try:
            rows = self.ssot.conn.execute("""
                SELECT id FROM experiment WHERE status = ?
            """, (ExperimentStatus.RUNNING.value,)).fetchall()

            return [
                self.get_experiment(r[0])
                for r in rows
                if self.get_experiment(r[0])
            ]
        except Exception as e:
            logger.error("Failed to get running experiments: %s", e)
            return []

    # ═══════════════════════════════════════════════════════════════════════
    # 변형 할당
    # ═══════════════════════════════════════════════════════════════════════

    def assign_variant(self, experiment_id: int, user_id: str = None) -> Optional[str]:
        """사용자에게 변형 할당"""
        experiment = self.get_experiment(experiment_id)
        if not experiment or experiment.status != ExperimentStatus.RUNNING:
            return None

        if not experiment.variants:
            return None

        # 균등 무작위 할당
        variant = random.choice(experiment.variants)

        # 할당 기록 (signals 테이블 사용)
        self.ssot.save_signal("experiment_assignment", json.dumps({
            "experiment_id": experiment_id,
            "variant": variant.name,
            "user_id": user_id,
        }))

        return variant.name

    # ═══════════════════════════════════════════════════════════════════════
    # 이벤트 기록
    # ═══════════════════════════════════════════════════════════════════════

    def record_impression(self, experiment_id: int, variant_name: str):
        """노출 기록"""
        self._record_event(experiment_id, variant_name, "impression")

    def record_conversion(self, experiment_id: int, variant_name: str,
                         revenue: float = 0.0):
        """전환 기록"""
        self._record_event(experiment_id, variant_name, "conversion", revenue)

    def _record_event(self, experiment_id: int, variant_name: str,
                     event_type: str, value: float = 0.0):
        """이벤트 기록"""
        try:
            self.ssot.save_signal("experiment_event", json.dumps({
                "experiment_id": experiment_id,
                "variant": variant_name,
                "event_type": event_type,
                "value": value,
            }))
        except Exception as e:
            logger.error("Failed to record experiment event: %s", e)

    # ═══════════════════════════════════════════════════════════════════════
    # 결과 분석
    # ═══════════════════════════════════════════════════════════════════════

    def analyze_experiment(self, experiment_id: int) -> Optional[ExperimentResult]:
        """실험 결과 분석"""
        experiment = self.get_experiment(experiment_id)
        if not experiment:
            return None

        # 이벤트 데이터 집계
        variant_stats = self._aggregate_events(experiment_id)

        # 변형 업데이트
        for variant in experiment.variants:
            stats = variant_stats.get(variant.name, {})
            variant.impressions = stats.get("impressions", 0)
            variant.conversions = stats.get("conversions", 0)
            variant.revenue = stats.get("revenue", 0)

        # 승자 결정
        winner, confidence = self._determine_winner(experiment.variants)

        # 개선율 계산
        improvement = 0.0
        if winner and len(experiment.variants) > 1:
            control = experiment.variants[0]  # 첫 번째가 컨트롤
            if control.conversion_rate > 0:
                improvement = (
                    (winner.conversion_rate - control.conversion_rate) /
                    control.conversion_rate * 100
                )

        # 권장 사항
        recommendation = self._generate_recommendation(
            experiment, winner, confidence, improvement
        )

        return ExperimentResult(
            experiment=experiment,
            winner=winner,
            confidence=confidence,
            improvement=improvement,
            recommendation=recommendation,
        )

    def _aggregate_events(self, experiment_id: int) -> Dict[str, Dict]:
        """이벤트 집계"""
        stats = {}

        try:
            rows = self.ssot.conn.execute("""
                SELECT data FROM signals
                WHERE kind = 'experiment_event'
                AND data LIKE ?
            """, (f'%"experiment_id": {experiment_id}%',)).fetchall()

            for row in rows:
                try:
                    data = json.loads(row[0])
                    variant = data.get("variant", "")
                    event_type = data.get("event_type", "")
                    value = data.get("value", 0)

                    if variant not in stats:
                        stats[variant] = {
                            "impressions": 0,
                            "conversions": 0,
                            "revenue": 0,
                        }

                    if event_type == "impression":
                        stats[variant]["impressions"] += 1
                    elif event_type == "conversion":
                        stats[variant]["conversions"] += 1
                        stats[variant]["revenue"] += value
                except:
                    continue

        except Exception as e:
            logger.error("Failed to aggregate events: %s", e)

        return stats

    def _determine_winner(self, variants: List[Variant]) -> tuple:
        """승자 결정 (간단한 통계 테스트)"""
        if not variants:
            return None, 0.0

        # 최소 표본 크기 체크
        total_impressions = sum(v.impressions for v in variants)
        if total_impressions < self.MIN_SAMPLE_SIZE * len(variants):
            return None, 0.0

        # 전환율 기준 정렬
        sorted_variants = sorted(
            variants,
            key=lambda v: v.conversion_rate,
            reverse=True
        )

        winner = sorted_variants[0]
        runner_up = sorted_variants[1] if len(sorted_variants) > 1 else None

        # 간단한 신뢰도 계산 (실제로는 Chi-squared 또는 Bayesian)
        if runner_up:
            # 두 비율 간 차이 기반 (근사)
            diff = winner.conversion_rate - runner_up.conversion_rate
            se = ((winner.conversion_rate * (1 - winner.conversion_rate) / max(winner.impressions, 1)) +
                  (runner_up.conversion_rate * (1 - runner_up.conversion_rate) / max(runner_up.impressions, 1))) ** 0.5

            if se > 0:
                z_score = diff / se
                # 간단한 신뢰도 매핑
                if z_score > 2.58:
                    confidence = 0.99
                elif z_score > 1.96:
                    confidence = 0.95
                elif z_score > 1.64:
                    confidence = 0.90
                else:
                    confidence = 0.5 + z_score * 0.2
            else:
                confidence = 0.5
        else:
            confidence = 0.5

        return winner, min(max(confidence, 0), 1)

    def _generate_recommendation(
        self,
        experiment: Experiment,
        winner: Optional[Variant],
        confidence: float,
        improvement: float
    ) -> str:
        """권장 사항 생성"""
        if not winner:
            return "더 많은 데이터가 필요합니다. 실험을 계속 진행하세요."

        if confidence >= self.CONFIDENCE_THRESHOLD:
            if improvement > 10:
                return f"'{winner.name}' 변형을 적용하세요. {improvement:.1f}% 개선, 신뢰도 {confidence*100:.0f}%"
            elif improvement > 0:
                return f"'{winner.name}' 변형이 소폭 우세합니다. 추가 테스트 권장."
            else:
                return "유의미한 차이가 없습니다. 기존 버전 유지를 권장합니다."
        else:
            return f"신뢰도가 낮습니다 ({confidence*100:.0f}%). 더 많은 데이터를 수집하세요."

    # ═══════════════════════════════════════════════════════════════════════
    # 실험 완료
    # ═══════════════════════════════════════════════════════════════════════

    def complete_experiment(self, experiment_id: int) -> Optional[ExperimentResult]:
        """실험 완료 및 결과 저장"""
        result = self.analyze_experiment(experiment_id)
        if not result:
            return None

        try:
            winner_name = result.winner.name if result.winner else ""

            self.ssot.conn.execute("""
                UPDATE experiment
                SET status = ?,
                    winner_variant = ?,
                    confidence = ?,
                    ended_at = datetime('now'),
                    results = ?
                WHERE id = ?
            """, (
                ExperimentStatus.COMPLETED.value,
                winner_name,
                result.confidence,
                json.dumps({
                    "improvement": result.improvement,
                    "recommendation": result.recommendation,
                    "variants": [
                        {
                            "name": v.name,
                            "impressions": v.impressions,
                            "conversions": v.conversions,
                            "revenue": v.revenue,
                            "conversion_rate": v.conversion_rate,
                        }
                        for v in result.experiment.variants
                    ]
                }),
                experiment_id
            ))
            self.ssot.conn.commit()

            logger.info("Experiment: Completed id=%d, winner=%s, confidence=%.2f",
                       experiment_id, winner_name, result.confidence)

        except Exception as e:
            logger.error("Failed to complete experiment: %s", e)

        return result

    # ═══════════════════════════════════════════════════════════════════════
    # 자동 실험 제안
    # ═══════════════════════════════════════════════════════════════════════

    def suggest_experiments(self, blog: str = None) -> List[Dict]:
        """실험 제안"""
        suggestions = []

        # 1. 저조한 CTR 콘텐츠 → 제목 테스트
        suggestions.append({
            "type": ExperimentType.TITLE.value,
            "hypothesis": "더 구체적인 숫자를 포함한 제목이 CTR을 높인다",
            "example": {
                "A": "Best AI Writing Tools",
                "B": "7 Best AI Writing Tools (2025 Tested)",
            }
        })

        # 2. 저조한 전환율 → CTA 테스트
        suggestions.append({
            "type": ExperimentType.CTA.value,
            "hypothesis": "행동 지향적 CTA가 전환율을 높인다",
            "example": {
                "A": "Learn More",
                "B": "Start Free Trial Now",
            }
        })

        # 3. 발행 시간 테스트
        suggestions.append({
            "type": ExperimentType.TIMING.value,
            "hypothesis": "오전 10시 발행이 오후 3시보다 트래픽이 높다",
            "example": {
                "A": "10:00 AM",
                "B": "3:00 PM",
            }
        })

        return suggestions
