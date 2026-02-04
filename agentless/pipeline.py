"""Agentless 3-Step 통합 파이프라인.

Localize → Repair → Validate 순서로 자동 버그 수정을 실행합니다.
"""
import time
from typing import Optional
from dataclasses import dataclass, asdict
from enum import Enum

from agentless.localizer import BugLocalizer, Localization
from agentless.repairer import BugRepairer, Patch
from agentless.validator import PatchValidator, Validation, ValidationResult

import logging
logger = logging.getLogger("REZE.agentless")


class PipelineStatus(Enum):
    """파이프라인 상태."""
    SUCCESS = "success"
    LOCALIZE_FAILED = "localize_failed"
    REPAIR_FAILED = "repair_failed"
    VALIDATE_FAILED = "validate_failed"
    SYNTAX_ERROR = "syntax_error"


@dataclass
class AgentlessResult:
    """파이프라인 실행 결과."""
    status: PipelineStatus
    localization: Optional[Localization]
    applied_patch: Optional[Patch]
    validation: Optional[Validation]
    attempts: int
    total_time_ms: int

    def to_dict(self) -> dict:
        """JSON 직렬화용 딕셔너리 변환."""
        return {
            "status": self.status.value,
            "localization": {
                "file_path": self.localization.file_path,
                "start_line": self.localization.start_line,
                "end_line": self.localization.end_line,
                "hypothesis": self.localization.hypothesis,
                "confidence": self.localization.confidence
            } if self.localization else None,
            "applied_patch": {
                "file_path": self.applied_patch.file_path,
                "patch_id": self.applied_patch.patch_id,
                "explanation": self.applied_patch.explanation
            } if self.applied_patch else None,
            "validation": {
                "result": self.validation.result.value,
                "tests_run": self.validation.tests_run,
                "tests_passed": self.validation.tests_passed,
                "tests_failed": self.validation.tests_failed,
                "duration_ms": self.validation.duration_ms
            } if self.validation else None,
            "attempts": self.attempts,
            "total_time_ms": self.total_time_ms
        }


