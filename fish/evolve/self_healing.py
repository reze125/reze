"""
Self-Healing — REZE v6.0 SOVEREIGN
자기 치유 (오류 자동 복구)

반복되는 오류를 탐지하고,
자동으로 복구 전략을 시도합니다.

가동 조건: error_log에 같은 오류 3회 이상
"""

import re
import json
import asyncio
import logging
import traceback
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Callable, Tuple
from enum import Enum
from collections import defaultdict

logger = logging.getLogger("reze.evolve.self_healing")


class ErrorCategory(Enum):
    """오류 카테고리"""
    API_ERROR = "api_error"           # API 호출 실패
    TIMEOUT = "timeout"               # 타임아웃
    RATE_LIMIT = "rate_limit"         # 레이트 리밋
    AUTH_ERROR = "auth_error"         # 인증 오류
    DATA_ERROR = "data_error"         # 데이터 오류
    RESOURCE_ERROR = "resource_error" # 리소스 부족
    LOGIC_ERROR = "logic_error"       # 로직 오류
    UNKNOWN = "unknown"


class HealingStrategy(Enum):
    """치유 전략"""
    RETRY = "retry"                   # 재시도
    BACKOFF = "backoff"               # 지수 백오프
    FALLBACK = "fallback"             # 폴백 프로바이더
    RESET = "reset"                   # 상태 리셋
    SKIP = "skip"                     # 스킵
    ESCALATE = "escalate"             # 상위 에스컬레이션
    CIRCUIT_BREAK = "circuit_break"   # 서킷 브레이커


@dataclass
class ErrorPattern:
    """오류 패턴"""
    pattern_id: str
    category: ErrorCategory
    signature: str  # 오류 시그니처 (정규화된 메시지)
    count: int = 0
    first_seen: str = ""
    last_seen: str = ""
    healing_attempts: int = 0
    healed: bool = False


@dataclass
class HealingAction:
    """치유 액션"""
    action_id: str
    error_pattern_id: str
    strategy: HealingStrategy
    params: Dict = field(default_factory=dict)
    success: bool = False
    result: str = ""
    executed_at: str = ""


