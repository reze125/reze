"""
Self-Code Evolution — REZE v6.0 SOVEREIGN
자기 코드 진화 (Gödel Agent)

자신의 코드를 분석하고, 개선점을 찾아내어
샌드박스 검증 후 적용합니다.

가동 조건: experiment 성공 5회 이상
"""

import os
import re
import ast
import json
import logging
import difflib
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple

logger = logging.getLogger("reze.evolve.self_code")


@dataclass
class CodePatch:
    """코드 패치"""
    patch_id: str
    target_file: str
    original_code: str
    patched_code: str
    description: str
    risk_level: str  # LOW, MEDIUM, HIGH, CRITICAL
    test_result: Optional[Dict] = None
    status: str = "pending"  # pending, testing, approved, applied, rejected, rolled_back


class SelfCodeEvolution:
    """
    자기 코드 진화 (Gödel Agent 패턴).
    코드 분석 → 개선 제안 → 샌드박스 테스트 → 승인 → 적용.
    """

    # 수정 가능한 파일 패턴
    ALLOWED_FILES = [
        "fish/*.py",
        "fish/**/*.py",
        "manus/*.py",
        "skills/*.py",
    ]

    # 수정 불가 파일
    FORBIDDEN_FILES = [
        "config.py",
        "reze_permissions.py",
        "fish/infra/boss_approval.py",
        "fish/evolve/self_code.py",  # 자기 자신은 수정 불가
    ]

    def __init__(self, ssot, llm_router=None, sandbox_runner=None, boss_approval=None, checkpoint_mgr=None):
        """
        Args:
            ssot: SSOT 인스턴스
            llm_router: LLM 라우터
            sandbox_runner: 샌드박스 러너
            boss_approval: Boss 승인 게이트
            checkpoint_mgr: 체크포인트 매니저
        """
        self.ssot = ssot
        self.conn = ssot.conn if hasattr(ssot, 'conn') else ssot
        self.llm = llm_router
        self.sandbox = sandbox_runner
        self.boss = boss_approval
        self.checkpoint = checkpoint_mgr
        self.base_path = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

    async def is_active(self) -> bool:
        """활성화 조건 확인: experiment 성공 5회 이상"""
        try:
            row = self.conn.execute("""
                SELECT COUNT(*) FROM experiment_queue
                WHERE status = 'completed' AND result LIKE '%success%'
            """).fetchone()
            return row[0] >= 5
        except:
            return False

    def is_file_allowed(self, filepath: str) -> bool:
        """파일 수정 허용 여부 확인"""
        # 절대 경로를 상대 경로로 변환
        if filepath.startswith(self.base_path):
            filepath = filepath[len(self.base_path):].lstrip("/")

        # 금지 파일 체크
        for forbidden in self.FORBIDDEN_FILES:
            if filepath.endswith(forbidden) or forbidden in filepath:
                return False

        # 허용 패턴 체크
        import fnmatch
        for pattern in self.ALLOWED_FILES:
            if fnmatch.fnmatch(filepath, pattern):
                return True

        return False

    async def analyze_file(self, filepath: str) -> Dict:
        """
        파일 분석.

        Args:
            filepath: 분석할 파일 경로

        Returns:
            분석 결과 (issues, metrics, suggestions)
        """
        if not os.path.exists(filepath):
            return {"error": f"File not found: {filepath}"}

        with open(filepath, "r", encoding="utf-8") as f:
            code = f.read()

        result = {
            "filepath": filepath,
            "lines": len(code.splitlines()),
            "issues": [],
            "metrics": {},
            "suggestions": []
        }

        # 1. 구문 분석
        try:
            tree = ast.parse(code)
            result["syntax_valid"] = True
        except SyntaxError as e:
            result["syntax_valid"] = False
            result["issues"].append(f"Syntax error: {e}")
            return result

        # 2. 복잡도 분석
        result["metrics"] = self._analyze_complexity(tree)

        # 3. 코드 품질 이슈 탐지
        result["issues"].extend(self._detect_issues(tree, code))

        # 4. LLM 기반 개선 제안
        if self.llm and len(result["issues"]) > 0:
            suggestions = await self._get_llm_suggestions(filepath, code, result["issues"])
            result["suggestions"] = suggestions

        return result

    def _analyze_complexity(self, tree: ast.AST) -> Dict:
        """복잡도 메트릭 계산"""
        metrics = {
            "functions": 0,
            "classes": 0,
            "max_depth": 0,
            "avg_function_length": 0
        }

        function_lengths = []

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                metrics["functions"] += 1
                # 함수 길이 (라인 수)
                if hasattr(node, 'end_lineno') and hasattr(node, 'lineno'):
                    length = node.end_lineno - node.lineno + 1
                    function_lengths.append(length)

            elif isinstance(node, ast.ClassDef):
                metrics["classes"] += 1

        if function_lengths:
            metrics["avg_function_length"] = round(sum(function_lengths) / len(function_lengths), 1)
            metrics["max_function_length"] = max(function_lengths)

        return metrics

    def _detect_issues(self, tree: ast.AST, code: str) -> List[str]:
        """코드 이슈 탐지"""
        issues = []

        for node in ast.walk(tree):
            # 너무 긴 함수
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if hasattr(node, 'end_lineno') and hasattr(node, 'lineno'):
                    length = node.end_lineno - node.lineno + 1
                    if length > 100:
                        issues.append(f"Function '{node.name}' is too long ({length} lines)")

            # bare except
            if isinstance(node, ast.ExceptHandler):
                if node.type is None:
                    issues.append(f"Bare 'except:' at line {node.lineno}")

            # TODO 주석
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
                if isinstance(node.value.value, str) and "TODO" in node.value.value:
                    issues.append(f"TODO found at line {node.lineno}")

        # 하드코딩된 값 탐지
        hardcoded_patterns = [
            (r'password\s*=\s*["\'][^"\']+["\']', "Hardcoded password"),
            (r'api_key\s*=\s*["\'][^"\']+["\']', "Hardcoded API key"),
            (r'secret\s*=\s*["\'][^"\']+["\']', "Hardcoded secret"),
        ]

        for pattern, desc in hardcoded_patterns:
            if re.search(pattern, code, re.IGNORECASE):
                issues.append(desc)

        return issues

    async def _get_llm_suggestions(
        self,
        filepath: str,
        code: str,
        issues: List[str]
    ) -> List[Dict]:
        """LLM 기반 개선 제안"""
        if not self.llm:
            return []

        prompt = f"""Analyze this Python code and suggest improvements:

File: {filepath}
Issues found: {issues}

Code (first 2000 chars):
```python
{code[:2000]}
```

Provide 1-3 specific improvement suggestions in JSON:
[
  {{
    "type": "refactor|fix|optimize|security",
    "description": "what to improve",
    "priority": "low|medium|high",
    "estimated_impact": "brief description"
  }}
]"""

        try:
            response = await self.llm.call(
                "cerebras",
                [{"role": "user", "content": prompt}],
                max_tokens=1000
            )

            text = response.text if hasattr(response, 'text') else str(response)
            return json.loads(self._extract_json(text))

        except:
            return []

    async def generate_patch(
        self,
        filepath: str,
        suggestion: Dict,
        context: str = None
    ) -> Optional[CodePatch]:
        """
        개선 제안에 대한 패치 생성.

        Args:
            filepath: 대상 파일
            suggestion: 개선 제안
            context: 추가 컨텍스트

        Returns:
            CodePatch 또는 None
        """
        if not self.is_file_allowed(filepath):
            logger.warning("File not allowed for modification: %s", filepath)
            return None

        if not os.path.exists(filepath):
            return None

        with open(filepath, "r", encoding="utf-8") as f:
            original_code = f.read()

        if not self.llm:
            return None

        prompt = f"""Generate a code patch for this improvement:

File: {filepath}
Suggestion: {json.dumps(suggestion)}
Context: {context or 'None'}

Original code:
```python
{original_code[:4000]}
```

Generate the improved code. Only output the complete improved code, no explanations.
Respond with the full file content:"""

        try:
            response = await self.llm.call(
                "gemini_pro",
                [{"role": "user", "content": prompt}],
                max_tokens=8000
            )

            text = response.text if hasattr(response, 'text') else str(response)
            patched_code = self._extract_code(text)

            if not patched_code or patched_code == original_code:
                return None

            # 구문 검증
            try:
                ast.parse(patched_code)
            except SyntaxError:
                logger.error("Generated patch has syntax error")
                return None

            patch_id = f"patch_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"

            # 리스크 레벨 결정
            risk_level = self._assess_risk(original_code, patched_code, suggestion)

            patch = CodePatch(
                patch_id=patch_id,
                target_file=filepath,
                original_code=original_code,
                patched_code=patched_code,
                description=suggestion.get("description", "Code improvement"),
                risk_level=risk_level
            )

            # DB에 저장
            self.conn.execute("""
                INSERT INTO code_patches
                (patch_id, target_file, original_hash, patched_hash,
                 description, risk_level, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                patch_id,
                filepath,
                hash(original_code),
                hash(patched_code),
                patch.description,
                risk_level,
                "pending",
                datetime.utcnow().isoformat()
            ))
            self.conn.commit()

            return patch

        except Exception as e:
            logger.error("Patch generation failed: %s", e)
            return None

    def _assess_risk(
        self,
        original: str,
        patched: str,
        suggestion: Dict
    ) -> str:
        """리스크 레벨 평가"""
        # diff 크기 계산
        diff = list(difflib.unified_diff(
            original.splitlines(),
            patched.splitlines(),
            lineterm=""
        ))
        diff_size = len([l for l in diff if l.startswith('+') or l.startswith('-')])

        # 변경 비율
        change_ratio = diff_size / max(len(original.splitlines()), 1)

        # 제안 우선순위
        priority = suggestion.get("priority", "medium")

        if change_ratio > 0.5 or diff_size > 200:
            return "CRITICAL"
        elif change_ratio > 0.2 or diff_size > 100 or priority == "high":
            return "HIGH"
        elif change_ratio > 0.1 or diff_size > 50:
            return "MEDIUM"
        else:
            return "LOW"

    async def test_patch(self, patch: CodePatch) -> Dict:
        """
        패치 샌드박스 테스트.

        Args:
            patch: 테스트할 패치

        Returns:
            테스트 결과
        """
        if not self.sandbox:
            # 샌드박스 없으면 구문 검증만
            try:
                ast.parse(patch.patched_code)
                return {"passed": True, "method": "syntax_only"}
            except SyntaxError as e:
                return {"passed": False, "error": str(e)}

        patch.status = "testing"

        result = await self.sandbox.run_code_patch(
            patch.patch_id,
            patch.target_file,
            patch.original_code,
            patch.patched_code
        )

        patch.test_result = {
            "passed": result.success,
            "exit_code": result.exit_code,
            "stdout": result.stdout[:500] if result.stdout else "",
            "stderr": result.stderr[:500] if result.stderr else "",
            "duration": result.duration_sec
        }

        # DB 업데이트
        self.conn.execute("""
            UPDATE code_patches
            SET test_result = ?, status = ?
            WHERE patch_id = ?
        """, (
            json.dumps(patch.test_result),
            "tested" if result.success else "test_failed",
            patch.patch_id
        ))
        self.conn.commit()

        return patch.test_result

    async def apply_patch(self, patch: CodePatch, force: bool = False) -> Tuple[bool, str]:
        """
        패치 적용.

        Args:
            patch: 적용할 패치
            force: 승인 무시 여부 (위험)

        Returns:
            (성공 여부, 메시지)
        """
        # 1. 파일 허용 여부 재확인
        if not self.is_file_allowed(patch.target_file):
            return False, "File not allowed for modification"

        # 2. 테스트 통과 확인
        if not patch.test_result or not patch.test_result.get("passed"):
            return False, "Patch must pass tests first"

        # 3. Boss 승인 (HIGH/CRITICAL)
        if patch.risk_level in ("HIGH", "CRITICAL") and not force:
            if self.boss:
                request = self.boss.request_approval(
                    module="self_code",
                    action="apply_patch",
                    description=f"Apply {patch.risk_level} risk patch to {patch.target_file}",
                    payload={
                        "patch_id": patch.patch_id,
                        "description": patch.description,
                        "diff_preview": self._get_diff_preview(patch)
                    }
                )

                if not self.boss.is_approved(request.request_id):
                    return False, f"Awaiting boss approval: {request.request_id}"

        # 4. 체크포인트 생성
        checkpoint_id = None
        if self.checkpoint:
            checkpoint_id = self.checkpoint.create(
                module="self_code",
                action=f"apply_patch_{patch.patch_id}",
                files=[patch.target_file],
                tables=["code_patches"]
            )

        # 5. 패치 적용
        try:
            # 현재 파일 내용 확인 (다른 변경 있었는지)
            with open(patch.target_file, "r", encoding="utf-8") as f:
                current_code = f.read()

            if current_code != patch.original_code:
                return False, "File has been modified since patch was generated"

            # 패치 적용
            with open(patch.target_file, "w", encoding="utf-8") as f:
                f.write(patch.patched_code)

            patch.status = "applied"

            # DB 업데이트
            self.conn.execute("""
                UPDATE code_patches
                SET status = ?, applied_at = ?, checkpoint_id = ?
                WHERE patch_id = ?
            """, (
                "applied",
                datetime.utcnow().isoformat(),
                checkpoint_id,
                patch.patch_id
            ))
            self.conn.commit()

            logger.info("Patch %s applied to %s", patch.patch_id, patch.target_file)
            return True, f"Patch applied successfully (checkpoint: {checkpoint_id})"

        except Exception as e:
            logger.error("Failed to apply patch: %s", e)

            # 롤백
            if checkpoint_id and self.checkpoint:
                self.checkpoint.rollback(checkpoint_id)

            return False, f"Failed to apply patch: {e}"

    async def rollback_patch(self, patch_id: str) -> Tuple[bool, str]:
        """패치 롤백"""
        try:
            row = self.conn.execute(
                "SELECT checkpoint_id, target_file FROM code_patches WHERE patch_id = ?",
                (patch_id,)
            ).fetchone()

            if not row:
                return False, "Patch not found"

            checkpoint_id, target_file = row

            if checkpoint_id and self.checkpoint:
                success = self.checkpoint.rollback(checkpoint_id)
                if success:
                    self.conn.execute(
                        "UPDATE code_patches SET status = ? WHERE patch_id = ?",
                        ("rolled_back", patch_id)
                    )
                    self.conn.commit()
                    return True, "Patch rolled back"

            return False, "No checkpoint available for rollback"

        except Exception as e:
            return False, f"Rollback failed: {e}"

    def _get_diff_preview(self, patch: CodePatch, context_lines: int = 3) -> str:
        """diff 프리뷰 생성"""
        diff = difflib.unified_diff(
            patch.original_code.splitlines(),
            patch.patched_code.splitlines(),
            fromfile=f"a/{patch.target_file}",
            tofile=f"b/{patch.target_file}",
            lineterm="",
            n=context_lines
        )
        return "\n".join(list(diff)[:50])  # 최대 50줄

    def _extract_json(self, text: str) -> str:
        """텍스트에서 JSON 추출"""
        if "```json" in text:
            return text.split("```json")[1].split("```")[0].strip()

        start = text.find("[")
        end = text.rfind("]") + 1

        if start >= 0 and end > start:
            return text[start:end]

        return "[]"

    def _extract_code(self, text: str) -> str:
        """텍스트에서 코드 추출"""
        if "```python" in text:
            return text.split("```python")[1].split("```")[0].strip()

        if "```" in text:
            return text.split("```")[1].split("```")[0].strip()

        return text.strip()

    def get_pending_patches(self) -> List[Dict]:
        """대기 중인 패치 목록"""
        try:
            rows = self.conn.execute("""
                SELECT patch_id, target_file, description, risk_level, status, created_at
                FROM code_patches
                WHERE status IN ('pending', 'tested')
                ORDER BY created_at DESC
            """).fetchall()

            return [
                {
                    "patch_id": r[0],
                    "target_file": r[1],
                    "description": r[2],
                    "risk_level": r[3],
                    "status": r[4],
                    "created_at": r[5]
                }
                for r in rows
            ]
        except:
            return []

    def get_recent_patches(self, limit: int = 20) -> List[Dict]:
        """최근 패치 목록"""
        try:
            rows = self.conn.execute("""
                SELECT patch_id, target_file, description, risk_level,
                       status, created_at, applied_at
                FROM code_patches
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,)).fetchall()

            return [
                {
                    "patch_id": r[0],
                    "target_file": r[1],
                    "description": r[2],
                    "risk_level": r[3],
                    "status": r[4],
                    "created_at": r[5],
                    "applied_at": r[6]
                }
                for r in rows
            ]
        except:
            return []
