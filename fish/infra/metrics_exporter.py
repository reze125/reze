"""
Prometheus Metrics Exporter — REZE v6.0 SOVEREIGN
진화 시스템 모니터링 메트릭

Prometheus/Grafana 연동을 위한 메트릭 수집 및 노출.
/metrics 엔드포인트로 Prometheus가 스크래핑.
"""

import time
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger("reze.evolve.metrics")

# Prometheus 클라이언트 선택적 import
try:
    from prometheus_client import (
        Counter, Gauge, Histogram,
        generate_latest, CONTENT_TYPE_LATEST
    )
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    logger.warning("prometheus_client not installed, metrics disabled")


if PROMETHEUS_AVAILABLE:
    # ═══════════════════════════════════════════
    # 카운터 (누적 값)
    # ═══════════════════════════════════════════

    HUNT_TOTAL = Counter(
        "reze_hunt_total",
        "Total hunts executed",
        ["niche", "strategy", "status"]
    )

    EVOLUTION_TOTAL = Counter(
        "reze_evolution_total",
        "Evolution actions executed",
        ["module", "action", "result"]
    )

    ERROR_TOTAL = Counter(
        "reze_error_total",
        "Errors encountered",
        ["module", "error_type"]
    )

    APPROVAL_TOTAL = Counter(
        "reze_approval_total",
        "Approval requests",
        ["module", "risk_level", "status"]
    )

    # ═══════════════════════════════════════════
    # 게이지 (현재 값)
    # ═══════════════════════════════════════════

    HEARTBEAT_LAG = Gauge(
        "reze_heartbeat_lag_seconds",
        "Seconds since last heartbeat"
    )

    ACTIVE_SUB_AGENTS = Gauge(
        "reze_active_sub_agents",
        "Number of running sub-agents"
    )

    PENDING_APPROVALS = Gauge(
        "reze_pending_approvals",
        "Pending approval requests"
    )

    METACOG_ACCURACY = Gauge(
        "reze_metacog_accuracy",
        "Metacognitive calibration accuracy",
        ["domain"]
    )

    FISH_ENERGY = Gauge(
        "reze_fish_energy",
        "Current fish energy level"
    )

    DAILY_TOKENS = Gauge(
        "reze_daily_tokens_used",
        "Tokens used today"
    )

    # ═══════════════════════════════════════════
    # 히스토그램 (분포)
    # ═══════════════════════════════════════════

    HUNT_DURATION = Histogram(
        "reze_hunt_duration_seconds",
        "Hunt execution time",
        buckets=[1, 5, 10, 30, 60, 120, 300]
    )

    LLM_LATENCY = Histogram(
        "reze_llm_latency_seconds",
        "LLM API latency",
        ["provider", "purpose"],
        buckets=[0.5, 1, 2, 5, 10, 30]
    )

    SANDBOX_DURATION = Histogram(
        "reze_sandbox_duration_seconds",
        "Sandbox test execution time",
        buckets=[1, 5, 10, 30, 60, 120]
    )


