"""
Idempotency Guard — REZE v6.0 SOVEREIGN
중복 실행 방지

동일한 작업이 TTL 내에 재실행되는 것을 방지합니다.
진화 모듈의 멱등성을 보장합니다.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger("reze.evolve.idempotency")


class IdempotencyGuard:
    """
    중복 실행 방지 가드.
    작업 키 기반으로 TTL 내 중복 실행을 차단.
    """

    def __init__(self, ssot):
        """
        Args:
            ssot: SSOT 인스턴스 (conn 속성 필요)
        """
        self.ssot = ssot
        self.conn = ssot.conn if hasattr(ssot, 'conn') else ssot

    def can_execute(self, operation_key: str, ttl_hours: int = 24) -> bool:
        """
        작업 실행 가능 여부 확인.

        Args:
            operation_key: 작업 고유 키 (예: "self_code_patch_hunt_py")
            ttl_hours: 중복 방지 시간 (기본 24시간)

        Returns:
            True if 실행 가능, False if 이미 실행됨
        """
        cutoff = (datetime.utcnow() - timedelta(hours=ttl_hours)).isoformat()

        try:
            row = self.conn.execute("""
                SELECT created_at FROM idempotency_log
                WHERE operation_key = ? AND created_at > ?
            """, (operation_key, cutoff)).fetchone()

            if row:
                logger.debug(
                    "Idempotency: %s already executed at %s",
                    operation_key, row[0]
                )
                return False

            return True

        except Exception as e:
            logger.error("Idempotency check failed: %s", e)
            # 에러 시 실행 허용 (안전을 위해)
            return True

    def mark_executed(
        self,
        operation_key: str,
        result: str = "ok"
    ) -> bool:
        """
        작업 실행 완료 표시.

        Args:
            operation_key: 작업 고유 키
            result: 실행 결과 (ok, failed, etc.)

        Returns:
            True if 성공
        """
        try:
            self.conn.execute("""
                INSERT OR REPLACE INTO idempotency_log
                (operation_key, result, created_at)
                VALUES (?, ?, ?)
            """, (operation_key, result, datetime.utcnow().isoformat()))
            self.conn.commit()

            logger.debug("Idempotency: marked %s as %s", operation_key, result)
            return True

        except Exception as e:
            logger.error("Failed to mark execution: %s", e)
            return False

    def execute_once(
        self,
        operation_key: str,
        func,
        *args,
        ttl_hours: int = 24,
        **kwargs
    ):
        """
        함수를 TTL 내 한 번만 실행.

        Args:
            operation_key: 작업 고유 키
            func: 실행할 함수
            ttl_hours: 중복 방지 시간
            *args, **kwargs: 함수 인자

        Returns:
            함수 반환값 또는 None (이미 실행됨)
        """
        if not self.can_execute(operation_key, ttl_hours):
            logger.info(
                "Idempotency: skipping %s (already executed)",
                operation_key
            )
            return None

        try:
            result = func(*args, **kwargs)
            self.mark_executed(operation_key, "ok")
            return result
        except Exception as e:
            self.mark_executed(operation_key, f"failed: {str(e)[:100]}")
            raise

    async def execute_once_async(
        self,
        operation_key: str,
        coro_func,
        *args,
        ttl_hours: int = 24,
        **kwargs
    ):
        """
        비동기 함수를 TTL 내 한 번만 실행.

        Args:
            operation_key: 작업 고유 키
            coro_func: 실행할 코루틴 함수
            ttl_hours: 중복 방지 시간
            *args, **kwargs: 함수 인자

        Returns:
            함수 반환값 또는 None (이미 실행됨)
        """
        if not self.can_execute(operation_key, ttl_hours):
            logger.info(
                "Idempotency: skipping %s (already executed)",
                operation_key
            )
            return None

        try:
            result = await coro_func(*args, **kwargs)
            self.mark_executed(operation_key, "ok")
            return result
        except Exception as e:
            self.mark_executed(operation_key, f"failed: {str(e)[:100]}")
            raise

    def clear_key(self, operation_key: str) -> bool:
        """
        특정 키의 실행 기록 삭제 (재실행 허용).

        Args:
            operation_key: 삭제할 작업 키

        Returns:
            True if 성공
        """
        try:
            self.conn.execute(
                "DELETE FROM idempotency_log WHERE operation_key = ?",
                (operation_key,)
            )
            self.conn.commit()
            logger.info("Idempotency: cleared %s", operation_key)
            return True
        except Exception as e:
            logger.error("Failed to clear key: %s", e)
            return False

    def cleanup_expired(self, max_age_days: int = 30) -> int:
        """
        오래된 실행 기록 정리.

        Args:
            max_age_days: 보관 기간 (기본 30일)

        Returns:
            삭제된 레코드 수
        """
        cutoff = (datetime.utcnow() - timedelta(days=max_age_days)).isoformat()

        try:
            cursor = self.conn.execute("""
                DELETE FROM idempotency_log
                WHERE created_at < ?
            """, (cutoff,))
            self.conn.commit()

            deleted = cursor.rowcount
            if deleted > 0:
                logger.info("Idempotency: cleaned up %d old records", deleted)
            return deleted

        except Exception as e:
            logger.error("Failed to cleanup: %s", e)
            return 0

    def get_recent(self, limit: int = 50) -> list:
        """최근 실행 기록"""
        try:
            rows = self.conn.execute("""
                SELECT operation_key, result, created_at
                FROM idempotency_log
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,)).fetchall()
            return [
                {"key": r[0], "result": r[1], "created_at": r[2]}
                for r in rows
            ]
        except Exception as e:
            logger.error("Failed to get recent: %s", e)
            return []
