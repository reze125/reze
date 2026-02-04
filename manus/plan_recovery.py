"""Manus Plan Recovery - 중단된 계획 복구 및 재주입."""
import json
import uuid
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from enum import Enum

import logging
logger = logging.getLogger("REZE.manus")

# 순환 import 방지
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from manus.failure_tracker import FailureRecord


class RecoveryStrategy(Enum):
    """복구 전략."""
    RESUME = "resume"           # 중단 지점부터 재개
    RETRY_STEP = "retry_step"   # 현재 단계 재시도
    SKIP_STEP = "skip_step"     # 현재 단계 건너뛰기
    REPLAN = "replan"           # 전체 재계획


@dataclass
class RecoveryPlan:
    """복구 계획."""
    original_task_id: str
    recovery_id: str
    strategy: RecoveryStrategy
    resume_from_step: int
    modified_steps: List[Dict[str, Any]]
    failure_context: Dict[str, Any]
    created_at: str


class PlanRecovery:
    """계획 복구 및 재주입 관리."""

    STALE_THRESHOLD_MINUTES = 30  # 30분 이상 running이면 stale

    def __init__(self, ssot, planner=None):
        """
        Args:
            ssot: SSOT 인스턴스
            planner: UniversalPlanner 인스턴스 (선택)
        """
        self.ssot = ssot
        self.planner = planner

    async def detect_interrupted(self) -> List[Dict[str, Any]]:
        """
        중단된 태스크 탐지.

        Returns:
            중단된 태스크 목록
        """
        threshold = (datetime.now() - timedelta(minutes=self.STALE_THRESHOLD_MINUTES)).isoformat()

        # running 상태지만 오래된 daemon_tasks
        rows = self.ssot.conn.execute('''
            SELECT id, task_spec, status, started_at
            FROM daemon_tasks
            WHERE status = 'running'
              AND started_at < ?
              AND started_at != ''
            ORDER BY started_at DESC
            LIMIT 20
        ''', (threshold,)).fetchall()

        interrupted = []
        for row in rows:
            # 체크포인트 확인
            checkpoint = self.get_checkpoint(row[0])
            interrupted.append({
                "task_id": row[0],
                "task_spec": row[1][:100] if row[1] else "",
                "status": row[2],
                "started_at": row[3],
                "last_checkpoint": checkpoint
            })

        return interrupted

    async def create_recovery_plan(
        self,
        task_id: str,
        failure: "FailureRecord" = None,
        strategy: RecoveryStrategy = None
    ) -> Optional[RecoveryPlan]:
        """
        복구 계획 생성.

        Args:
            task_id: 원본 태스크 ID
            failure: 실패 기록 (선택)
            strategy: 복구 전략 (지정하지 않으면 자동 선택)

        Returns:
            RecoveryPlan (생성 불가 시 None)
        """
        # 기존 계획 조회
        cached_plan = self._get_cached_plan(task_id)
        if not cached_plan:
            logger.warning(f"[RECOVERY] No cached plan for task {task_id}")
            return None

        # 마지막 체크포인트
        checkpoint = self.get_checkpoint(task_id)
        resume_step = checkpoint["step_number"] if checkpoint else 0

        # 전략 자동 선택
        if not strategy:
            strategy = self._select_strategy(failure, checkpoint)

        # 복구 계획 생성
        recovery_id = str(uuid.uuid4())[:12]
        modified_steps = self._modify_steps(cached_plan, resume_step, strategy)

        recovery = RecoveryPlan(
            original_task_id=task_id,
            recovery_id=recovery_id,
            strategy=strategy,
            resume_from_step=resume_step,
            modified_steps=modified_steps,
            failure_context={
                "failure_type": failure.failure_type.value if failure else None,
                "error_message": failure.error_message[:500] if failure else None,
                "tool_name": failure.tool_name if failure else None
            },
            created_at=datetime.now().isoformat()
        )

        logger.info(f"[RECOVERY] Created recovery plan {recovery_id} for task {task_id} "
                   f"using strategy {strategy.value}, resume from step {resume_step}")

        return recovery

    async def inject_plan(self, recovery: RecoveryPlan) -> str:
        """
        복구 계획 주입 및 새 태스크 생성.

        Args:
            recovery: 복구 계획

        Returns:
            새 태스크 ID
        """
        new_task_id = f"recovery_{recovery.recovery_id}"

        # 새 계획으로 캐시 저장
        if recovery.modified_steps:
            self.ssot.conn.execute('''
                INSERT OR REPLACE INTO plan_cache_v4
                (task_id, plan_json, steps_completed, created_at)
                VALUES (?, ?, ?, ?)
            ''', (
                new_task_id,
                json.dumps(recovery.modified_steps, ensure_ascii=False),
                recovery.resume_from_step,
                datetime.now().isoformat()
            ))
            self.ssot.conn.commit()

        logger.info(f"[RECOVERY] Injected recovery plan as task {new_task_id}")
        return new_task_id

    def save_checkpoint(self, task_id: str, step: int, state: Dict[str, Any]):
        """
        체크포인트 저장.

        Args:
            task_id: 태스크 ID
            step: 완료된 단계 번호
            state: 현재 상태 (messages, results 등)
        """
        self.ssot.conn.execute('''
            INSERT OR REPLACE INTO checkpoints_v6
            (task_id, step_number, state_json, created_at)
            VALUES (?, ?, ?, ?)
        ''', (
            task_id,
            step,
            json.dumps(state, ensure_ascii=False)[:50000],  # 50KB 제한
            datetime.now().isoformat()
        ))
        self.ssot.conn.commit()
        logger.debug(f"[CHECKPOINT] Saved step {step} for task {task_id}")

    def get_checkpoint(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        마지막 체크포인트 조회.

        Args:
            task_id: 태스크 ID

        Returns:
            체크포인트 정보 (없으면 None)
        """
        row = self.ssot.conn.execute('''
            SELECT step_number, state_json, created_at
            FROM checkpoints_v6
            WHERE task_id = ?
            ORDER BY step_number DESC
            LIMIT 1
        ''', (task_id,)).fetchone()

        if row:
            return {
                "step_number": row[0],
                "state": json.loads(row[1]) if row[1] else {},
                "saved_at": row[2]
            }
        return None

    def _get_cached_plan(self, task_id: str) -> Optional[List[Dict]]:
        """캐시된 계획 조회."""
        row = self.ssot.conn.execute('''
            SELECT plan_json FROM plan_cache_v4
            WHERE task_id = ?
            ORDER BY created_at DESC
            LIMIT 1
        ''', (task_id,)).fetchone()

        if row and row[0]:
            try:
                return json.loads(row[0])
            except:
                return None
        return None

    def _select_strategy(
        self,
        failure: "FailureRecord" = None,
        checkpoint: Dict = None
    ) -> RecoveryStrategy:
        """실패 유형에 따른 전략 자동 선택."""
        if not failure:
            return RecoveryStrategy.RESUME

        from manus.failure_tracker import FailureType

        # 권한 문제 → 건너뛰기
        if failure.failure_type == FailureType.PERMISSION:
            return RecoveryStrategy.SKIP_STEP

        # 타임아웃 → 재시도
        if failure.failure_type == FailureType.TIMEOUT:
            return RecoveryStrategy.RETRY_STEP

        # 도구 에러 → 재시도 (3회 미만)
        if failure.failure_type == FailureType.TOOL_ERROR:
            # 동일 단계 실패 횟수 확인
            count = self.ssot.conn.execute('''
                SELECT COUNT(*) FROM failures_v6
                WHERE task_id = ? AND step_number = ?
            ''', (failure.task_id, failure.step_number)).fetchone()[0]

            if count < 3:
                return RecoveryStrategy.RETRY_STEP
            else:
                return RecoveryStrategy.SKIP_STEP

        # LLM 에러 → 재계획
        if failure.failure_type == FailureType.LLM_ERROR:
            return RecoveryStrategy.REPLAN

        # 기본: 재개
        return RecoveryStrategy.RESUME

    def _modify_steps(
        self,
        original_steps: List[Dict],
        resume_from: int,
        strategy: RecoveryStrategy
    ) -> List[Dict]:
        """전략에 따라 단계 수정."""
        if strategy == RecoveryStrategy.RESUME:
            # resume_from 이후 단계만 반환
            return original_steps[resume_from:]

        elif strategy == RecoveryStrategy.RETRY_STEP:
            # resume_from 포함하여 반환
            return original_steps[max(0, resume_from - 1):]

        elif strategy == RecoveryStrategy.SKIP_STEP:
            # resume_from 건너뛰고 다음부터
            return original_steps[resume_from + 1:]

        elif strategy == RecoveryStrategy.REPLAN:
            # 전체 반환 (재계획 시 planner가 새로 생성)
            return []

        return original_steps
