"""ADaPT - Adaptive Dynamic Planning.

실행 중 계획 동적 조정:
1. 신뢰도 기반 실행/확인
2. 결과 기반 단계 수정
3. 조건 분기 처리
"""
import logging
import re
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("REZE.adapt")


class AdjustmentType(Enum):
    MODIFY = "modify"      # 단계 입력/파라미터 수정
    SKIP = "skip"          # 단계 건너뛰기
    INSERT = "insert"      # 새 단계 삽입
    BRANCH = "branch"      # 조건 분기


@dataclass
class ConfidenceResult:
    """신뢰도 평가 결과."""
    score: float           # 0.0 ~ 1.0
    factors: List[str]     # 신뢰도에 영향 준 요소
    should_confirm: bool   # 확인 필요 여부
    suggestion: str = ""   # 낮을 때 제안


@dataclass
class AdjustmentRecord:
    """계획 조정 기록."""
    step_id: int
    adjustment_type: AdjustmentType
    original_value: str
    new_value: str
    reason: str
    triggered_by: str


@dataclass
class AdaptivePlanStep:
    """확장된 계획 단계 (ADaPT용)."""
    id: int
    action: str
    tool: str
    input: Any
    expect: str = ""
    on_fail: str = ""
    result: str = ""
    status: str = "pending"
    confidence: float = 0.8
    condition: str = ""           # 실행 조건 (이전 결과 기반)
    branch_if_true: int = None    # 조건 참일 때 다음 단계
    branch_if_false: int = None   # 조건 거짓일 때 다음 단계
    adjustable: bool = True       # 동적 조정 허용 여부
    requires_confirm: bool = False  # 실행 전 확인 필요


