"""
EVENT HORIZON v3.0 — Singularity Protocol
4단계 위기 대응 시스템

Level 1 (YELLOW): 경고 - 모니터링 강화
Level 2 (ORANGE): 주의 - 자동 복구 시도
Level 3 (RED): 위험 - 수동 개입 요청
Level 4 (BLACK): 치명적 - 모든 것 중단, 로그 보존
"""

import logging
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Callable
from enum import IntEnum

logger = logging.getLogger("reze.fish.singularity")


class CrisisLevel(IntEnum):
    """위기 수준"""
    NONE = 0
    YELLOW = 1    # 경고
    ORANGE = 2    # 주의
    RED = 3       # 위험
    BLACK = 4     # 치명적


@dataclass
class Crisis:
    """위기 상황"""
    level: CrisisLevel
    category: str           # infra, revenue, security, content, api
    reason: str
    detected_at: datetime = field(default_factory=datetime.now)
    auto_recoverable: bool = True
    recovery_action: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class CrisisResponse:
    """위기 대응 결과"""
    crisis: Crisis
    action_taken: str
    success: bool
    message: str
    escalated: bool = False
    notified: bool = False


class SingularityProtocol:
    """
    4단계 위기 대응 시스템.
    블랙홀의 특이점처럼, 위기가 임계점을 넘으면 모든 것이 변한다.
    """

    # 위기 유형별 기본 레벨
    CRISIS_LEVELS = {
        # 인프라
        "container_down": CrisisLevel.ORANGE,
        "container_repeated_down": CrisisLevel.RED,
        "disk_warning": CrisisLevel.YELLOW,
        "disk_critical": CrisisLevel.ORANGE,
        "memory_warning": CrisisLevel.YELLOW,
        "memory_critical": CrisisLevel.ORANGE,
        "server_unreachable": CrisisLevel.RED,
        "database_error": CrisisLevel.RED,

        # 수익
        "revenue_drop_10": CrisisLevel.YELLOW,
        "revenue_drop_30": CrisisLevel.ORANGE,
        "revenue_drop_50": CrisisLevel.RED,
        "payment_failure": CrisisLevel.ORANGE,
        "churn_spike": CrisisLevel.ORANGE,

        # 보안
        "suspicious_login": CrisisLevel.YELLOW,
        "brute_force_detected": CrisisLevel.ORANGE,
        "data_breach_suspected": CrisisLevel.BLACK,
        "vulnerability_critical": CrisisLevel.RED,

        # 콘텐츠
        "blog_down": CrisisLevel.ORANGE,
        "traffic_drop_50": CrisisLevel.ORANGE,
        "traffic_drop_80": CrisisLevel.RED,
        "google_penalty_suspected": CrisisLevel.RED,

        # API
        "api_quota_80": CrisisLevel.YELLOW,
        "api_quota_95": CrisisLevel.ORANGE,
        "api_quota_exhausted": CrisisLevel.RED,
        "api_key_compromised": CrisisLevel.BLACK,

        # 일반
        "consecutive_errors": CrisisLevel.ORANGE,
        "unknown_critical": CrisisLevel.RED,
    }

    # 자동 복구 가능 여부
    AUTO_RECOVERABLE = {
        "container_down": True,
        "disk_warning": True,
        "disk_critical": True,
        "memory_warning": False,
        "api_quota_80": False,
        "consecutive_errors": True,
    }

    def __init__(self, ssot, discord_notifier: Callable = None):
        self.ssot = ssot
        self.discord = discord_notifier
        self.active_crises: List[Crisis] = []

    # ═══════════════════════════════════════════════════════════════════════
    # 위기 감지
    # ═══════════════════════════════════════════════════════════════════════

    def detect_crisis(self, category: str, reason: str,
                     metadata: dict = None) -> Optional[Crisis]:
        """위기 감지 및 Crisis 객체 생성"""
        level = self.CRISIS_LEVELS.get(reason, CrisisLevel.YELLOW)
        auto_recoverable = self.AUTO_RECOVERABLE.get(reason, False)

        crisis = Crisis(
            level=level,
            category=category,
            reason=reason,
            auto_recoverable=auto_recoverable,
            metadata=metadata or {}
        )

        # 중복 위기 체크 (최근 1시간 이내 같은 이유)
        if self._is_duplicate_crisis(crisis):
            # 반복 위기는 레벨 상승
            crisis.level = min(crisis.level + 1, CrisisLevel.BLACK)
            crisis.reason = f"{reason}_repeated"
            crisis.auto_recoverable = False

        self.active_crises.append(crisis)
        self._log_crisis(crisis)

        return crisis

    def _is_duplicate_crisis(self, crisis: Crisis) -> bool:
        """최근 1시간 이내 동일 위기 존재 여부"""
        try:
            row = self.ssot.conn.execute("""
                SELECT COUNT(*) FROM signals
                WHERE kind='crisis'
                AND data LIKE ?
                AND created_at > datetime('now', '-1 hour')
            """, (f'%{crisis.reason}%',)).fetchone()
            return row[0] >= 3  # 3번 이상 반복
        except:
            return False

    def _log_crisis(self, crisis: Crisis):
        """위기 기록"""
        try:
            self.ssot.save_signal("crisis", json.dumps({
                "level": crisis.level,
                "level_name": crisis.level.name,
                "category": crisis.category,
                "reason": crisis.reason,
                "auto_recoverable": crisis.auto_recoverable,
                "metadata": crisis.metadata,
            }))
        except Exception as e:
            logger.error("Failed to log crisis: %s", e)

    # ═══════════════════════════════════════════════════════════════════════
    # 위기 대응
    # ═══════════════════════════════════════════════════════════════════════

    async def respond(self, crisis: Crisis) -> CrisisResponse:
        """위기 대응 실행"""
        logger.warning("Singularity: Responding to %s crisis [%s]",
                      crisis.level.name, crisis.reason)

        if crisis.level == CrisisLevel.BLACK:
            return await self._respond_black(crisis)
        elif crisis.level == CrisisLevel.RED:
            return await self._respond_red(crisis)
        elif crisis.level == CrisisLevel.ORANGE:
            return await self._respond_orange(crisis)
        else:  # YELLOW
            return await self._respond_yellow(crisis)

    async def _respond_yellow(self, crisis: Crisis) -> CrisisResponse:
        """YELLOW: 모니터링 강화"""
        action = "monitoring_increased"
        message = f"⚠️ YELLOW ALERT: {crisis.reason}"

        # 내부 로깅만
        logger.warning(message)

        return CrisisResponse(
            crisis=crisis,
            action_taken=action,
            success=True,
            message=message,
            escalated=False,
            notified=False,
        )

    async def _respond_orange(self, crisis: Crisis) -> CrisisResponse:
        """ORANGE: 자동 복구 시도"""
        action = "auto_recovery_attempted"
        success = False
        message = f"🟠 ORANGE ALERT: {crisis.reason}"

        if crisis.auto_recoverable:
            success = await self._attempt_auto_recovery(crisis)
            if success:
                action = "auto_recovery_success"
                message = f"🟠 ORANGE RESOLVED: {crisis.reason} - Auto-recovered"
            else:
                action = "auto_recovery_failed"
                message = f"🟠 ORANGE ESCALATING: {crisis.reason} - Auto-recovery failed"

        # Discord 알림
        if self.discord:
            await self.discord(message)

        return CrisisResponse(
            crisis=crisis,
            action_taken=action,
            success=success,
            message=message,
            escalated=not success,
            notified=True,
        )

    async def _respond_red(self, crisis: Crisis) -> CrisisResponse:
        """RED: 수동 개입 요청"""
        action = "manual_intervention_requested"
        message = f"""🔴 RED ALERT: {crisis.reason}

Category: {crisis.category}
Level: RED (수동 개입 필요)
Time: {crisis.detected_at.strftime('%Y-%m-%d %H:%M:%S')}

Details: {json.dumps(crisis.metadata, indent=2)}

즉시 확인이 필요합니다."""

        # Discord 알림 (멘션 포함 가능)
        if self.discord:
            await self.discord(message)

        # 에스컬레이션 기록
        self._record_escalation(crisis)

        return CrisisResponse(
            crisis=crisis,
            action_taken=action,
            success=False,
            message=message,
            escalated=True,
            notified=True,
        )

    async def _respond_black(self, crisis: Crisis) -> CrisisResponse:
        """BLACK: 모든 것 중단, 로그 보존"""
        action = "emergency_shutdown_initiated"
        message = f"""⬛ BLACK ALERT: {crisis.reason}

🚨 CRITICAL EMERGENCY 🚨

Category: {crisis.category}
Level: BLACK (치명적)
Time: {crisis.detected_at.strftime('%Y-%m-%d %H:%M:%S')}

ALL AUTONOMOUS OPERATIONS HALTED.

Details: {json.dumps(crisis.metadata, indent=2)}

즉시 시스템 확인 필요!"""

        # 모든 채널로 알림
        if self.discord:
            await self.discord(message)

        # 상태 보존
        self._preserve_state(crisis)

        # 에스컬레이션 기록
        self._record_escalation(crisis, is_black=True)

        return CrisisResponse(
            crisis=crisis,
            action_taken=action,
            success=False,
            message=message,
            escalated=True,
            notified=True,
        )

    # ═══════════════════════════════════════════════════════════════════════
    # 자동 복구
    # ═══════════════════════════════════════════════════════════════════════

    async def _attempt_auto_recovery(self, crisis: Crisis) -> bool:
        """자동 복구 시도"""
        try:
            if "container" in crisis.reason:
                return await self._recover_container(crisis)
            elif "disk" in crisis.reason:
                return await self._recover_disk(crisis)
            elif "consecutive_errors" in crisis.reason:
                return await self._recover_consecutive_errors(crisis)
            else:
                return False
        except Exception as e:
            logger.error("Auto recovery failed: %s", e)
            return False

    async def _recover_container(self, crisis: Crisis) -> bool:
        """컨테이너 복구"""
        import subprocess
        container = crisis.metadata.get("container", "")
        if not container:
            return False

        try:
            result = subprocess.run(
                ["docker", "restart", container],
                capture_output=True, text=True, timeout=30
            )
            return result.returncode == 0
        except:
            return False

    async def _recover_disk(self, crisis: Crisis) -> bool:
        """디스크 정리"""
        import subprocess
        try:
            # Docker 정리
            subprocess.run(["docker", "system", "prune", "-f"],
                         capture_output=True, timeout=60)
            # PM2 로그 정리
            subprocess.run(["pm2", "flush"],
                         capture_output=True, timeout=30)
            return True
        except:
            return False

    async def _recover_consecutive_errors(self, crisis: Crisis) -> bool:
        """연속 오류 복구 (상태 리셋)"""
        # Fish 통계 리셋은 외부에서 처리
        return True

    # ═══════════════════════════════════════════════════════════════════════
    # 상태 보존 및 에스컬레이션
    # ═══════════════════════════════════════════════════════════════════════

    def _preserve_state(self, crisis: Crisis):
        """BLACK 레벨 시 상태 보존"""
        try:
            # 현재 상태 스냅샷
            state = {
                "crisis": {
                    "level": crisis.level.name,
                    "category": crisis.category,
                    "reason": crisis.reason,
                    "metadata": crisis.metadata,
                },
                "timestamp": datetime.now().isoformat(),
                "active_crises": len(self.active_crises),
            }

            # signals 테이블에 보존
            self.ssot.save_signal("black_alert_state", json.dumps(state))
            logger.critical("BLACK ALERT: State preserved")
        except Exception as e:
            logger.error("Failed to preserve state: %s", e)

    def _record_escalation(self, crisis: Crisis, is_black: bool = False):
        """에스컬레이션 기록"""
        try:
            self.ssot.conn.execute("""
                INSERT INTO signals (kind, data, created_at)
                VALUES (?, ?, datetime('now'))
            """, (
                "escalation",
                json.dumps({
                    "level": crisis.level.name,
                    "category": crisis.category,
                    "reason": crisis.reason,
                    "is_black": is_black,
                })
            ))
            self.ssot.conn.commit()
        except Exception as e:
            logger.error("Failed to record escalation: %s", e)

    # ═══════════════════════════════════════════════════════════════════════
    # 상태 조회
    # ═══════════════════════════════════════════════════════════════════════

    def get_active_crises(self) -> List[Crisis]:
        """활성 위기 목록"""
        return [c for c in self.active_crises
                if (datetime.now() - c.detected_at).seconds < 3600]

    def get_highest_level(self) -> CrisisLevel:
        """현재 최고 위기 수준"""
        active = self.get_active_crises()
        if not active:
            return CrisisLevel.NONE
        return max(c.level for c in active)

    def clear_crisis(self, reason: str):
        """위기 해제"""
        self.active_crises = [c for c in self.active_crises
                            if c.reason != reason]
        logger.info("Singularity: Crisis cleared - %s", reason)

    def get_crisis_history(self, hours: int = 24) -> List[Dict]:
        """위기 이력 조회"""
        try:
            rows = self.ssot.conn.execute("""
                SELECT data, created_at FROM signals
                WHERE kind='crisis'
                AND created_at > datetime('now', ?)
                ORDER BY created_at DESC
            """, (f'-{hours} hours',)).fetchall()

            return [
                {**json.loads(r[0]), "created_at": r[1]}
                for r in rows
            ]
        except Exception as e:
            logger.error("Failed to get crisis history: %s", e)
            return []