class AgentlessPipeline:
    """3단계 자동 버그 수정 파이프라인."""

    MAX_REPAIR_ATTEMPTS = 3
    MAX_VALIDATE_RETRIES = 2

    def __init__(self, tools, router, ssot=None):
        """
        Args:
            tools: ToolExecutor 인스턴스
            router: ModelRouter 인스턴스
            ssot: SSOT 인스턴스 (로깅용, 선택적)
        """
        self.tools = tools
        self.router = router
        self.ssot = ssot
        self.localizer = BugLocalizer(tools, router.call)
        self.repairer = BugRepairer(tools, router.call)
        self.validator = PatchValidator(tools)

    async def run(
        self,
        bug_description: str,
        repo_path: str,
        error_trace: str = None,
        test_command: str = None
    ) -> AgentlessResult:
        """
        전체 파이프라인 실행.

        Args:
            bug_description: 버그 설명
            repo_path: 레포지토리 경로
            error_trace: 에러 트레이스 (선택적)
            test_command: 테스트 명령 (선택적)

        Returns:
            AgentlessResult
        """
        start_time = time.time()
        attempts = 0

        logger.info(f"[PIPELINE] Starting Agentless pipeline for: {bug_description[:50]}...")
        await self._log_step("start", {"bug_description": bug_description, "repo_path": repo_path})

        # === STEP 1: LOCALIZE ===
        logger.info("[PIPELINE] Step 1: LOCALIZE")
        localizations = await self.localizer.localize(
            bug_description=bug_description,
            repo_path=repo_path,
            error_trace=error_trace
        )

        if not localizations:
            logger.warning("[PIPELINE] Localization failed - no locations found")
            await self._log_step("localize_failed", {})
            return AgentlessResult(
                status=PipelineStatus.LOCALIZE_FAILED,
                localization=None,
                applied_patch=None,
                validation=None,
                attempts=0,
                total_time_ms=int((time.time() - start_time) * 1000)
            )

        best_localization = localizations[0]
        logger.info(f"[PIPELINE] Found {len(localizations)} locations, using: {best_localization.file_path}:{best_localization.start_line}")
        await self._log_step("localize_success", {
            "file": best_localization.file_path,
            "line": best_localization.start_line,
            "confidence": best_localization.confidence
        })

        # === STEP 2: REPAIR ===
        logger.info("[PIPELINE] Step 2: REPAIR")
        patches = await self.repairer.generate_patches(
            localization=best_localization,
            bug_description=bug_description,
            num_patches=self.MAX_REPAIR_ATTEMPTS
        )

        if not patches:
            logger.warning("[PIPELINE] Repair failed - no patches generated")
            await self._log_step("repair_failed", {})
            return AgentlessResult(
                status=PipelineStatus.REPAIR_FAILED,
                localization=best_localization,
                applied_patch=None,
                validation=None,
                attempts=0,
                total_time_ms=int((time.time() - start_time) * 1000)
            )

        logger.info(f"[PIPELINE] Generated {len(patches)} patches")

        # === STEP 3: VALIDATE (각 패치 시도) ===
        logger.info("[PIPELINE] Step 3: VALIDATE")

        for patch in patches:
            attempts += 1
            logger.info(f"[PIPELINE] Trying patch {patch.patch_id} (attempt {attempts}/{len(patches)})")

            # 패치 적용
            apply_result = await self.repairer.apply_patch(patch)
            if not apply_result["success"]:
                logger.warning(f"[PIPELINE] Failed to apply patch {patch.patch_id}: {apply_result['message']}")
                continue

            # 구문 검사
            syntax_result = await self.repairer.syntax_check(patch.file_path)
            if not syntax_result["valid"]:
                logger.warning(f"[PIPELINE] Syntax error after patch: {syntax_result['error']}")
                await self.repairer.rollback(patch)
                continue

            # 테스트 검증
            validation = await self.validator.validate(
                patch=patch,
                test_command=test_command,
                repo_path=repo_path
            )

            await self._log_step("validate_attempt", {
                "patch_id": patch.patch_id,
                "result": validation.result.value,
                "tests_passed": validation.tests_passed,
                "tests_failed": validation.tests_failed
            })

            if validation.result == ValidationResult.PASS:
                logger.info(f"[PIPELINE] SUCCESS! Patch {patch.patch_id} passed validation")
                await self._log_step("success", {"patch_id": patch.patch_id})
                return AgentlessResult(
                    status=PipelineStatus.SUCCESS,
                    localization=best_localization,
                    applied_patch=patch,
                    validation=validation,
                    attempts=attempts,
                    total_time_ms=int((time.time() - start_time) * 1000)
                )

            elif validation.result == ValidationResult.SKIP:
                logger.info(f"[PIPELINE] No tests to run, assuming success for patch {patch.patch_id}")
                # 테스트가 없으면 구문 검사 통과를 성공으로 간주
                return AgentlessResult(
                    status=PipelineStatus.SUCCESS,
                    localization=best_localization,
                    applied_patch=patch,
                    validation=validation,
                    attempts=attempts,
                    total_time_ms=int((time.time() - start_time) * 1000)
                )

            else:
                # 실패 시 롤백하고 다음 패치 시도
                logger.warning(f"[PIPELINE] Patch {patch.patch_id} failed validation, rolling back")
                await self.repairer.rollback(patch)

        # 모든 패치 실패
        logger.error("[PIPELINE] All patches failed validation")
        await self._log_step("all_failed", {"attempts": attempts})

        return AgentlessResult(
            status=PipelineStatus.VALIDATE_FAILED,
            localization=best_localization,
            applied_patch=None,
            validation=validation if 'validation' in locals() else None,
            attempts=attempts,
            total_time_ms=int((time.time() - start_time) * 1000)
        )

    async def _log_step(self, step: str, data: dict):
        """SSOT에 단계별 로그 기록."""
        if self.ssot:
            try:
                self.ssot.log_event(
                    kind=f"agentless_{step}",
                    raw_input=str(data)[:500],
                    output_preview=step
                )
            except Exception as e:
                logger.warning(f"Failed to log step: {e}")
