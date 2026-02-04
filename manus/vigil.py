"""VIGIL - 에이전트 안전장치.

1. Kill Switch: 비상 정지
2. 핵심 파일 보호: reze_core.py, ssot.py, config.py
3. 위험 코드 탐지: 파괴적 패턴 차단
4. 감사 로그: 모든 민감 작업 기록
"""
import logging
import re
import json
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

logger = logging.getLogger("REZE.vigil")


class VigilAction(Enum):
    BLOCKED = "blocked"
    ALLOWED = "allowed"
    WARNING = "warning"


@dataclass
class VigilResult:
    """VIGIL 검사 결과."""
    allowed: bool
    action: VigilAction
    reason: str = ""
    warnings: List[str] = field(default_factory=list)


class VIGIL:
    """에이전트 안전장치."""

    # Kill Switch 경로
    KILL_SWITCH_PATH = Path.home() / ".reze" / "KILL_SWITCH"

    # 핵심 파일 (절대 보호)
    CRITICAL_FILES = frozenset({
        "reze_core.py",
        "ssot.py",
        "config.py",
        "reze_permissions.py",
    })

    # 핵심 디렉토리
    CRITICAL_DIRS = frozenset({
        "manus",
    })

    # 위험 코드 패턴
    DANGEROUS_CODE_PATTERNS = [
        # DB 파괴
        (r"DROP\s+TABLE", "DROP TABLE 감지"),
        (r"DELETE\s+FROM\s+\w+\s*;?\s*$", "WHERE 없는 DELETE"),
        (r"TRUNCATE\s+TABLE", "TRUNCATE TABLE 감지"),

        # 파일 파괴
        (r"shutil\.rmtree\s*\(", "재귀 삭제 감지"),
        (r"\.unlink\s*\(\s*\)", "파일 삭제 감지"),
        (r"os\.remove\s*\(", "파일 삭제 감지"),

        # 시스템 명령 (shell injection 위험)
        (r"subprocess\..*shell\s*=\s*True", "shell=True 감지"),
        (r"os\.system\s*\(", "os.system 감지"),

        # 보안 우회 시도
        (r"VIGIL\s*=\s*False", "VIGIL 비활성화 시도"),
        (r"kill_switch\s*=\s*False", "Kill Switch 비활성화 시도"),
        (r"CRITICAL_FILES\s*=\s*\[\s*\]", "CRITICAL_FILES 초기화 시도"),
    ]

    # 위험 shell 명령
    DANGEROUS_SHELL_PATTERNS = [
        (r"rm\s+-rf\s+/", "루트 삭제 시도"),
        (r"rm\s+-rf\s+\*", "와일드카드 삭제"),
        (r">\s*/dev/sd", "디스크 직접 쓰기"),
        (r"mkfs\s+", "파일시스템 포맷"),
        (r"dd\s+if=.*of=/dev", "디스크 덮어쓰기"),
    ]

    def __init__(self, ssot=None, enabled: bool = True):
        self.ssot = ssot
        self.enabled = enabled
        self._kill_switch_active = None

    # === Kill Switch ===

    def check_kill_switch(self) -> bool:
        """Kill Switch 상태 확인. True면 활성화됨."""
        if self._kill_switch_active is not None:
            return self._kill_switch_active
        return self.KILL_SWITCH_PATH.exists()

    def activate_kill_switch(self, reason: str = "Manual activation"):
        """Kill Switch 활성화."""
        self.KILL_SWITCH_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.KILL_SWITCH_PATH.write_text(f"{reason}\n{datetime.now().isoformat()}")
        self._kill_switch_active = True
        self._audit("kill_switch", "KILL_SWITCH", VigilAction.BLOCKED, reason)
        logger.critical(f"[VIGIL] Kill switch ACTIVATED: {reason}")

    def deactivate_kill_switch(self):
        """Kill Switch 비활성화 (주인만 가능)."""
        if self.KILL_SWITCH_PATH.exists():
            self.KILL_SWITCH_PATH.unlink()
        self._kill_switch_active = False
        self._audit("kill_switch", "KILL_SWITCH", VigilAction.ALLOWED, "Deactivated")
        logger.info("[VIGIL] Kill switch deactivated")

    # === 파일 보호 ===

    def is_critical_file(self, path: str) -> bool:
        """핵심 파일인지 확인."""
        try:
            p = Path(path).resolve()
            # 파일명 체크
            if p.name in self.CRITICAL_FILES:
                return True
            # 디렉토리 체크
            for part in p.parts:
                if part in self.CRITICAL_DIRS:
                    return True
            return False
        except Exception:
            return False

    def check_file_access(
        self,
        path: str,
        operation: str,
        source: str = "unknown"
    ) -> VigilResult:
        """파일 접근 검사."""
        if not self.enabled:
            return VigilResult(True, VigilAction.ALLOWED)

        # Kill Switch 체크
        if self.check_kill_switch():
            self._audit("file_access", path, VigilAction.BLOCKED, "Kill switch active", source)
            return VigilResult(False, VigilAction.BLOCKED, "Kill switch active")

        # 읽기는 허용
        if operation in ("read", "list"):
            return VigilResult(True, VigilAction.ALLOWED)

        # 쓰기/삭제 시 핵심 파일 체크
        if self.is_critical_file(path):
            reason = f"Critical file protection: {Path(path).name}"
            self._audit("file_access", path, VigilAction.BLOCKED, reason, source)
            logger.warning(f"[VIGIL] BLOCKED: {operation} on critical file {path}")
            return VigilResult(False, VigilAction.BLOCKED, reason)

        self._audit("file_access", path, VigilAction.ALLOWED, operation, source)
        return VigilResult(True, VigilAction.ALLOWED)

    # === 코드 검사 ===

    def check_code(
        self,
        code: str,
        code_type: str = "python",
        source: str = "unknown"
    ) -> VigilResult:
        """코드 위험성 검사."""
        if not self.enabled:
            return VigilResult(True, VigilAction.ALLOWED)

        # Kill Switch 체크
        if self.check_kill_switch():
            return VigilResult(False, VigilAction.BLOCKED, "Kill switch active")

        warnings = []
        patterns = self.DANGEROUS_CODE_PATTERNS
        if code_type == "shell":
            patterns = self.DANGEROUS_SHELL_PATTERNS + patterns

        for pattern, description in patterns:
            if re.search(pattern, code, re.IGNORECASE | re.MULTILINE):
                reason = f"Dangerous pattern: {description}"
                self._audit("code_execution", code[:100], VigilAction.BLOCKED, reason, source)
                logger.warning(f"[VIGIL] BLOCKED: {description} in {code_type} code")
                return VigilResult(False, VigilAction.BLOCKED, reason)

        # 경고 패턴 (차단하지는 않음)
        warning_patterns = [
            (r"exec\s*\(", "exec() 사용"),
            (r"eval\s*\(", "eval() 사용"),
            (r"__import__", "동적 import"),
        ]
        for pattern, description in warning_patterns:
            if re.search(pattern, code, re.IGNORECASE):
                warnings.append(description)

        if warnings:
            self._audit("code_execution", code[:100], VigilAction.WARNING,
                       f"Warnings: {', '.join(warnings)}", source)
            return VigilResult(True, VigilAction.WARNING, warnings=warnings)

        return VigilResult(True, VigilAction.ALLOWED)

    def check_file_content(
        self,
        path: str,
        content: str,
        source: str = "unknown"
    ) -> VigilResult:
        """파일에 쓸 내용 검사."""
        if not self.enabled:
            return VigilResult(True, VigilAction.ALLOWED)

        # 핵심 파일 체크
        file_check = self.check_file_access(path, "write", source)
        if not file_check.allowed:
            return file_check

        # Python 파일인 경우 코드 검사
        if path.endswith(".py"):
            return self.check_code(content, "python", source)

        # Shell 스크립트인 경우
        if path.endswith(".sh") or content.startswith("#!/"):
            return self.check_code(content, "shell", source)

        return VigilResult(True, VigilAction.ALLOWED)

    # === 감사 로그 ===

    def _audit(
        self,
        event_type: str,
        target: str,
        action: VigilAction,
        reason: str = "",
        source: str = "unknown",
        context: Dict = None
    ):
        """감사 로그 기록."""
        if not self.ssot:
            return

        try:
            self.ssot.conn.execute("""
                INSERT INTO vigil_audit
                (event_type, target, action, reason, source, context)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                event_type,
                str(target)[:500],
                action.value,
                reason,
                source,
                json.dumps(context or {})
            ))
            self.ssot.conn.commit()
        except Exception as e:
            logger.warning(f"[VIGIL] Audit log failed: {e}")

    def get_audit_log(self, limit: int = 50, action: str = None) -> List[Dict]:
        """감사 로그 조회."""
        if not self.ssot:
            return []

        sql = "SELECT * FROM vigil_audit"
        params = []
        if action:
            sql += " WHERE action = ?"
            params.append(action)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = self.ssot.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_blocked_count(self, hours: int = 24) -> int:
        """최근 N시간 차단 횟수."""
        if not self.ssot:
            return 0

        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        row = self.ssot.conn.execute("""
            SELECT COUNT(*) FROM vigil_audit
            WHERE action = 'blocked' AND created_at > ?
        """, (cutoff,)).fetchone()
        return row[0] if row else 0

    # === 통계 ===

    def get_stats(self) -> Dict[str, Any]:
        """VIGIL 통계."""
        return {
            "enabled": self.enabled,
            "kill_switch_active": self.check_kill_switch(),
            "critical_files": list(self.CRITICAL_FILES),
            "blocked_24h": self.get_blocked_count(24),
        }


# === 전역 인스턴스 ===
_vigil_instance: Optional[VIGIL] = None


def get_vigil(ssot=None) -> VIGIL:
    """VIGIL 싱글톤."""
    global _vigil_instance
    if _vigil_instance is None:
        _vigil_instance = VIGIL(ssot)
    elif ssot and _vigil_instance.ssot is None:
        _vigil_instance.ssot = ssot
    return _vigil_instance
