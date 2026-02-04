"""Agentless Step 3: 테스트 검증.

테스트를 실행하여 패치가 버그를 수정했는지 확인합니다.
"""
import re
import time
from typing import Optional
from dataclasses import dataclass
from enum import Enum

import logging
logger = logging.getLogger("REZE.agentless")

# 순환 import 방지
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from agentless.repairer import Patch


class ValidationResult(Enum):
    """검증 결과."""
    PASS = "pass"
    FAIL = "fail"
    ERROR = "error"
    TIMEOUT = "timeout"
    SKIP = "skip"


@dataclass
class Validation:
    """검증 결과 정보."""
    result: ValidationResult
    tests_run: int
    tests_passed: int
    tests_failed: int
    output: str
    duration_ms: int


class PatchValidator:
    """테스트 기반 패치 검증."""

    DEFAULT_TIMEOUT = 60  # 초

    def __init__(self, tools):
        """
        Args:
            tools: ToolExecutor 인스턴스
        """
        self.tools = tools

    async def validate(
        self,
        patch: "Patch",
        test_command: str = None,
        repo_path: str = None,
        timeout: int = None
    ) -> Validation:
        """
        테스트 실행으로 패치 검증.

        Args:
            patch: 검증할 패치
            test_command: 테스트 명령 (없으면 자동 탐지)
            repo_path: 레포지토리 경로
            timeout: 타임아웃 (초)

        Returns:
            Validation 결과
        """
        timeout = timeout or self.DEFAULT_TIMEOUT
        repo_path = repo_path or self._extract_repo_path(patch.file_path)

        logger.info(f"[VALIDATE] Validating patch {patch.patch_id}")

        # 1. 구문 검사 (빠른 실패)
        syntax_ok = await self._check_syntax(patch.file_path)
        if not syntax_ok:
            return Validation(
                result=ValidationResult.ERROR,
                tests_run=0,
                tests_passed=0,
                tests_failed=0,
                output="Syntax error in patched file",
                duration_ms=0
            )

        # 2. 테스트 명령 결정
        if not test_command:
            test_command = await self._detect_test_command(repo_path, patch.file_path)

        if not test_command:
            logger.warning("[VALIDATE] No test command available, skipping validation")
            return Validation(
                result=ValidationResult.SKIP,
                tests_run=0,
                tests_passed=0,
                tests_failed=0,
                output="No test command detected",
                duration_ms=0
            )

        # 3. 테스트 실행
        start_time = time.time()
        test_output = await self._run_tests(test_command, timeout, repo_path)
        duration_ms = int((time.time() - start_time) * 1000)

        # 4. 결과 파싱
        return self._parse_test_output(test_output, duration_ms)

    async def _check_syntax(self, file_path: str) -> bool:
        """구문 검사."""
        ast_code = f'''
import ast
try:
    with open("{file_path}", "r") as f:
        ast.parse(f.read())
    print("OK")
except SyntaxError as e:
    print(f"SYNTAX_ERROR: {{e}}")
'''
        result = await self.tools.execute("python", ast_code, source="agentless")
        return result.strip() == "OK"

    async def _detect_test_command(self, repo_path: str, file_path: str) -> Optional[str]:
        """테스트 프레임워크 자동 탐지."""
        # pytest.ini 또는 pyproject.toml 확인
        check_cmd = f'ls "{repo_path}/pytest.ini" "{repo_path}/pyproject.toml" "{repo_path}/setup.py" 2>/dev/null | head -1'
        result = await self.tools.execute("shell", check_cmd, source="agentless")

        if "pytest.ini" in result or "pyproject.toml" in result:
            # pytest 사용
            # 관련 테스트 파일 찾기
            module_name = file_path.split("/")[-1].replace(".py", "")
            test_file = await self._find_test_file(repo_path, module_name)
            if test_file:
                return f'cd "{repo_path}" && python -m pytest "{test_file}" -v --tb=short 2>&1'
            return f'cd "{repo_path}" && python -m pytest -v --tb=short 2>&1'

        # unittest 확인
        test_dir = f"{repo_path}/tests"
        check_result = await self.tools.execute(
            "shell",
            f'ls "{test_dir}" 2>/dev/null | head -1',
            source="agentless"
        )
        if check_result and not check_result.startswith("ERROR"):
            return f'cd "{repo_path}" && python -m unittest discover -v 2>&1'

        return None

    async def _find_test_file(self, repo_path: str, module_name: str) -> Optional[str]:
        """모듈에 대응하는 테스트 파일 찾기."""
        patterns = [
            f"test_{module_name}.py",
            f"{module_name}_test.py",
            f"tests/test_{module_name}.py",
            f"tests/{module_name}_test.py",
        ]

        for pattern in patterns:
            check_cmd = f'ls "{repo_path}/{pattern}" 2>/dev/null'
            result = await self.tools.execute("shell", check_cmd, source="agentless")
            if result and not result.startswith("ERROR") and result.strip():
                return result.strip()

        return None

    async def _run_tests(self, command: str, timeout: int, repo_path: str) -> str:
        """테스트 실행."""
        # timeout 명령 추가
        full_command = f'timeout {timeout} bash -c \'{command}\' 2>&1 || echo "TIMEOUT_OR_ERROR"'

        logger.info(f"[VALIDATE] Running: {command[:80]}...")
        result = await self.tools.execute("shell", full_command, source="agentless")

        return result

    def _parse_test_output(self, output: str, duration_ms: int) -> Validation:
        """테스트 출력 파싱."""
        # 타임아웃 체크
        if "TIMEOUT_OR_ERROR" in output and "PASSED" not in output:
            return Validation(
                result=ValidationResult.TIMEOUT,
                tests_run=0,
                tests_passed=0,
                tests_failed=0,
                output=output[:1000],
                duration_ms=duration_ms
            )

        # pytest 형식 파싱
        pytest_match = re.search(
            r'(\d+)\s+passed(?:,\s*(\d+)\s+failed)?(?:,\s*(\d+)\s+error)?',
            output, re.IGNORECASE
        )

        if pytest_match:
            passed = int(pytest_match.group(1))
            failed = int(pytest_match.group(2) or 0)
            errors = int(pytest_match.group(3) or 0)
            total = passed + failed + errors

            if failed > 0 or errors > 0:
                result = ValidationResult.FAIL
            else:
                result = ValidationResult.PASS

            return Validation(
                result=result,
                tests_run=total,
                tests_passed=passed,
                tests_failed=failed + errors,
                output=output[:1000],
                duration_ms=duration_ms
            )

        # unittest 형식 파싱
        unittest_match = re.search(r'Ran\s+(\d+)\s+tests?', output)
        if unittest_match:
            total = int(unittest_match.group(1))
            ok_match = re.search(r'\bOK\b', output)
            fail_match = re.search(r'FAILED\s*\((?:failures=(\d+))?(?:,?\s*errors=(\d+))?\)', output)

            if ok_match and not fail_match:
                return Validation(
                    result=ValidationResult.PASS,
                    tests_run=total,
                    tests_passed=total,
                    tests_failed=0,
                    output=output[:1000],
                    duration_ms=duration_ms
                )
            elif fail_match:
                failures = int(fail_match.group(1) or 0)
                errors = int(fail_match.group(2) or 0)
                return Validation(
                    result=ValidationResult.FAIL,
                    tests_run=total,
                    tests_passed=total - failures - errors,
                    tests_failed=failures + errors,
                    output=output[:1000],
                    duration_ms=duration_ms
                )

        # 에러 패턴 체크
        if re.search(r'error|exception|traceback', output, re.IGNORECASE):
            return Validation(
                result=ValidationResult.ERROR,
                tests_run=0,
                tests_passed=0,
                tests_failed=0,
                output=output[:1000],
                duration_ms=duration_ms
            )

        # 기본: 알 수 없음 → 에러로 처리
        return Validation(
            result=ValidationResult.ERROR,
            tests_run=0,
            tests_passed=0,
            tests_failed=0,
            output=f"Could not parse test output:\n{output[:500]}",
            duration_ms=duration_ms
        )

    def _extract_repo_path(self, file_path: str) -> str:
        """파일 경로에서 레포 루트 추출."""
        # 간단한 휴리스틱: /home/reze/reze-agent/ 같은 패턴
        parts = file_path.split("/")
        for i, part in enumerate(parts):
            if part in ("reze-agent", "projects", "blogs"):
                return "/".join(parts[:i+1])
        # 기본값
        return "/".join(parts[:-1])