class MetricsCollector:
    """
    메트릭 수집 헬퍼 클래스.
    Prometheus가 없어도 동작 (no-op).
    """

    @staticmethod
    def record_hunt(
        niche: str,
        strategy: str,
        status: str,
        duration: float
    ):
        """사냥 실행 기록"""
        if PROMETHEUS_AVAILABLE:
            HUNT_TOTAL.labels(
                niche=niche,
                strategy=strategy,
                status=status
            ).inc()
            HUNT_DURATION.observe(duration)

    @staticmethod
    def record_evolution(
        module: str,
        action: str,
        result: str
    ):
        """진화 액션 기록"""
        if PROMETHEUS_AVAILABLE:
            EVOLUTION_TOTAL.labels(
                module=module,
                action=action,
                result=result
            ).inc()

    @staticmethod
    def record_error(module: str, error_type: str):
        """에러 기록"""
        if PROMETHEUS_AVAILABLE:
            ERROR_TOTAL.labels(
                module=module,
                error_type=error_type
            ).inc()

    @staticmethod
    def record_approval(
        module: str,
        risk_level: str,
        status: str
    ):
        """승인 요청 기록"""
        if PROMETHEUS_AVAILABLE:
            APPROVAL_TOTAL.labels(
                module=module,
                risk_level=risk_level,
                status=status
            ).inc()

    @staticmethod
    def record_llm_call(
        provider: str,
        purpose: str,
        latency: float
    ):
        """LLM 호출 기록"""
        if PROMETHEUS_AVAILABLE:
            LLM_LATENCY.labels(
                provider=provider,
                purpose=purpose
            ).observe(latency)

    @staticmethod
    def record_sandbox(duration: float):
        """샌드박스 실행 기록"""
        if PROMETHEUS_AVAILABLE:
            SANDBOX_DURATION.observe(duration)

    @staticmethod
    def update_heartbeat_lag(seconds: float):
        """하트비트 지연 업데이트"""
        if PROMETHEUS_AVAILABLE:
            HEARTBEAT_LAG.set(seconds)

    @staticmethod
    def update_active_sub_agents(count: int):
        """활성 서브에이전트 수 업데이트"""
        if PROMETHEUS_AVAILABLE:
            ACTIVE_SUB_AGENTS.set(count)

    @staticmethod
    def update_pending_approvals(count: int):
        """대기 중 승인 수 업데이트"""
        if PROMETHEUS_AVAILABLE:
            PENDING_APPROVALS.set(count)

    @staticmethod
    def update_metacog_accuracy(domain: str, accuracy: float):
        """메타인지 정확도 업데이트"""
        if PROMETHEUS_AVAILABLE:
            METACOG_ACCURACY.labels(domain=domain).set(accuracy)

    @staticmethod
    def update_fish_energy(energy: float):
        """물고기 에너지 업데이트"""
        if PROMETHEUS_AVAILABLE:
            FISH_ENERGY.set(energy)

    @staticmethod
    def update_daily_tokens(tokens: int):
        """일일 토큰 사용량 업데이트"""
        if PROMETHEUS_AVAILABLE:
            DAILY_TOKENS.set(tokens)


def get_metrics() -> bytes:
    """Prometheus 형식 메트릭 반환"""
    if PROMETHEUS_AVAILABLE:
        return generate_latest()
    return b"# Prometheus client not installed\n"


def get_content_type() -> str:
    """메트릭 Content-Type 반환"""
    if PROMETHEUS_AVAILABLE:
        return CONTENT_TYPE_LATEST
    return "text/plain"


# FastAPI 라우터 (선택적)
def create_metrics_router():
    """FastAPI 메트릭 라우터 생성"""
    try:
        from fastapi import APIRouter
        from fastapi.responses import Response

        router = APIRouter()

        @router.get("/metrics")
        async def metrics():
            """Prometheus 메트릭 엔드포인트"""
            return Response(
                content=get_metrics(),
                media_type=get_content_type()
            )

        return router
    except ImportError:
        logger.warning("FastAPI not available for metrics router")
        return None


# ═══════════════════════════════════════════
# DB 기반 메트릭 (Prometheus 없이도 동작)
# ═══════════════════════════════════════════

class DBMetrics:
    """SQLite 기반 메트릭 저장 (Prometheus 대안)"""

    def __init__(self, ssot):
        self.conn = ssot.conn if hasattr(ssot, 'conn') else ssot
        self._ensure_table()

    def _ensure_table(self):
        """메트릭 테이블 생성"""
        try:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS metrics_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    metric_name TEXT NOT NULL,
                    metric_value REAL NOT NULL,
                    labels TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            self.conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_metrics_name
                ON metrics_log(metric_name, created_at)
            """)
            self.conn.commit()
        except:
            pass

    def record(
        self,
        name: str,
        value: float,
        labels: dict = None
    ):
        """메트릭 기록"""
        import json
        try:
            self.conn.execute("""
                INSERT INTO metrics_log (metric_name, metric_value, labels, created_at)
                VALUES (?, ?, ?, ?)
            """, (
                name, value,
                json.dumps(labels or {}),
                datetime.utcnow().isoformat()
            ))
            self.conn.commit()
        except Exception as e:
            logger.error("Failed to record metric: %s", e)

    def get_recent(
        self,
        name: str,
        limit: int = 100
    ) -> list:
        """최근 메트릭 조회"""
        import json
        try:
            rows = self.conn.execute("""
                SELECT metric_value, labels, created_at
                FROM metrics_log
                WHERE metric_name = ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (name, limit)).fetchall()
            return [
                {
                    "value": r[0],
                    "labels": json.loads(r[1] or "{}"),
                    "timestamp": r[2]
                }
                for r in rows
            ]
        except:
            return []

    def cleanup_old(self, days: int = 7):
        """오래된 메트릭 정리"""
        try:
            self.conn.execute("""
                DELETE FROM metrics_log
                WHERE created_at < datetime('now', ?)
            """, (f'-{days} days',))
            self.conn.commit()
        except:
            pass
