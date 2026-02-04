"""DSPy - 프롬프트 성능 분석 및 자동 최적화 엔진.

LLM 호출 성능 데이터를 분석하여 프롬프트/역할 할당을 자동 최적화.
수동 튜닝 없이 점진적 성능 향상 달성.
"""
import logging
import json
import hashlib
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from datetime import datetime, timedelta

logger = logging.getLogger("REZE.dspy")


@dataclass
class StepMetrics:
    """step_type별 성능 메트릭."""
    step_type: str
    total_calls: int = 0
    success_count: int = 0
    error_count: int = 0
    avg_latency_ms: float = 0.0
    avg_tokens: float = 0.0
    avg_quality: float = None
    provider_breakdown: Dict[str, Dict] = field(default_factory=dict)


@dataclass
class OptimizationProposal:
    """최적화 제안."""
    optimization_type: str  # role_assignment, prompt_template
    target: str             # step_type
    current_value: str
    proposed_value: str
    reason: str
    expected_improvement: str
    confidence: float


class DSPyOptimizer:
    """프롬프트 성능 분석 및 자동 최적화."""

    # 성능 임계값
    MIN_SAMPLES_FOR_ANALYSIS = 10    # 최소 샘플 수
    LATENCY_THRESHOLD_MS = 5000      # 지연 경고 임계값
    ERROR_RATE_THRESHOLD = 0.15      # 에러율 경고 임계값
    QUALITY_THRESHOLD = 60.0         # 품질 경고 임계값

    def __init__(self, ssot, router=None):
        """
        Args:
            ssot: SSOT 인스턴스
            router: ModelRouter 인스턴스 (선택)
        """
        self.ssot = ssot
        self.router = router

    def record_call(
        self,
        step_type: str,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: int,
        success: bool,
        quality_score: float = None,
        task_id: str = None,
        prompt_text: str = None
    ):
        """LLM 호출 성능 기록."""
        prompt_hash = None
        if prompt_text:
            prompt_hash = hashlib.md5(prompt_text[:1000].encode()).hexdigest()[:16]

        self.ssot.conn.execute("""
            INSERT INTO prompt_metrics
            (step_type, provider, model, prompt_hash, input_tokens, output_tokens,
             latency_ms, success, quality_score, task_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            step_type, provider, model or "", prompt_hash,
            input_tokens, output_tokens, latency_ms,
            1 if success else 0, quality_score, task_id
        ))
        self.ssot.conn.commit()

    def get_step_metrics(self, days: int = 7) -> List[StepMetrics]:
        """step_type별 성능 메트릭 조회."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()

        rows = self.ssot.conn.execute("""
            SELECT
                step_type,
                COUNT(*) as total_calls,
                SUM(success) as success_count,
                SUM(1 - success) as error_count,
                AVG(latency_ms) as avg_latency,
                AVG(input_tokens + output_tokens) as avg_tokens,
                AVG(CASE WHEN quality_score IS NOT NULL THEN quality_score END) as avg_quality
            FROM prompt_metrics
            WHERE created_at > ?
            GROUP BY step_type
            ORDER BY total_calls DESC
        """, (cutoff,)).fetchall()

        metrics = []
        for row in rows:
            d = dict(row)
            # provider별 breakdown
            provider_rows = self.ssot.conn.execute("""
                SELECT provider,
                       COUNT(*) as calls,
                       AVG(latency_ms) as avg_latency,
                       SUM(1 - success) as errors
                FROM prompt_metrics
                WHERE step_type = ? AND created_at > ?
                GROUP BY provider
            """, (d["step_type"], cutoff)).fetchall()

            provider_breakdown = {}
            for pr in provider_rows:
                pd = dict(pr)
                provider_breakdown[pd["provider"]] = {
                    "calls": pd["calls"],
                    "avg_latency": round(pd["avg_latency"] or 0, 1),
                    "errors": pd["errors"] or 0
                }

            metrics.append(StepMetrics(
                step_type=d["step_type"],
                total_calls=d["total_calls"],
                success_count=d["success_count"] or 0,
                error_count=d["error_count"] or 0,
                avg_latency_ms=round(d["avg_latency"] or 0, 1),
                avg_tokens=round(d["avg_tokens"] or 0, 1),
                avg_quality=round(d["avg_quality"], 1) if d["avg_quality"] else None,
                provider_breakdown=provider_breakdown
            ))

        return metrics

    def get_provider_performance(self, days: int = 7) -> Dict[str, Dict]:
        """프로바이더별 전체 성능 요약."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()

        rows = self.ssot.conn.execute("""
            SELECT
                provider,
                COUNT(*) as total_calls,
                SUM(success) as success_count,
                AVG(latency_ms) as avg_latency,
                AVG(input_tokens + output_tokens) as avg_tokens
            FROM prompt_metrics
            WHERE created_at > ?
            GROUP BY provider
            ORDER BY total_calls DESC
        """, (cutoff,)).fetchall()

        result = {}
        for row in rows:
            d = dict(row)
            result[d["provider"]] = {
                "total_calls": d["total_calls"],
                "success_rate": d["success_count"] / d["total_calls"] if d["total_calls"] > 0 else 0,
                "avg_latency_ms": round(d["avg_latency"] or 0, 1),
                "avg_tokens": round(d["avg_tokens"] or 0, 1)
            }
        return result

    def analyze_and_propose(self, days: int = 7) -> List[OptimizationProposal]:
        """성능 분석 및 최적화 제안 생성."""
        metrics = self.get_step_metrics(days)
        proposals = []

        # 현재 ROLE_ASSIGNMENT 가져오기
        try:
            from reze_core import ModelRouter
            current_assignment = ModelRouter.ROLE_ASSIGNMENT.copy()
        except ImportError:
            current_assignment = {}

        for m in metrics:
            if m.total_calls < self.MIN_SAMPLES_FOR_ANALYSIS:
                continue

            # 1. 에러율 검사
            error_rate = m.error_count / m.total_calls if m.total_calls > 0 else 0
            if error_rate > self.ERROR_RATE_THRESHOLD:
                best_provider = self._find_best_provider(m, "errors")
                if best_provider and best_provider != current_assignment.get(m.step_type):
                    proposals.append(OptimizationProposal(
                        optimization_type="role_assignment",
                        target=m.step_type,
                        current_value=current_assignment.get(m.step_type, "unknown"),
                        proposed_value=best_provider,
                        reason=f"에러율 {error_rate:.1%} (>{self.ERROR_RATE_THRESHOLD:.0%})",
                        expected_improvement="에러율 감소 기대",
                        confidence=0.7
                    ))

            # 2. 지연 검사
            if m.avg_latency_ms > self.LATENCY_THRESHOLD_MS:
                best_provider = self._find_best_provider(m, "latency")
                if best_provider and best_provider != current_assignment.get(m.step_type):
                    proposals.append(OptimizationProposal(
                        optimization_type="role_assignment",
                        target=m.step_type,
                        current_value=current_assignment.get(m.step_type, "unknown"),
                        proposed_value=best_provider,
                        reason=f"평균 지연 {m.avg_latency_ms:.0f}ms (>{self.LATENCY_THRESHOLD_MS}ms)",
                        expected_improvement="지연 감소 기대",
                        confidence=0.6
                    ))

            # 3. 품질 검사 (품질 점수가 있는 경우)
            if m.avg_quality and m.avg_quality < self.QUALITY_THRESHOLD:
                best_provider = self._find_best_provider(m, "quality")
                if best_provider and best_provider != current_assignment.get(m.step_type):
                    proposals.append(OptimizationProposal(
                        optimization_type="role_assignment",
                        target=m.step_type,
                        current_value=current_assignment.get(m.step_type, "unknown"),
                        proposed_value=best_provider,
                        reason=f"품질 점수 {m.avg_quality:.1f} (<{self.QUALITY_THRESHOLD})",
                        expected_improvement="품질 향상 기대",
                        confidence=0.5
                    ))

        return proposals

    def _find_best_provider(self, metrics: StepMetrics, criterion: str) -> Optional[str]:
        """기준에 따라 최적 provider 찾기."""
        if not metrics.provider_breakdown:
            return None

        candidates = []
        for provider, data in metrics.provider_breakdown.items():
            if data["calls"] < 3:  # 최소 3회 이상 호출된 provider만
                continue

            score = 0
            if criterion == "errors":
                error_rate = data["errors"] / data["calls"]
                score = 1 - error_rate  # 에러 적을수록 좋음
            elif criterion == "latency":
                score = 1 / (data["avg_latency"] + 1)  # 지연 적을수록 좋음
            elif criterion == "quality":
                # 품질은 provider별로 추적 안 되므로 latency로 대체
                score = 1 / (data["avg_latency"] + 1)

            candidates.append((provider, score))

        if not candidates:
            return None

        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[0][0]

    def save_proposal(self, proposal: OptimizationProposal) -> int:
        """최적화 제안 저장."""
        cursor = self.ssot.conn.execute("""
            INSERT INTO dspy_optimizations
            (optimization_type, target, old_value, new_value, reason)
            VALUES (?, ?, ?, ?, ?)
        """, (
            proposal.optimization_type,
            proposal.target,
            proposal.current_value,
            proposal.proposed_value,
            proposal.reason
        ))
        self.ssot.conn.commit()
        return cursor.lastrowid

    def get_pending_proposals(self) -> List[Dict]:
        """승인 대기 중인 제안 조회."""
        rows = self.ssot.conn.execute("""
            SELECT * FROM dspy_optimizations
            WHERE status = 'proposed'
            ORDER BY created_at DESC
        """).fetchall()
        return [dict(r) for r in rows]

    def get_applied_optimizations(self) -> List[Dict]:
        """적용된 최적화 조회."""
        rows = self.ssot.conn.execute("""
            SELECT * FROM dspy_optimizations
            WHERE status = 'applied'
            ORDER BY applied_at DESC
        """).fetchall()
        return [dict(r) for r in rows]

    def apply_proposal(self, proposal_id: int) -> bool:
        """제안 적용 (ROLE_ASSIGNMENT 업데이트)."""
        row = self.ssot.conn.execute(
            "SELECT * FROM dspy_optimizations WHERE id = ?",
            (proposal_id,)
        ).fetchone()

        if not row:
            return False

        d = dict(row)
        if d["optimization_type"] == "role_assignment":
            # 런타임 ROLE_ASSIGNMENT 업데이트
            try:
                from reze_core import ModelRouter
                ModelRouter.ROLE_ASSIGNMENT[d["target"]] = d["new_value"]
                logger.info(f"[DSPy] Applied: {d['target']} → {d['new_value']}")
            except ImportError:
                logger.warning("[DSPy] ModelRouter import failed")
                return False

        self.ssot.conn.execute("""
            UPDATE dspy_optimizations
            SET status = 'applied', applied_at = datetime('now')
            WHERE id = ?
        """, (proposal_id,))
        self.ssot.conn.commit()
        return True

    def rollback_proposal(self, proposal_id: int) -> bool:
        """제안 롤백."""
        row = self.ssot.conn.execute(
            "SELECT * FROM dspy_optimizations WHERE id = ? AND status = 'applied'",
            (proposal_id,)
        ).fetchone()

        if not row:
            return False

        d = dict(row)
        if d["optimization_type"] == "role_assignment":
            try:
                from reze_core import ModelRouter
                ModelRouter.ROLE_ASSIGNMENT[d["target"]] = d["old_value"]
                logger.info(f"[DSPy] Rolled back: {d['target']} → {d['old_value']}")
            except ImportError:
                logger.warning("[DSPy] ModelRouter import failed")
                return False

        self.ssot.conn.execute("""
            UPDATE dspy_optimizations
            SET status = 'rolled_back'
            WHERE id = ?
        """, (proposal_id,))
        self.ssot.conn.commit()
        return True

    def reject_proposal(self, proposal_id: int) -> bool:
        """제안 거부."""
        self.ssot.conn.execute("""
            UPDATE dspy_optimizations
            SET status = 'rejected'
            WHERE id = ? AND status = 'proposed'
        """, (proposal_id,))
        self.ssot.conn.commit()
        return True

    def generate_weekly_report(self, days: int = 7) -> str:
        """주간 성능 리포트 생성."""
        metrics = self.get_step_metrics(days)
        proposals = self.analyze_and_propose(days)
        provider_perf = self.get_provider_performance(days)

        lines = [f"# DSPy 주간 성능 리포트", f"분석 기간: 최근 {days}일", ""]

        # 전체 요약
        total_calls = sum(m.total_calls for m in metrics)
        total_errors = sum(m.error_count for m in metrics)

        if total_calls > 0:
            avg_latency = sum(m.avg_latency_ms * m.total_calls for m in metrics) / total_calls
            error_rate = total_errors / total_calls
        else:
            avg_latency = 0
            error_rate = 0

        lines.append("## 전체 요약")
        lines.append(f"- 총 호출: {total_calls:,}")
        lines.append(f"- 에러율: {error_rate:.1%}")
        lines.append(f"- 평균 지연: {avg_latency:.0f}ms")
        lines.append("")

        # 프로바이더별 성능
        if provider_perf:
            lines.append("## 프로바이더별 성능")
            lines.append("| Provider | 호출 | 성공률 | 평균 지연 |")
            lines.append("|----------|------|--------|----------|")
            for provider, perf in provider_perf.items():
                lines.append(
                    f"| {provider} | {perf['total_calls']} | "
                    f"{perf['success_rate']:.1%} | {perf['avg_latency_ms']:.0f}ms |"
                )
            lines.append("")

        # step_type별 성능
        if metrics:
            lines.append("## Step Type별 성능")
            lines.append("| Step Type | 호출 | 성공률 | 평균 지연 | 평균 토큰 |")
            lines.append("|-----------|------|--------|----------|----------|")
            for m in metrics[:10]:
                success_rate = m.success_count / m.total_calls if m.total_calls > 0 else 0
                lines.append(
                    f"| {m.step_type} | {m.total_calls} | {success_rate:.1%} | "
                    f"{m.avg_latency_ms:.0f}ms | {m.avg_tokens:.0f} |"
                )
            lines.append("")

        # 최적화 제안
        lines.append("## 최적화 제안")
        if proposals:
            for i, p in enumerate(proposals, 1):
                lines.append(f"\n### {i}. {p.target}")
                lines.append(f"- 유형: {p.optimization_type}")
                lines.append(f"- 현재: {p.current_value} → 제안: {p.proposed_value}")
                lines.append(f"- 사유: {p.reason}")
                lines.append(f"- 기대 효과: {p.expected_improvement}")
                lines.append(f"- 신뢰도: {p.confidence:.0%}")
        else:
            lines.append("현재 제안 사항 없음 (성능 양호)")

        return "\n".join(lines)

    def get_stats(self) -> Dict[str, Any]:
        """DSPy 통계."""
        # 최근 7일 호출 수
        cutoff = (datetime.now() - timedelta(days=7)).isoformat()
        row = self.ssot.conn.execute("""
            SELECT COUNT(*) as total, SUM(1-success) as errors
            FROM prompt_metrics WHERE created_at > ?
        """, (cutoff,)).fetchone()

        # 적용된 최적화 수
        opt_row = self.ssot.conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 'applied' THEN 1 ELSE 0 END) as applied,
                SUM(CASE WHEN status = 'proposed' THEN 1 ELSE 0 END) as pending
            FROM dspy_optimizations
        """).fetchone()

        return {
            "calls_7d": row["total"] or 0,
            "errors_7d": row["errors"] or 0,
            "error_rate_7d": round((row["errors"] or 0) / (row["total"] or 1), 3),
            "total_optimizations": opt_row["total"] or 0,
            "applied_optimizations": opt_row["applied"] or 0,
            "pending_proposals": opt_row["pending"] or 0
        }

    def cleanup_old_metrics(self, days: int = 30):
        """오래된 메트릭 정리."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        cursor = self.ssot.conn.execute(
            "DELETE FROM prompt_metrics WHERE created_at < ?",
            (cutoff,)
        )
        deleted = cursor.rowcount
        self.ssot.conn.commit()
        if deleted > 0:
            logger.info(f"[DSPy] Cleaned up {deleted} old metrics")
        return deleted