class ADaPTEngine:
    """Adaptive Dynamic Planning Engine."""

    def __init__(
        self,
        ssot=None,
        router=None,
        confidence_threshold: float = 0.7,
        auto_adjust: bool = True,
        max_adjustments: int = 3
    ):
        self.ssot = ssot
        self.router = router
        self.confidence_threshold = confidence_threshold
        self.auto_adjust = auto_adjust
        self.max_adjustments = max_adjustments
        self._adjustments: List[AdjustmentRecord] = []

    # === 신뢰도 평가 ===

    async def evaluate_confidence(
        self,
        step: AdaptivePlanStep,
        context: Dict[str, Any]
    ) -> ConfidenceResult:
        """
        단계 실행 전 신뢰도 평가.

        Args:
            step: 실행할 단계
            context: 이전 단계 결과 등 컨텍스트

        Returns:
            ConfidenceResult
        """
        factors = []
        score = step.confidence  # 기본값

        # Factor 1: 도구 위험도
        tool_risk = self._assess_tool_risk(step.tool, step.input)
        if tool_risk > 0.5:
            score -= tool_risk * 0.2
            factors.append(f"high_risk_tool ({tool_risk:.1f})")

        # Factor 2: 이전 단계 실패 여부
        prev_failures = context.get("consecutive_failures", 0)
        if prev_failures > 0:
            score -= prev_failures * 0.1
            factors.append(f"prev_failures ({prev_failures})")

        # Factor 3: 입력에 불확실한 참조 포함
        uncertain_refs = self._count_uncertain_refs(step.input, context)
        if uncertain_refs > 0:
            score -= uncertain_refs * 0.1
            factors.append(f"uncertain_refs ({uncertain_refs})")

        # Factor 4: 유사 실패 이력
        similar_failures = self._check_similar_failures(step)
        if similar_failures > 0:
            score -= similar_failures * 0.15
            factors.append(f"similar_failures ({similar_failures})")

        score = max(0.1, min(1.0, score))
        should_confirm = score < self.confidence_threshold or step.requires_confirm

        suggestion = ""
        if should_confirm and self.router:
            suggestion = await self._generate_suggestion(step, factors)

        return ConfidenceResult(
            score=score,
            factors=factors,
            should_confirm=should_confirm,
            suggestion=suggestion
        )

    def _assess_tool_risk(self, tool: str, tool_input: Any) -> float:
        """도구 위험도 평가 (0.0 ~ 1.0)."""
        risk_map = {
            "shell": 0.6,
            "python": 0.4,
            "http": 0.3,
            "code_edit": 0.5,
            "web_search": 0.1,
            "web_fetch": 0.1,
            "filesystem": 0.4,
            "final_answer": 0.0,
        }
        base_risk = risk_map.get(tool, 0.5)

        # 추가 위험 요소 체크
        input_str = str(tool_input).lower()
        if any(kw in input_str for kw in ["delete", "remove", "drop", "rm "]):
            base_risk += 0.3
        if any(kw in input_str for kw in ["sudo", "root", "chmod", "chown"]):
            base_risk += 0.2

        return min(1.0, base_risk)

    def _count_uncertain_refs(self, tool_input: Any, context: Dict) -> int:
        """불확실한 참조 개수 (값이 없는 {step_N_result})."""
        input_str = str(tool_input)
        refs = re.findall(r'\{step_(\d+)_result\}', input_str)
        uncertain = 0
        for ref in refs:
            key = f"step_{ref}_result"
            if key not in context or not context[key]:
                uncertain += 1
        return uncertain

    def _check_similar_failures(self, step: AdaptivePlanStep) -> int:
        """유사 단계 실패 이력 조회."""
        if not self.ssot:
            return 0
        try:
            rows = self.ssot.conn.execute("""
                SELECT COUNT(*) FROM iterations
                WHERE action_type = ? AND success = 0
                AND created_at > datetime('now', '-7 days')
            """, (step.tool,)).fetchone()
            return min(3, rows[0] // 10) if rows else 0
        except:
            return 0

    async def _generate_suggestion(
        self,
        step: AdaptivePlanStep,
        factors: List[str]
    ) -> str:
        """낮은 신뢰도 시 제안 생성."""
        prompt = f"""단계 실행 신뢰도가 낮습니다.

단계: {step.action}
도구: {step.tool}
입력: {str(step.input)[:200]}
요인: {', '.join(factors)}

안전하게 진행하기 위한 1-2문장 제안:"""

        try:
            response = await self.router.call("planning", prompt, temperature=0.3)
            text = response.text if hasattr(response, 'text') else str(response)
            return text[:200]
        except:
            return "실행 전 입력값 확인 권장"

    # === 동적 조정 ===

    async def adjust_step(
        self,
        step: AdaptivePlanStep,
        prev_result: str,
        context: Dict[str, Any],
        plan_id: int = None
    ) -> Tuple[AdaptivePlanStep, bool]:
        """
        이전 결과 기반 단계 동적 조정.

        Args:
            step: 조정할 단계
            prev_result: 이전 단계 실행 결과
            context: 전체 컨텍스트
            plan_id: 계획 ID (로깅용)

        Returns:
            (조정된 단계, 조정 여부)
        """
        if not self.auto_adjust or not step.adjustable:
            return step, False

        if len(self._adjustments) >= self.max_adjustments:
            logger.info(f"[ADaPT] Max adjustments reached ({self.max_adjustments})")
            return step, False

        # 조정 필요 여부 판단
        adjustment = await self._should_adjust(step, prev_result, context)
        if not adjustment:
            return step, False

        # 조정 적용
        adjusted_step = self._apply_adjustment(step, adjustment)

        # 기록
        self._adjustments.append(adjustment)
        self._log_adjustment(plan_id, adjustment)

        logger.info(f"[ADaPT] Step {step.id} adjusted: {adjustment.adjustment_type.value}")
        return adjusted_step, True

    async def _should_adjust(
        self,
        step: AdaptivePlanStep,
        prev_result: str,
        context: Dict
    ) -> Optional[AdjustmentRecord]:
        """조정 필요 여부 판단 및 조정 내용 결정."""
        # 이전 결과 분석
        if not prev_result:
            return None

        # Case 1: 이전 결과에 에러 포함
        if "error" in prev_result.lower() or "not found" in prev_result.lower():
            # 입력에 이전 결과 참조가 있으면 조정 필요
            input_str = str(step.input)
            if "{step_" in input_str and "_result}" in input_str:
                adjusted_input = self._adjust_input_for_error(input_str, prev_result)
                if adjusted_input != input_str:
                    return AdjustmentRecord(
                        step_id=step.id,
                        adjustment_type=AdjustmentType.MODIFY,
                        original_value=input_str,
                        new_value=adjusted_input,
                        reason="Previous step had error, adjusting input",
                        triggered_by="execution_result"
                    )

        # Case 2: 이전 결과가 예상과 다름
        prev_step_id = step.id - 1
        if prev_step_id > 0:
            expected = context.get(f"step_{prev_step_id}_expect", "")
            if expected and not self._result_matches_expectation(prev_result, expected):
                adjusted_input = await self._generate_adjusted_input(step, prev_result, context)
                if adjusted_input != str(step.input):
                    return AdjustmentRecord(
                        step_id=step.id,
                        adjustment_type=AdjustmentType.MODIFY,
                        original_value=str(step.input),
                        new_value=adjusted_input,
                        reason="Previous result didn't match expectation",
                        triggered_by="execution_result"
                    )

        return None

    def _adjust_input_for_error(self, input_str: str, error: str) -> str:
        """에러 기반 입력 조정."""
        # 에러 메시지에서 힌트 추출 시도
        error_lower = error.lower()

        if "not found" in error_lower:
            # 경로 관련 에러면 대체 경로 시도
            if "/var/" in input_str:
                return input_str.replace("/var/", "/tmp/")
            if "/opt/" in input_str:
                return input_str.replace("/opt/", "/home/")

        if "permission denied" in error_lower:
            # 권한 에러면 sudo 추가 시도 (쉘 명령인 경우)
            if not input_str.strip().startswith("sudo"):
                return f"sudo {input_str}"

        return input_str  # 조정 실패 시 원본 반환

    def _result_matches_expectation(self, result: str, expected: str) -> bool:
        """결과가 기대와 일치하는지."""
        if not expected:
            return True

        result_lower = result.lower()
        expected_lower = expected.lower()

        # 키워드 매칭
        keywords = [kw for kw in expected_lower.split() if len(kw) > 2]
        if not keywords:
            return True

        matches = sum(1 for kw in keywords if kw in result_lower)
        return matches >= len(keywords) * 0.5

    async def _generate_adjusted_input(
        self,
        step: AdaptivePlanStep,
        prev_result: str,
        context: Dict
    ) -> str:
        """LLM으로 조정된 입력 생성."""
        if not self.router:
            return str(step.input)

        prompt = f"""이전 단계 결과를 반영해서 입력을 조정하세요.

현재 단계: {step.action}
도구: {step.tool}
원래 입력: {str(step.input)[:300]}
이전 결과: {prev_result[:500]}

조정된 입력만 출력 (JSON이면 JSON 형태로):"""

        try:
            response = await self.router.call("planning", prompt, temperature=0.2)
            adjusted = response.text if hasattr(response, 'text') else str(response)
            # 불필요한 마크다운 제거
            adjusted = adjusted.strip().strip('`').strip()
            if adjusted.startswith("```"):
                adjusted = adjusted.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            return adjusted if adjusted else str(step.input)
        except:
            return str(step.input)

    def _apply_adjustment(
        self,
        step: AdaptivePlanStep,
        adjustment: AdjustmentRecord
    ) -> AdaptivePlanStep:
        """조정 적용."""
        if adjustment.adjustment_type == AdjustmentType.MODIFY:
            step.input = adjustment.new_value
        elif adjustment.adjustment_type == AdjustmentType.SKIP:
            step.tool = "final_answer"
            step.input = f"Step skipped: {adjustment.reason}"
        return step

    def _log_adjustment(self, plan_id: int, adjustment: AdjustmentRecord):
        """조정 이력 DB 기록."""
        if not self.ssot or not plan_id:
            return
        try:
            self.ssot.conn.execute("""
                INSERT INTO adapt_adjustments
                (plan_id, step_id, adjustment_type, original_value, new_value, reason, triggered_by)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                plan_id,
                adjustment.step_id,
                adjustment.adjustment_type.value,
                adjustment.original_value[:500],
                adjustment.new_value[:500],
                adjustment.reason,
                adjustment.triggered_by
            ))
            self.ssot.conn.commit()
        except Exception as e:
            logger.warning(f"[ADaPT] Log adjustment failed: {e}")

    # === 조건 분기 ===

    def evaluate_condition(
        self,
        step: AdaptivePlanStep,
        context: Dict[str, Any]
    ) -> Tuple[bool, int]:
        """
        조건 평가 및 다음 단계 결정.

        Returns:
            (조건 결과, 다음 단계 ID)
        """
        if not step.condition:
            return True, step.id + 1  # 조건 없으면 다음 단계

        # 조건 평가
        condition_result = self._eval_condition(step.condition, context)

        if condition_result:
            next_step = step.branch_if_true if step.branch_if_true else step.id + 1
        else:
            next_step = step.branch_if_false if step.branch_if_false else step.id + 1

        logger.info(f"[ADaPT] Condition '{step.condition[:50]}' = {condition_result} -> step {next_step}")
        return condition_result, next_step

    def _eval_condition(self, condition: str, context: Dict) -> bool:
        """조건 문자열 평가."""
        # 변수 치환
        for key, value in context.items():
            condition = condition.replace(f"{{{key}}}", str(value)[:200])

        condition_lower = condition.lower()

        # 안전한 평가
        try:
            # 간단한 비교 연산만 허용
            if "==" in condition:
                left, right = condition.split("==", 1)
                return left.strip().lower() == right.strip().lower()
            elif "!=" in condition:
                left, right = condition.split("!=", 1)
                return left.strip().lower() != right.strip().lower()
            elif "contains" in condition_lower:
                match = re.match(r"(.+)\s+contains\s+(.+)", condition, re.IGNORECASE)
                if match:
                    return match.group(2).strip().lower() in match.group(1).strip().lower()
            elif "not contains" in condition_lower:
                match = re.match(r"(.+)\s+not\s+contains\s+(.+)", condition, re.IGNORECASE)
                if match:
                    return match.group(2).strip().lower() not in match.group(1).strip().lower()
            elif "success" in condition_lower:
                last_result = str(context.get("last_result", "")).lower()
                return "error" not in last_result and "blocked" not in last_result
            elif "failure" in condition_lower or "failed" in condition_lower:
                last_result = str(context.get("last_result", "")).lower()
                return "error" in last_result or "blocked" in last_result
            elif "empty" in condition_lower:
                match = re.match(r"(.+)\s+is\s+empty", condition, re.IGNORECASE)
                if match:
                    value = match.group(1).strip()
                    return not value or value.lower() in ("none", "null", "")
            elif "not empty" in condition_lower:
                match = re.match(r"(.+)\s+is\s+not\s+empty", condition, re.IGNORECASE)
                if match:
                    value = match.group(1).strip()
                    return bool(value) and value.lower() not in ("none", "null", "")
        except Exception as e:
            logger.warning(f"[ADaPT] Condition eval error: {e}")

        return True  # 평가 실패 시 기본 True

    # === 헬퍼 ===

    def convert_to_adaptive_step(self, step) -> AdaptivePlanStep:
        """일반 PlanStep을 AdaptivePlanStep으로 변환."""
        return AdaptivePlanStep(
            id=step.id,
            action=getattr(step, 'action', ''),
            tool=getattr(step, 'tool', ''),
            input=getattr(step, 'input', ''),
            expect=getattr(step, 'expect', ''),
            on_fail=getattr(step, 'on_fail', ''),
            result=getattr(step, 'result', ''),
            status=getattr(step, 'status', 'pending'),
            confidence=getattr(step, 'confidence', 0.8),
            condition=getattr(step, 'condition', ''),
            branch_if_true=getattr(step, 'branch_if_true', None),
            branch_if_false=getattr(step, 'branch_if_false', None),
            adjustable=getattr(step, 'adjustable', True),
            requires_confirm=getattr(step, 'requires_confirm', False)
        )

    # === 통계 ===

    def get_stats(self) -> Dict[str, Any]:
        """ADaPT 통계."""
        return {
            "total_adjustments": len(self._adjustments),
            "adjustments_by_type": {
                t.value: sum(1 for a in self._adjustments if a.adjustment_type == t)
                for t in AdjustmentType
            },
            "confidence_threshold": self.confidence_threshold,
            "auto_adjust": self.auto_adjust,
            "max_adjustments": self.max_adjustments,
        }

    def get_adjustment_history(self) -> List[Dict]:
        """조정 이력 반환."""
        return [
            {
                "step_id": a.step_id,
                "type": a.adjustment_type.value,
                "original": a.original_value[:100],
                "new": a.new_value[:100],
                "reason": a.reason,
                "triggered_by": a.triggered_by
            }
            for a in self._adjustments
        ]

    def reset(self):
        """조정 이력 초기화 (새 계획 시작 시)."""
        self._adjustments.clear()
