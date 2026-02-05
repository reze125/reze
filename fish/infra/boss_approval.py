"""
Boss Approval Gate — REZE v6.0 SOVEREIGN
위험도 기반 승인 시스템

- LOW → 자동 승인, 로그만
- MEDIUM → 자동 승인, 알림 발송
- HIGH → 보스 승인 대기
- CRITICAL → 즉시 중단, 보스 알림
"""

import json
import logging
from datetime import datetime
from enum import Enum
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("reze.evolve.approval")


class RiskLevel(Enum):
    """위험도 레벨"""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


# 모듈별 기본 위험도
MODULE_RISK = {
    "self_code": RiskLevel.HIGH,
    "tool_discovery": RiskLevel.MEDIUM,
    "self_play": RiskLevel.LOW,
    "world_model": RiskLevel.LOW,
    "sub_agent": RiskLevel.MEDIUM,
    "metacognition": RiskLevel.LOW,
    "curiosity": RiskLevel.LOW,
    "evo_coding": RiskLevel.MEDIUM,
    "self_healing": RiskLevel.HIGH,
    "lifelong": RiskLevel.LOW,
}

# 특정 액션의 위험도 오버라이드
ACTION_RISK_OVERRIDE = {
    "modify_fish_py": RiskLevel.CRITICAL,
    "modify_db_schema": RiskLevel.CRITICAL,
    "delete_file": RiskLevel.CRITICAL,
    "add_new_file": RiskLevel.HIGH,
    "modify_prompt": RiskLevel.MEDIUM,
    "register_tool": RiskLevel.MEDIUM,
    "adjust_schedule": RiskLevel.MEDIUM,
    "log_metric": RiskLevel.LOW,
    "record_experience": RiskLevel.LOW,
    "patch": RiskLevel.HIGH,
}


@dataclass
class ApprovalRequest:
    """승인 요청 결과"""
    request_id: str
    status: str  # pending, approved, rejected, auto_approved
    risk_level: RiskLevel


class BossApproval:
    """
    보스 승인 게이트.
    위험도에 따라 자동 승인 또는 보스 승인 대기.
    """

    def __init__(self, ssot):
        """
        Args:
            ssot: SSOT 인스턴스 (conn 속성 필요)
        """
        self.ssot = ssot
        self.conn = ssot.conn if hasattr(ssot, 'conn') else ssot

    def assess_risk(self, module: str, action: str) -> RiskLevel:
        """모듈과 액션에 따른 위험도 평가"""
        # 액션 오버라이드 우선
        if action in ACTION_RISK_OVERRIDE:
            return ACTION_RISK_OVERRIDE[action]
        # 모듈 기본 위험도
        return MODULE_RISK.get(module, RiskLevel.HIGH)

    def request_approval(
        self,
        module: str,
        action: str,
        description: str,
        payload: dict = None
    ) -> ApprovalRequest:
        """
        승인 요청 생성.

        Returns:
            ApprovalRequest with status:
            - auto_approved: LOW/MEDIUM 자동 승인
            - pending: HIGH 이상, 보스 승인 대기
        """
        risk = self.assess_risk(module, action)
        ts = datetime.utcnow()
        req_id = f"apr_{module}_{ts.strftime('%Y%m%d_%H%M%S')}"

        # LOW/MEDIUM은 자동 승인
        if risk in (RiskLevel.LOW, RiskLevel.MEDIUM):
            status = "auto_approved"
        else:
            status = "pending"

        try:
            self.conn.execute("""
                INSERT INTO approval_requests
                (request_id, module, action, risk_level, description,
                 payload, status, created_at, resolved_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                req_id, module, action, risk.value, description,
                json.dumps(payload or {}, default=str),
                status, ts.isoformat(),
                ts.isoformat() if status == "auto_approved" else None
            ))

            # MEDIUM 이상은 알림 생성
            if risk in (RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL):
                urgent = 1 if risk in (RiskLevel.HIGH, RiskLevel.CRITICAL) else 0
                self.conn.execute("""
                    INSERT INTO boss_notifications
                    (request_id, module, action, risk_level, description,
                     urgent, created_at, read)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 0)
                """, (
                    req_id, module, action, risk.value,
                    description, urgent, ts.isoformat()
                ))

            self.conn.commit()

            logger.info(
                "Approval: %s %s/%s [%s] -> %s",
                req_id, module, action, risk.value, status
            )

        except Exception as e:
            logger.error("Failed to create approval request: %s", e)
            # 에러 시에도 요청 객체 반환 (상태는 pending으로)
            return ApprovalRequest(req_id, "pending", risk)

        return ApprovalRequest(req_id, status, risk)

    def is_approved(self, request_id: str) -> bool:
        """요청이 승인되었는지 확인"""
        try:
            row = self.conn.execute(
                "SELECT status FROM approval_requests WHERE request_id = ?",
                (request_id,)
            ).fetchone()
            if row:
                return row[0] in ("approved", "auto_approved")
        except Exception as e:
            logger.error("Failed to check approval status: %s", e)
        return False

    def boss_approve(self, request_id: str, note: str = "") -> bool:
        """보스가 요청 승인"""
        try:
            self.conn.execute("""
                UPDATE approval_requests
                SET status='approved', resolved_at=?, boss_note=?
                WHERE request_id=?
            """, (datetime.utcnow().isoformat(), note, request_id))
            self.conn.commit()
            logger.info("Approval: %s APPROVED by boss", request_id)
            return True
        except Exception as e:
            logger.error("Failed to approve request: %s", e)
            return False

    def boss_reject(self, request_id: str, note: str = "") -> bool:
        """보스가 요청 거부"""
        try:
            self.conn.execute("""
                UPDATE approval_requests
                SET status='rejected', resolved_at=?, boss_note=?
                WHERE request_id=?
            """, (datetime.utcnow().isoformat(), note, request_id))
            self.conn.commit()
            logger.info("Approval: %s REJECTED by boss", request_id)
            return True
        except Exception as e:
            logger.error("Failed to reject request: %s", e)
            return False

    def get_pending(self) -> list:
        """대기 중인 승인 요청 목록"""
        try:
            rows = self.conn.execute("""
                SELECT request_id, module, action, risk_level,
                       description, payload, created_at
                FROM approval_requests
                WHERE status='pending'
                ORDER BY
                    CASE risk_level
                        WHEN 'CRITICAL' THEN 0
                        WHEN 'HIGH' THEN 1
                        WHEN 'MEDIUM' THEN 2
                        ELSE 3
                    END,
                    created_at ASC
            """).fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error("Failed to get pending approvals: %s", e)
            return []

    def get_unread_notifications(self) -> list:
        """읽지 않은 알림 목록"""
        try:
            rows = self.conn.execute("""
                SELECT request_id, module, action, risk_level,
                       description, urgent, created_at
                FROM boss_notifications
                WHERE read = 0
                ORDER BY urgent DESC, created_at DESC
            """).fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error("Failed to get notifications: %s", e)
            return []

    def mark_notification_read(self, request_id: str) -> bool:
        """알림을 읽음으로 표시"""
        try:
            self.conn.execute("""
                UPDATE boss_notifications
                SET read = 1, read_at = ?
                WHERE request_id = ?
            """, (datetime.utcnow().isoformat(), request_id))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error("Failed to mark notification read: %s", e)
            return False

    def get_recent_approvals(self, limit: int = 20) -> list:
        """최근 승인 기록"""
        try:
            rows = self.conn.execute("""
                SELECT request_id, module, action, risk_level,
                       status, created_at, resolved_at, boss_note
                FROM approval_requests
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,)).fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error("Failed to get recent approvals: %s", e)
            return []
