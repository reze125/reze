"""Agentless Step 1: 버그 위치 탐지.

계층적 탐색으로 버그 위치를 좁혀감:
1. 파일 수준: grep으로 관련 파일 식별
2. 함수 수준: AST로 함수/클래스 구조 파악
3. 라인 수준: LLM으로 정확한 위치 특정
"""
import re
import json
from typing import Optional, Callable, Awaitable, Any
from dataclasses import dataclass, field

import logging
logger = logging.getLogger("REZE.agentless")


@dataclass
class Localization:
    """버그 위치 정보."""
    file_path: str
    start_line: int
    end_line: int
    code_snippet: str
    hypothesis: str  # 버그 원인 가설
    confidence: float = 0.5  # 0.0 ~ 1.0


class BugLocalizer:
    """계층적 버그 위치 탐지."""

    def __init__(self, tools, llm_fn: Callable[..., Awaitable[Any]]):
        """
        Args:
            tools: ToolExecutor 인스턴스
            llm_fn: LLM 호출 함수 (router.call)
        """
        self.tools = tools
        self.llm_fn = llm_fn

    async def localize(
        self,
        bug_description: str,
        repo_path: str,
        error_trace: Optional[str] = None,
        max_files: int = 5
    ) -> list[Localization]:
        """
        버그 위치 탐지.

        Args:
            bug_description: 버그 설명
            repo_path: 레포지토리 경로
            error_trace: 에러 트레이스 (선택적)
            max_files: 탐색할 최대 파일 수

        Returns:
            Localization 리스트 (신뢰도 순)
        """
        logger.info(f"[LOCALIZE] Starting bug localization in {repo_path}")

        # 1. 에러 트레이스에서 파일:라인 추출
        if error_trace:
            trace_locs = self._parse_error_trace(error_trace)
            if trace_locs:
                logger.info(f"[LOCALIZE] Found {len(trace_locs)} locations from error trace")
                return await self._refine_locations(trace_locs, bug_description, repo_path)

        # 2. 키워드 기반 파일 검색
        keywords = await self._extract_keywords(bug_description)
        logger.info(f"[LOCALIZE] Extracted keywords: {keywords}")

        files = await self._find_files(keywords, repo_path, max_files)
        if not files:
            logger.warning("[LOCALIZE] No relevant files found")
            return []

        logger.info(f"[LOCALIZE] Found {len(files)} candidate files")

        # 3. 각 파일에서 함수/라인 분석
        localizations = []
        for file_path in files[:max_files]:
            loc = await self._analyze_file(file_path, bug_description, keywords)
            if loc:
                localizations.append(loc)

        # 4. 신뢰도순 정렬
        localizations.sort(key=lambda x: x.confidence, reverse=True)
        return localizations

    def _parse_error_trace(self, error_trace: str) -> list[dict]:
        """에러 트레이스에서 파일:라인 정보 추출."""
        # Python 트레이스백 패턴: File "path", line N
        pattern = r'File ["\']([^"\']+)["\'],\s*line\s*(\d+)'
        matches = re.findall(pattern, error_trace)

        locations = []
        for file_path, line_no in matches:
            locations.append({
                "file_path": file_path,
                "line": int(line_no)
            })
        return locations

    async def _extract_keywords(self, bug_description: str) -> list[str]:
        """버그 설명에서 핵심 키워드 추출."""
        # 간단한 키워드 추출: 코드 관련 단어
        code_patterns = [
            r'`([^`]+)`',  # 백틱 안 코드
            r'"([^"]+)"',  # 따옴표 안 텍스트
            r"'([^']+)'",  # 작은따옴표 안 텍스트
            r'\b([A-Z][a-z]+[A-Z]\w*)\b',  # CamelCase
            r'\b([a-z]+_[a-z_]+)\b',  # snake_case
        ]

        keywords = set()
        for pattern in code_patterns:
            matches = re.findall(pattern, bug_description)
            keywords.update(matches)

        # 에러 타입 추출
        error_types = [
            "TypeError", "ValueError", "AttributeError", "KeyError",
            "IndexError", "ImportError", "NameError", "RuntimeError",
            "Exception", "Error"
        ]
        for err in error_types:
            if err.lower() in bug_description.lower():
                keywords.add(err)

        # 최소 키워드 보장
        if not keywords:
            # 단어 토큰화 (3글자 이상)
            words = re.findall(r'\b\w{3,}\b', bug_description)
            keywords.update(words[:5])

        return list(keywords)[:10]

    async def _find_files(
        self,
        keywords: list[str],
        repo_path: str,
        max_files: int
    ) -> list[str]:
        """grep으로 관련 파일 검색."""
        files_found = set()

        for keyword in keywords[:5]:  # 상위 5개 키워드만
            # grep으로 키워드 포함 파일 검색
            grep_cmd = f'grep -rl "{keyword}" "{repo_path}" --include="*.py" 2>/dev/null | head -10'
            result = await self.tools.execute("shell", grep_cmd, source="agentless")

            if not result.startswith("ERROR"):
                for line in result.strip().split('\n'):
                    if line and line.endswith('.py'):
                        files_found.add(line.strip())

        return list(files_found)[:max_files]

    async def _analyze_file(
        self,
        file_path: str,
        bug_description: str,
        keywords: list[str]
    ) -> Optional[Localization]:
        """파일 분석하여 버그 위치 특정."""
        # 파일 읽기
        read_result = await self.tools.execute(
            "code_edit",
            {"action": "read", "path": file_path},
            source="agentless"
        )

        if read_result.startswith("ERROR"):
            return None

        # 함수 구조 추출 (AST)
        functions = await self._extract_functions(file_path)

        # LLM으로 버그 위치 분석
        prompt = f"""아래 파일에서 버그 위치를 찾아주세요.

## 버그 설명
{bug_description}

## 파일: {file_path}
```python
{read_result[:3000]}
```

## 함수 목록
{json.dumps(functions, indent=2, ensure_ascii=False) if functions else "N/A"}

## 응답 형식 (JSON)
{{
    "found": true/false,
    "start_line": 숫자,
    "end_line": 숫자,
    "hypothesis": "버그 원인 가설",
    "confidence": 0.0~1.0
}}
"""

        try:
            response = await self.llm_fn(
                "analysis",
                [{"role": "user", "content": prompt}],
                system="버그 위치 분석 전문가. JSON만 응답."
            )

            # JSON 추출
            json_match = re.search(r'\{[^{}]*\}', response.text, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                if data.get("found"):
                    # 코드 스니펫 추출
                    start = max(1, data.get("start_line", 1))
                    end = data.get("end_line", start + 10)
                    snippet_result = await self.tools.execute(
                        "code_edit",
                        {"action": "read", "path": file_path, "line_range": [start, end]},
                        source="agentless"
                    )

                    return Localization(
                        file_path=file_path,
                        start_line=start,
                        end_line=end,
                        code_snippet=snippet_result[:1000],
                        hypothesis=data.get("hypothesis", "Unknown"),
                        confidence=float(data.get("confidence", 0.5))
                    )
        except Exception as e:
            logger.warning(f"[LOCALIZE] Failed to analyze {file_path}: {e}")

        return None

    async def _extract_functions(self, file_path: str) -> list[dict]:
        """AST로 함수/클래스 목록 추출."""
        ast_code = f'''
import ast
import json

try:
    with open("{file_path}", "r") as f:
        tree = ast.parse(f.read())

    functions = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            functions.append({{
                "type": "function",
                "name": node.name,
                "line": node.lineno,
                "end_line": getattr(node, "end_lineno", node.lineno + 10)
            }})
        elif isinstance(node, ast.ClassDef):
            functions.append({{
                "type": "class",
                "name": node.name,
                "line": node.lineno,
                "end_line": getattr(node, "end_lineno", node.lineno + 50)
            }})
    print(json.dumps(functions))
except Exception as e:
    print(json.dumps([]))
'''
        result = await self.tools.execute("python", ast_code, source="agentless")

        try:
            return json.loads(result.strip())
        except:
            return []

    async def _refine_locations(
        self,
        trace_locs: list[dict],
        bug_description: str,
        repo_path: str
    ) -> list[Localization]:
        """트레이스 위치를 Localization으로 변환."""
        localizations = []

        for loc in trace_locs[:3]:  # 최대 3개
            file_path = loc["file_path"]
            line = loc["line"]

            # 파일이 repo_path 내에 있는지 확인
            if not file_path.startswith(repo_path):
                continue

            # 주변 코드 읽기
            start = max(1, line - 5)
            end = line + 10
            snippet_result = await self.tools.execute(
                "code_edit",
                {"action": "read", "path": file_path, "line_range": [start, end]},
                source="agentless"
            )

            if snippet_result.startswith("ERROR"):
                continue

            localizations.append(Localization(
                file_path=file_path,
                start_line=start,
                end_line=end,
                code_snippet=snippet_result,
                hypothesis=f"Error occurred at line {line}",
                confidence=0.9  # 트레이스에서 직접 추출했으므로 높은 신뢰도
            ))

        return localizations
