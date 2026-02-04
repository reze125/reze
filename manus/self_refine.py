"""Self-Refine - 결과물 자기 피드백 및 반복 개선 엔진.

결과물의 품질을 평가하고, 미달 시 피드백 기반으로 개선합니다.
최대 3회 반복하여 품질 목표 달성을 시도합니다.
"""
import logging
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger("REZE.self_refine")


@dataclass
class RefineResult:
    """개선 결과."""
    original_content: str
    final_content: str
    output_type: str
    initial_score: float
    final_score: float
    iterations: int
    history: List[Dict[str, Any]] = field(default_factory=list)
    improved: bool = False


class SelfRefineEngine:
    """결과물 자기 피드백 및 반복 개선."""

    def __init__(
        self,
        router,
        max_iterations: int = 3,
        min_score: float = 70.0,
        enabled_types: List[str] = None
    ):
        """
        Args:
            router: LLM 라우터
            max_iterations: 최대 반복 횟수
            min_score: 최소 통과 점수
            enabled_types: 개선 대상 유형 리스트
        """
        self.router = router
        self.max_iterations = max_iterations
        self.min_score = min_score
        self.enabled_types = enabled_types or [
            "blog_article", "saas_report", "strategy_document",
            "code_change", "email_outreach"
        ]

    def should_refine(self, output_type: str) -> bool:
        """해당 유형이 개선 대상인지 확인."""
        return output_type in self.enabled_types

    async def refine(
        self,
        content: str,
        task: str,
        classify_fn: Callable,
        hard_check_fn: Callable,
        cross_review_fn: Callable,
    ) -> RefineResult:
        """
        결과물 품질 평가 및 반복 개선.

        Args:
            content: 원본 결과물
            task: 원래 태스크
            classify_fn: _classify_output(task, output) -> str
            hard_check_fn: _run_hard_checks(output, checks_dict) -> dict
            cross_review_fn: _cross_review(output, config_dict) -> dict

        Returns:
            RefineResult
        """
        # 1. 유형 분류
        output_type = await classify_fn(task, content)

        if not self.should_refine(output_type):
            logger.debug(f"[SelfRefine] Type '{output_type}' not in refine targets, skipping")
            return RefineResult(
                original_content=content,
                final_content=content,
                output_type=output_type,
                initial_score=100.0,
                final_score=100.0,
                iterations=0,
                improved=False
            )

        # 2. QUALITY_GATES에서 설정 가져오기
        from reze_permissions import QUALITY_GATES
        gate_config = QUALITY_GATES.get(output_type, {})
        hard_checks = gate_config.get("hard_checks", {})
        cross_config = gate_config.get("cross_review", {})

        # 3. 초기 평가
        current_content = content
        initial_score, hard_result, cross_result = await self._evaluate_full(
            current_content, hard_checks, cross_config, hard_check_fn, cross_review_fn
        )

        result = RefineResult(
            original_content=content,
            final_content=content,
            output_type=output_type,
            initial_score=initial_score,
            final_score=initial_score,
            iterations=0
        )

        # 이미 충분하면 반환
        if initial_score >= self.min_score:
            logger.info(f"[SelfRefine] Score {initial_score:.1f} >= {self.min_score}, no refinement needed")
            return result

        # 4. 반복 개선
        for iteration in range(1, self.max_iterations + 1):
            if result.final_score >= self.min_score:
                logger.info(f"[SelfRefine] Score {result.final_score:.1f} achieved, stopping")
                break

            # 피드백 정리
            feedback = self._compile_feedback(hard_result, cross_result)

            # 개선 요청
            improved_content = await self._request_improvement(
                current_content, task, output_type, feedback
            )

            # 새 점수 평가
            new_score, hard_result, cross_result = await self._evaluate_full(
                improved_content, hard_checks, cross_config, hard_check_fn, cross_review_fn
            )

            # 이력 기록
            result.history.append({
                "iteration": iteration,
                "before_score": result.final_score,
                "after_score": new_score,
                "feedback_summary": feedback[:200] + "..." if len(feedback) > 200 else feedback,
                "timestamp": datetime.now().isoformat()
            })

            result.iterations = iteration

            # 개선된 경우만 적용
            if new_score > result.final_score:
                current_content = improved_content
                result.final_content = improved_content
                result.final_score = new_score
                result.improved = True
                logger.info(f"[SelfRefine] Iteration {iteration}: {result.history[-1]['before_score']:.1f} -> {new_score:.1f}")
            else:
                logger.info(f"[SelfRefine] Iteration {iteration}: No improvement ({new_score:.1f} <= {result.history[-1]['before_score']:.1f}), stopping")
                break  # 개선 안 되면 더 이상 시도 안 함

        return result

    async def _evaluate_full(
        self,
        content: str,
        hard_checks: dict,
        cross_config: dict,
        hard_check_fn: Callable,
        cross_review_fn: Callable
    ) -> tuple:
        """콘텐츠 점수 산출 (상세 결과 포함)."""
        # Hard check
        hard_result = hard_check_fn(content, hard_checks)
        hard_score = 100 if hard_result.get("passed") else max(0, 100 - len(hard_result.get("failures", [])) * 15)

        # Cross review
        cross_result = await cross_review_fn(content, cross_config)
        cross_score = cross_result.get("score", 50)

        # 종합 (hard 30%, cross 70%)
        total_score = hard_score * 0.3 + cross_score * 0.7

        return total_score, hard_result, cross_result

    def _compile_feedback(self, hard_result: dict, cross_result: dict) -> str:
        """피드백 정리."""
        lines = []

        # Hard check 실패 항목
        if not hard_result.get("passed"):
            failures = hard_result.get("failures", [])
            if failures:
                lines.append("## 규칙 위반:")
                for f in failures:
                    lines.append(f"- {f}")

        # Cross review 피드백
        feedback = cross_result.get("feedback", "")
        score = cross_result.get("score", 0)
        if feedback:
            lines.append(f"\n## 품질 리뷰 (점수: {score}/100):")
            lines.append(feedback)
        elif score < 70:
            lines.append(f"\n## 품질 점수: {score}/100 (개선 필요)")

        return "\n".join(lines) if lines else "품질 개선 필요"

    async def _request_improvement(
        self,
        content: str,
        task: str,
        output_type: str,
        feedback: str
    ) -> str:
        """LLM에 개선 요청."""
        prompt = f"""당신은 콘텐츠 개선 전문가입니다.

## 원래 요청
{task}

## 현재 콘텐츠
{content[:4000]}

## 피드백
{feedback}

## 지시사항
위 피드백을 반영하여 콘텐츠를 개선해주세요.
- 기존 내용의 핵심은 유지
- 피드백에서 지적된 문제점 해결
- 더 명확하고 완성도 높게

개선된 전체 콘텐츠를 출력하세요:"""

        try:
            response = await self.router.call(
                "refine",
                [{"role": "user", "content": prompt}],
                temperature=0.3
            )
            improved = response.text if hasattr(response, 'text') else str(response)
            return improved if improved.strip() else content
        except Exception as e:
            logger.warning(f"[SelfRefine] Improvement request failed: {e}")
            return content


def refine_sync(
    content: str,
    task: str,
    output_type: str,
    hard_checks: dict,
    cross_score: float,
    cross_feedback: str
) -> dict:
    """동기 버전 피드백 컴파일 (테스트/디버그용)."""
    engine = SelfRefineEngine(router=None)

    hard_result = {"passed": len(hard_checks.get("failures", [])) == 0, "failures": hard_checks.get("failures", [])}
    cross_result = {"score": cross_score, "feedback": cross_feedback}

    feedback = engine._compile_feedback(hard_result, cross_result)

    return {
        "output_type": output_type,
        "feedback": feedback,
        "should_refine": cross_score < 70 or not hard_result["passed"]
    }
