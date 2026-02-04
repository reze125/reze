"""Manus Failure Tracker - 실패 로그 영구 보존 및 패턴 분석."""
import json
import uuid
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from typing import Optional, List, Dict, Any
from enum import Enum

import logging
logger = logging.getLogger("REZE.manus")


class FailureType(Enum):
    """실패 유형 분류."""
    TOOL_ERROR = "tool_error"
    LLM_ERROR = "llm_error"
    TIMEOUT = "timeout"
    VALIDATION = "validation"
    PERMISSION = "permission"
    NETWORK = "network"
    UNKNOWN = "unknown"


@dataclass
class FailureRecord:
    """실패 기록."""
    failure_id: str
    task_id: str
    failure_type: FailureType
    step_number: int
    tool_name: Optional[str]
    error_message: str
    stack_trace: Optional[str]
    context: Dict[str, Any]
    timestamp: str
    recovered: bool = False
    recovery_method: Optional[str] = None


class FailureTracker:
    """실패 로그 관리 및 패턴 분석."""

    def __init__(self, ssot):
        """
        Args:
            ssot: SSOT 인스턴스
        """
        self.ssot = ssot

    def record(
        self,
        task_id: str,
        failure_type: FailureType,
        step: int,
        error: str,
        tool_name: str = None,
        stack_trace: str = None,
        context: Dict[str, Any] = None
    ) -> str:
        """
        실패 기록 저장.

        Args:
            task_id: 태스크 ID
            failure_type: 실패 유형
            step: 실패 발생 단계
            error: 에러 메시지
            tool_name: 실패한 도구 이름 (선택)
            stack_trace: 스택 트레이스 (선택)
            context: 추가 컨텍스트 (선택)

        Returns:
            failure_id
        """
        failure_id = str(uuid.uuid4())[:12]
        timestamp = datetime.now().isoformat()

        self.ssot.conn.execute('''
            INSERT INTO failures_v6
            (failure_id, task_id, failure_type, step_number, tool_name,
             error_message, stack_trace, context_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            failure_id,
            task_id,
            failure_type.value,
            step,
            tool_name,
            error[:2000],  # 길이 제한
            stack_trace[:5000] if stack_trace else None,
            json.dumps(context or {}, ensure_ascii=False),
            timestamp
        ))
        self.ssot.conn.commit()

        logger.info(f"[FAILURE] Recorded {failure_type.value} for task {task_id}: {error[:100]}")

        # 교훈 추출 (Reflexion 연동)
        try:
            from manus.reflexion import ReflexionEngine
            reflexion = ReflexionEngine(ssot=self.ssot)
            reflexion.extract_lesson(
                failure_id=failure_id,
                task_id=task_id,
                failure_type=failure_type.value,
                tool_name=tool_name,
                error_message=error,
                context=context or {},
                recovery_action=None
            )
        except Exception as e:
            logger.warning(f"[FailureTracker] Lesson extraction failed: {e}")

        return failure_id

    def mark_recovered(self, failure_id: str, method: str) -> bool:
        """
        복구 완료 표시.

        Args:
            failure_id: 실패 ID
            method: 복구 방법 (resume, retry, skip, replan)

        Returns:
            성공 여부
        """
        cursor = self.ssot.conn.execute('''
            UPDATE failures_v6
            SET recovered = 1, recovery_method = ?
            WHERE failure_id = ?
        ''', (method, failure_id))
        self.ssot.conn.commit()
        return cursor.rowcount > 0

    def get_task_failures(self, task_id: str) -> List[FailureRecord]:
        """
        태스크별 실패 이력 조회.

        Args:
            task_id: 태스크 ID

        Returns:
            FailureRecord 리스트
        """
        rows = self.ssot.conn.execute('''
            SELECT failure_id, task_id, failure_type, step_number, tool_name,
                   error_message, stack_trace, context_json, created_at,
                   recovered, recovery_method
            FROM failures_v6
            WHERE task_id = ?
            ORDER BY created_at DESC
        ''', (task_id,)).fetchall()

        return [self._row_to_record(row) for row in rows]

    def get_recent_failures(self, hours: int = 24, limit: int = 100) -> List[FailureRecord]:
        """
        최근 실패 조회.

        Args:
            hours: 시간 범위
            limit: 최대 개수

        Returns:
            FailureRecord 리스트
        """
        since = (datetime.now() - timedelta(hours=hours)).isoformat()
        rows = self.ssot.conn.execute('''
            SELECT failure_id, task_id, failure_type, step_number, tool_name,
                   error_message, stack_trace, context_json, created_at,
                   recovered, recovery_method
            FROM failures_v6
            WHERE created_at > ?
            ORDER BY created_at DESC
            LIMIT ?
        ''', (since, limit)).fetchall()

        return [self._row_to_record(row) for row in rows]

    def analyze_patterns(self, hours: int = 24) -> Dict[str, Any]:
        """
        실패 패턴 분석.

        Args:
            hours: 분석 시간 범위

        Returns:
            패턴 분석 결과
        """
        since = (datetime.now() - timedelta(hours=hours)).isoformat()

        # 유형별 통계
        type_stats = self.ssot.conn.execute('''
            SELECT failure_type, COUNT(*) as cnt
            FROM failures_v6
            WHERE created_at > ?
            GROUP BY failure_type
            ORDER BY cnt DESC
        ''', (since,)).fetchall()

        # 도구별 통계
        tool_stats = self.ssot.conn.execute('''
            SELECT tool_name, COUNT(*) as cnt
            FROM failures_v6
            WHERE created_at > ? AND tool_name IS NOT NULL
            GROUP BY tool_name
            ORDER BY cnt DESC
            LIMIT 10
        ''', (since,)).fetchall()

        # 복구율
        recovery_stats = self.ssot.conn.execute('''
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN recovered = 1 THEN 1 ELSE 0 END) as recovered
            FROM failures_v6
            WHERE created_at > ?
        ''', (since,)).fetchone()

        # 시간대별 분포
        hourly_dist = self.ssot.conn.execute('''
            SELECT strftime('%H', created_at) as hour, COUNT(*) as cnt
            FROM failures_v6
            WHERE created_at > ?
            GROUP BY hour
            ORDER BY hour
        ''', (since,)).fetchall()

        total = recovery_stats[0] or 0
        recovered = recovery_stats[1] or 0

        return {
            "hours": hours,
            "total_failures": total,
            "recovered": recovered,
            "recovery_rate": round(recovered / total * 100, 1) if total > 0 else 0,
            "by_type": {row[0]: row[1] for row in type_stats},
            "by_tool": {row[0]: row[1] for row in tool_stats},
            "hourly_distribution": {row[0]: row[1] for row in hourly_dist}
        }

    def get_recovery_hint(self, failure: FailureRecord) -> Optional[str]:
        """
        유사 실패의 복구 방법 제안.

        Args:
            failure: 실패 기록

        Returns:
            복구 힌트 (있으면)
        """
        # 동일 유형 + 동일 도구의 복구 성공 사례 찾기
        rows = self.ssot.conn.execute('''
            SELECT recovery_method, COUNT(*) as cnt
            FROM failures_v6
            WHERE failure_type = ?
              AND (tool_name = ? OR (tool_name IS NULL AND ? IS NULL))
              AND recovered = 1
              AND recovery_method IS NOT NULL
            GROUP BY recovery_method
            ORDER BY cnt DESC
            LIMIT 1
        ''', (failure.failure_type.value, failure.tool_name, failure.tool_name)).fetchone()

        if rows:
            return f"Suggested recovery: {rows[0]} (used {rows[1]} times)"
        return None

    def _row_to_record(self, row) -> FailureRecord:
        """DB row → FailureRecord 변환."""
        return FailureRecord(
            failure_id=row[0],
            task_id=row[1],
            failure_type=FailureType(row[2]),
            step_number=row[3],
            tool_name=row[4],
            error_message=row[5],
            stack_trace=row[6],
            context=json.loads(row[7]) if row[7] else {},
            timestamp=row[8],
            recovered=bool(row[9]),
            recovery_method=row[10]
        )