class SelfHealing:
    """
    자기 치유 엔진.
    오류 패턴 탐지 → 전략 선택 → 자동 복구.
    """

    # 카테고리별 기본 전략
    DEFAULT_STRATEGIES = {
        ErrorCategory.API_ERROR: HealingStrategy.RETRY,
        ErrorCategory.TIMEOUT: HealingStrategy.BACKOFF,
        ErrorCategory.RATE_LIMIT: HealingStrategy.BACKOFF,
        ErrorCategory.AUTH_ERROR: HealingStrategy.ESCALATE,
        ErrorCategory.DATA_ERROR: HealingStrategy.SKIP,
        ErrorCategory.RESOURCE_ERROR: HealingStrategy.CIRCUIT_BREAK,
        ErrorCategory.LOGIC_ERROR: HealingStrategy.ESCALATE,
        ErrorCategory.UNKNOWN: HealingStrategy.RETRY,
    }

    # 서킷 브레이커 상태
    CIRCUIT_OPEN_DURATION = 300  # 5분

    def __init__(self, ssot, llm_router=None):
        """
        Args:
            ssot: SSOT 인스턴스
            llm_router: LLM 라우터
        """
        self.ssot = ssot
        self.conn = ssot.conn if hasattr(ssot, 'conn') else ssot
        self.llm = llm_router

        # 서킷 브레이커 상태
        self._circuit_state: Dict[str, Dict] = {}  # {service: {open_until, failures}}

        # 에러 패턴 캐시
        self._patterns: Dict[str, ErrorPattern] = {}

        # 폴백 핸들러 등록
        self._fallback_handlers: Dict[str, Callable] = {}

    async def is_active(self) -> bool:
        """활성화 조건: error_log에 같은 오류 3회 이상"""
        try:
            # 중복 오류 확인
            row = self.conn.execute("""
                SELECT COUNT(*) FROM (
                    SELECT error_signature, COUNT(*) as cnt
                    FROM healing_errors
                    GROUP BY error_signature
                    HAVING cnt >= 3
                )
            """).fetchone()
            if row[0] >= 1:
                return True
        except:
            pass

        # evolution_log에서 에러 패턴 확인
        try:
            row = self.conn.execute("""
                SELECT COUNT(*) FROM (
                    SELECT outcome, COUNT(*) as cnt
                    FROM evolution_log
                    WHERE outcome LIKE '%error%' OR outcome LIKE '%fail%'
                    GROUP BY outcome
                    HAVING cnt >= 3
                )
            """).fetchone()
            return row[0] >= 1
        except:
            return False

    def register_fallback(self, service: str, handler: Callable):
        """폴백 핸들러 등록"""
        self._fallback_handlers[service] = handler

    def categorize_error(self, error: Exception, context: Dict = None) -> ErrorCategory:
        """오류 카테고리 분류"""
        error_str = str(error).lower()
        error_type = type(error).__name__.lower()

        # 타임아웃
        if any(kw in error_str for kw in ["timeout", "timed out", "deadline"]):
            return ErrorCategory.TIMEOUT

        # 레이트 리밋
        if any(kw in error_str for kw in ["rate limit", "too many requests", "429"]):
            return ErrorCategory.RATE_LIMIT

        # 인증
        if any(kw in error_str for kw in ["auth", "unauthorized", "forbidden", "401", "403"]):
            return ErrorCategory.AUTH_ERROR

        # API 오류
        if any(kw in error_str for kw in ["api", "request", "response", "http", "500", "502", "503"]):
            return ErrorCategory.API_ERROR

        # 데이터 오류
        if any(kw in error_str for kw in ["json", "parse", "decode", "key error", "index"]):
            return ErrorCategory.DATA_ERROR

        # 리소스
        if any(kw in error_str for kw in ["memory", "disk", "resource", "quota"]):
            return ErrorCategory.RESOURCE_ERROR

        # 로직
        if any(kw in error_type for kw in ["value", "type", "attribute", "assertion"]):
            return ErrorCategory.LOGIC_ERROR

        return ErrorCategory.UNKNOWN

    def get_error_signature(self, error: Exception) -> str:
        """오류 시그니처 생성 (정규화)"""
        # 숫자, UUID, 경로 등 제거
        error_str = str(error)
        signature = re.sub(r'\d+', 'N', error_str)
        signature = re.sub(r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}', 'UUID', signature)
        signature = re.sub(r'/[^\s]+', '/PATH', signature)
        signature = re.sub(r'\s+', ' ', signature).strip()

        # 최대 길이 제한
        return signature[:200]

    async def record_error(
        self,
        error: Exception,
        module: str,
        context: Dict = None
    ) -> ErrorPattern:
        """
        오류 기록.

        Args:
            error: 발생한 예외
            module: 발생 모듈
            context: 추가 컨텍스트

        Returns:
            ErrorPattern
        """
        signature = self.get_error_signature(error)
        category = self.categorize_error(error, context)
        now = datetime.utcnow().isoformat()

        # 기존 패턴 확인
        pattern = self._patterns.get(signature)

        if pattern:
            pattern.count += 1
            pattern.last_seen = now
        else:
            pattern = ErrorPattern(
                pattern_id=f"err_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{len(self._patterns)}",
                category=category,
                signature=signature,
                count=1,
                first_seen=now,
                last_seen=now
            )
            self._patterns[signature] = pattern

        # DB에 저장
        try:
            self.conn.execute("""
                INSERT INTO healing_errors
                (pattern_id, category, error_signature, module, error_message,
                 context, count, first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(error_signature) DO UPDATE SET
                    count = count + 1,
                    last_seen = ?
            """, (
                pattern.pattern_id,
                category.value,
                signature,
                module,
                str(error)[:500],
                json.dumps(context or {}),
                1,
                now, now,
                now
            ))
            self.conn.commit()
        except Exception as e:
            logger.error("Failed to record error: %s", e)

        return pattern

    def select_strategy(
        self,
        pattern: ErrorPattern,
        attempt: int = 0
    ) -> Tuple[HealingStrategy, Dict]:
        """
        치유 전략 선택.

        Args:
            pattern: 오류 패턴
            attempt: 시도 횟수

        Returns:
            (전략, 파라미터)
        """
        # 기본 전략
        strategy = self.DEFAULT_STRATEGIES.get(
            pattern.category,
            HealingStrategy.RETRY
        )

        params = {}

        # 시도 횟수에 따른 전략 조정
        if attempt >= 3:
            # 3회 이상 실패 → 에스컬레이션
            strategy = HealingStrategy.ESCALATE
            params["reason"] = f"Failed {attempt} attempts"

        elif attempt >= 1 and strategy == HealingStrategy.RETRY:
            # 재시도 → 백오프로 전환
            strategy = HealingStrategy.BACKOFF
            params["delay"] = min(30, 2 ** attempt)  # 지수 백오프

        elif pattern.count >= 10:
            # 빈번한 오류 → 서킷 브레이커
            strategy = HealingStrategy.CIRCUIT_BREAK
            params["duration"] = self.CIRCUIT_OPEN_DURATION

        # 전략별 기본 파라미터
        if strategy == HealingStrategy.RETRY:
            params["max_retries"] = 3
            params["delay"] = 1

        elif strategy == HealingStrategy.BACKOFF:
            params["initial_delay"] = params.get("delay", 1)
            params["max_delay"] = 60
            params["multiplier"] = 2

        elif strategy == HealingStrategy.FALLBACK:
            params["fallback_service"] = self._get_fallback_service(pattern)

        return strategy, params

    def _get_fallback_service(self, pattern: ErrorPattern) -> Optional[str]:
        """폴백 서비스 결정"""
        # API 오류면 다른 프로바이더로 폴백
        if pattern.category == ErrorCategory.API_ERROR:
            # 시그니처에서 서비스 추출 시도
            if "cerebras" in pattern.signature.lower():
                return "groq"
            elif "groq" in pattern.signature.lower():
                return "gemini_pro"
            elif "gemini" in pattern.signature.lower():
                return "cerebras"

        return None

    async def execute_healing(
        self,
        pattern: ErrorPattern,
        strategy: HealingStrategy,
        params: Dict,
        retry_fn: Callable = None
    ) -> HealingAction:
        """
        치유 실행.

        Args:
            pattern: 오류 패턴
            strategy: 치유 전략
            params: 전략 파라미터
            retry_fn: 재시도 함수

        Returns:
            HealingAction
        """
        action_id = f"heal_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"

        action = HealingAction(
            action_id=action_id,
            error_pattern_id=pattern.pattern_id,
            strategy=strategy,
            params=params,
            executed_at=datetime.utcnow().isoformat()
        )

        try:
            if strategy == HealingStrategy.RETRY:
                action = await self._execute_retry(action, retry_fn, params)

            elif strategy == HealingStrategy.BACKOFF:
                action = await self._execute_backoff(action, retry_fn, params)

            elif strategy == HealingStrategy.FALLBACK:
                action = await self._execute_fallback(action, retry_fn, params)

            elif strategy == HealingStrategy.RESET:
                action = await self._execute_reset(action, params)

            elif strategy == HealingStrategy.SKIP:
                action = await self._execute_skip(action, params)

            elif strategy == HealingStrategy.CIRCUIT_BREAK:
                action = await self._execute_circuit_break(action, params)

            elif strategy == HealingStrategy.ESCALATE:
                action = await self._execute_escalate(action, params)

        except Exception as e:
            action.success = False
            action.result = f"Healing failed: {e}"

        # 기록
        pattern.healing_attempts += 1
        if action.success:
            pattern.healed = True

        self._save_action(action)

        return action

    async def _execute_retry(
        self,
        action: HealingAction,
        retry_fn: Callable,
        params: Dict
    ) -> HealingAction:
        """재시도 실행"""
        if not retry_fn:
            action.success = False
            action.result = "No retry function provided"
            return action

        max_retries = params.get("max_retries", 3)
        delay = params.get("delay", 1)

        for attempt in range(max_retries):
            try:
                if asyncio.iscoroutinefunction(retry_fn):
                    result = await retry_fn()
                else:
                    result = retry_fn()

                action.success = True
                action.result = f"Succeeded on attempt {attempt + 1}"
                return action

            except Exception as e:
                if attempt < max_retries - 1:
                    await asyncio.sleep(delay)
                else:
                    action.result = f"All {max_retries} retries failed: {e}"

        action.success = False
        return action

    async def _execute_backoff(
        self,
        action: HealingAction,
        retry_fn: Callable,
        params: Dict
    ) -> HealingAction:
        """지수 백오프 실행"""
        if not retry_fn:
            action.success = False
            action.result = "No retry function provided"
            return action

        delay = params.get("initial_delay", 1)
        max_delay = params.get("max_delay", 60)
        multiplier = params.get("multiplier", 2)
        max_attempts = 5

        for attempt in range(max_attempts):
            try:
                await asyncio.sleep(delay)

                if asyncio.iscoroutinefunction(retry_fn):
                    result = await retry_fn()
                else:
                    result = retry_fn()

                action.success = True
                action.result = f"Succeeded after {delay}s backoff (attempt {attempt + 1})"
                return action

            except Exception as e:
                delay = min(delay * multiplier, max_delay)
                if attempt == max_attempts - 1:
                    action.result = f"Backoff failed after {max_attempts} attempts: {e}"

        action.success = False
        return action

    async def _execute_fallback(
        self,
        action: HealingAction,
        retry_fn: Callable,
        params: Dict
    ) -> HealingAction:
        """폴백 실행"""
        fallback_service = params.get("fallback_service")

        if fallback_service in self._fallback_handlers:
            try:
                handler = self._fallback_handlers[fallback_service]

                if asyncio.iscoroutinefunction(handler):
                    result = await handler()
                else:
                    result = handler()

                action.success = True
                action.result = f"Fallback to {fallback_service} succeeded"
                return action

            except Exception as e:
                action.result = f"Fallback to {fallback_service} failed: {e}"

        else:
            action.result = f"No fallback handler for {fallback_service}"

        action.success = False
        return action

    async def _execute_reset(
        self,
        action: HealingAction,
        params: Dict
    ) -> HealingAction:
        """상태 리셋"""
        # 캐시 클리어, 연결 재설정 등
        target = params.get("target", "all")

        try:
            # 서킷 브레이커 리셋
            if target in ("all", "circuit"):
                self._circuit_state.clear()

            # 패턴 캐시 리셋
            if target in ("all", "patterns"):
                self._patterns.clear()

            action.success = True
            action.result = f"Reset {target} completed"

        except Exception as e:
            action.success = False
            action.result = f"Reset failed: {e}"

        return action

    async def _execute_skip(
        self,
        action: HealingAction,
        params: Dict
    ) -> HealingAction:
        """스킵 (오류 무시)"""
        action.success = True
        action.result = "Error skipped"
        return action

    async def _execute_circuit_break(
        self,
        action: HealingAction,
        params: Dict
    ) -> HealingAction:
        """서킷 브레이커 열기"""
        service = params.get("service", "default")
        duration = params.get("duration", self.CIRCUIT_OPEN_DURATION)

        self._circuit_state[service] = {
            "open_until": (datetime.utcnow() + timedelta(seconds=duration)).isoformat(),
            "failures": 0
        }

        action.success = True
        action.result = f"Circuit opened for {service} ({duration}s)"
        return action

    async def _execute_escalate(
        self,
        action: HealingAction,
        params: Dict
    ) -> HealingAction:
        """상위 에스컬레이션"""
        reason = params.get("reason", "Unknown")

        # Boss approval 요청 또는 알림
        try:
            self.conn.execute("""
                INSERT INTO healing_escalations
                (action_id, reason, status, created_at)
                VALUES (?, ?, 'pending', ?)
            """, (
                action.action_id,
                reason,
                datetime.utcnow().isoformat()
            ))
            self.conn.commit()

            action.success = True
            action.result = f"Escalated: {reason}"

        except Exception as e:
            action.success = False
            action.result = f"Escalation failed: {e}"

        return action

    def is_circuit_open(self, service: str) -> bool:
        """서킷 브레이커 열림 여부"""
        state = self._circuit_state.get(service)

        if not state:
            return False

        open_until = datetime.fromisoformat(state["open_until"])
        return datetime.utcnow() < open_until

    async def heal(
        self,
        error: Exception,
        module: str,
        retry_fn: Callable = None,
        context: Dict = None
    ) -> HealingAction:
        """
        오류 치유 (통합 인터페이스).

        Args:
            error: 발생한 예외
            module: 발생 모듈
            retry_fn: 재시도 함수
            context: 추가 컨텍스트

        Returns:
            HealingAction
        """
        # 1. 오류 기록
        pattern = await self.record_error(error, module, context)

        # 2. 전략 선택
        strategy, params = self.select_strategy(pattern, pattern.healing_attempts)

        logger.info("Healing %s with %s (attempt %d)",
                    pattern.category.value, strategy.value, pattern.healing_attempts + 1)

        # 3. 치유 실행
        action = await self.execute_healing(pattern, strategy, params, retry_fn)

        return action

    def _save_action(self, action: HealingAction):
        """치유 액션 DB 저장"""
        try:
            self.conn.execute("""
                INSERT INTO healing_actions
                (action_id, error_pattern_id, strategy, params,
                 success, result, executed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                action.action_id,
                action.error_pattern_id,
                action.strategy.value,
                json.dumps(action.params),
                1 if action.success else 0,
                action.result,
                action.executed_at
            ))
            self.conn.commit()
        except Exception as e:
            logger.error("Failed to save healing action: %s", e)

    def get_error_patterns(self, min_count: int = 1) -> List[Dict]:
        """오류 패턴 목록"""
        try:
            rows = self.conn.execute("""
                SELECT pattern_id, category, error_signature, count,
                       first_seen, last_seen
                FROM healing_errors
                WHERE count >= ?
                ORDER BY count DESC
                LIMIT 50
            """, (min_count,)).fetchall()

            return [
                {
                    "pattern_id": r[0],
                    "category": r[1],
                    "signature": r[2],
                    "count": r[3],
                    "first_seen": r[4],
                    "last_seen": r[5]
                }
                for r in rows
            ]
        except:
            return []

    def get_healing_stats(self) -> Dict:
        """치유 통계"""
        try:
            # 전체 치유 시도
            total = self.conn.execute(
                "SELECT COUNT(*) FROM healing_actions"
            ).fetchone()[0]

            # 성공률
            success = self.conn.execute(
                "SELECT COUNT(*) FROM healing_actions WHERE success = 1"
            ).fetchone()[0]

            # 전략별 통계
            by_strategy = self.conn.execute("""
                SELECT strategy, COUNT(*), SUM(success)
                FROM healing_actions
                GROUP BY strategy
            """).fetchall()

            return {
                "total_attempts": total,
                "success_count": success,
                "success_rate": round(success / max(total, 1), 3),
                "by_strategy": {
                    r[0]: {"attempts": r[1], "successes": r[2] or 0}
                    for r in by_strategy
                },
                "open_circuits": list(self._circuit_state.keys())
            }
        except:
            return {"error": "Failed to get stats"}
