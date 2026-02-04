"""Agentless Step 2: 패치 생성 및 적용.

LLM을 사용하여 다중 패치를 생성하고,
code_edit 도구로 코드를 수정합니다.
"""
import re
import json
import uuid
from typing import Optional, Callable, Awaitable, Any
from dataclasses import dataclass

import logging
logger = logging.getLogger("REZE.agentless")

# 순환 import 방지
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from agentless.localizer import Localization


@dataclass
class Patch:
    """패치 정보."""
    file_path: str
    old_code: str
    new_code: str
    explanation: str
    patch_id: str

    @classmethod
    def create(cls, file_path: str, old_code: str, new_code: str, explanation: str) -> "Patch":
        return cls(
            file_path=file_path,
            old_code=old_code,
            new_code=new_code,
            explanation=explanation,
            patch_id=str(uuid.uuid4())[:8]
        )


class BugRepairer:
    """LLM 기반 패치 생성 및 적용."""

    def __init__(self, tools, llm_fn: Callable[..., Awaitable[Any]]):
        """
        Args:
            tools: ToolExecutor 인스턴스
            llm_fn: LLM 호출 함수 (router.call)
        """
        self.tools = tools
        self.llm_fn = llm_fn

    async def generate_patches(
        self,
        localization: "Localization",
        bug_description: str,
        context_files: list[str] = None,
        num_patches: int = 3
    ) -> list[Patch]:
        """
        다중 패치 생성.

        Args:
            localization: 버그 위치 정보
            bug_description: 버그 설명
            context_files: 추가 컨텍스트 파일들
            num_patches: 생성할 패치 수

        Returns:
            Patch 리스트
        """
        logger.info(f"[REPAIR] Generating {num_patches} patches for {localization.file_path}")

        # 컨텍스트 수집
        context = await self._gather_context(localization, context_files)

        # LLM으로 패치 생성
        prompt = f"""버그를 수정하는 패치를 {num_patches}개 생성해주세요.

## 버그 설명
{bug_description}

## 버그 위치: {localization.file_path} (lines {localization.start_line}-{localization.end_line})
```python
{localization.code_snippet}
```

## 버그 원인 가설
{localization.hypothesis}

{context}

## 응답 형식 (JSON 배열)
[
    {{
        "old_code": "교체할 기존 코드 (정확히 일치해야 함)",
        "new_code": "새로운 코드",
        "explanation": "수정 설명"
    }},
    ...
]

## 주의사항
- old_code는 파일에 존재하는 코드와 정확히 일치해야 합니다
- old_code는 고유해야 합니다 (파일에서 한 번만 등장)
- 들여쓰기와 공백을 정확히 유지하세요
- 최소한의 변경으로 버그를 수정하세요
"""

        try:
            response = await self.llm_fn(
                "creation",
                [{"role": "user", "content": prompt}],
                system="코드 수정 전문가. 정확한 JSON 배열만 응답. 마크다운 금지."
            )

            # JSON 배열 추출
            json_match = re.search(r'\[[\s\S]*\]', response.text)
            if json_match:
                patches_data = json.loads(json_match.group())
                patches = []
                for p in patches_data[:num_patches]:
                    if p.get("old_code") and p.get("new_code"):
                        patch = Patch.create(
                            file_path=localization.file_path,
                            old_code=p["old_code"],
                            new_code=p["new_code"],
                            explanation=p.get("explanation", "No explanation")
                        )
                        patches.append(patch)
                        logger.info(f"[REPAIR] Generated patch {patch.patch_id}: {patch.explanation[:50]}")
                return patches

        except Exception as e:
            logger.error(f"[REPAIR] Failed to generate patches: {e}")

        return []

    async def apply_patch(self, patch: Patch) -> dict:
        """
        code_edit으로 패치 적용.

        Args:
            patch: 적용할 패치

        Returns:
            {"success": bool, "message": str}
        """
        logger.info(f"[REPAIR] Applying patch {patch.patch_id} to {patch.file_path}")

        # code_edit edit 모드로 적용
        result = await self.tools.execute(
            "code_edit",
            {
                "action": "edit",
                "path": patch.file_path,
                "old_str": patch.old_code,
                "new_str": patch.new_code
            },
            source="agentless"
        )

        if result.startswith("OK"):
            logger.info(f"[REPAIR] Patch {patch.patch_id} applied successfully")
            return {"success": True, "message": result}
        else:
            logger.warning(f"[REPAIR] Patch {patch.patch_id} failed: {result}")
            return {"success": False, "message": result}

    async def syntax_check(self, file_path: str) -> dict:
        """
        Python AST로 구문 검사.

        Args:
            file_path: 검사할 파일

        Returns:
            {"valid": bool, "error": str}
        """
        ast_code = f'''
import ast
import json

try:
    with open("{file_path}", "r") as f:
        code = f.read()
    ast.parse(code)
    print(json.dumps({{"valid": True, "error": None}}))
except SyntaxError as e:
    print(json.dumps({{"valid": False, "error": f"{{e.msg}} at line {{e.lineno}}"}}))
except Exception as e:
    print(json.dumps({{"valid": False, "error": str(e)}}))
'''
        result = await self.tools.execute("python", ast_code, source="agentless")

        try:
            return json.loads(result.strip())
        except:
            return {"valid": False, "error": "Failed to parse result"}

    async def rollback(self, patch: Patch) -> bool:
        """
        패치 롤백 (new → old 교체).

        Args:
            patch: 롤백할 패치

        Returns:
            성공 여부
        """
        logger.info(f"[REPAIR] Rolling back patch {patch.patch_id}")

        # 역방향 교체
        result = await self.tools.execute(
            "code_edit",
            {
                "action": "edit",
                "path": patch.file_path,
                "old_str": patch.new_code,
                "new_str": patch.old_code
            },
            source="agentless"
        )

        if result.startswith("OK"):
            logger.info(f"[REPAIR] Patch {patch.patch_id} rolled back successfully")
            return True
        else:
            logger.error(f"[REPAIR] Failed to rollback patch {patch.patch_id}: {result}")
            return False

    async def _gather_context(
        self,
        localization: "Localization",
        context_files: list[str] = None
    ) -> str:
        """관련 컨텍스트 수집."""
        context_parts = []

        # import 문 추출
        import_result = await self.tools.execute(
            "shell",
            f'grep -n "^import\\|^from" "{localization.file_path}" | head -20',
            source="agentless"
        )
        if not import_result.startswith("ERROR"):
            context_parts.append(f"## Imports\n```\n{import_result}\n```")

        # 추가 컨텍스트 파일
        if context_files:
            for ctx_file in context_files[:2]:  # 최대 2개
                read_result = await self.tools.execute(
                    "code_edit",
                    {"action": "read", "path": ctx_file, "line_range": [1, 50]},
                    source="agentless"
                )
                if not read_result.startswith("ERROR"):
                    context_parts.append(f"## Context: {ctx_file}\n```python\n{read_result[:1000]}\n```")

        return "\n\n".join(context_parts) if context_parts else ""
