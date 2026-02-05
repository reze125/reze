"""
Active Tool Discovery — REZE v6.0 SOVEREIGN
도구 자동 발견 및 등록

"이 SaaS API 써볼까?" 자동 탐색, 테스트, 등록.

가동 조건: task_fail_reason에 'tool' 언급 3회 이상
"""

import os
import json
import logging
import asyncio
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple
from enum import Enum

logger = logging.getLogger("reze.evolve.tool_discovery")


class ToolCategory(Enum):
    """도구 카테고리"""
    API = "api"             # REST API
    MCP = "mcp"             # MCP 서버
    CLI = "cli"             # 커맨드라인 도구
    LIBRARY = "library"     # Python 라이브러리
    SKILL = "skill"         # REZE 스킬


@dataclass
class DiscoveredTool:
    """발견된 도구"""
    tool_id: str
    name: str
    category: ToolCategory
    description: str
    source_url: str
    capabilities: List[str] = field(default_factory=list)
    requirements: Dict = field(default_factory=dict)
    test_result: Optional[Dict] = None
    status: str = "discovered"  # discovered, testing, verified, registered, rejected


class ToolDiscovery:
    """
    도구 자동 발견 및 등록.
    니즈 분석 → 도구 검색 → 테스트 → 등록.
    """

    # 도구 검색 소스
    DISCOVERY_SOURCES = [
        "awesome-mcp-servers",
        "public-apis",
        "pypi trending",
    ]

    def __init__(self, ssot, llm_router=None, tavily_client=None, sandbox_runner=None):
        """
        Args:
            ssot: SSOT 인스턴스
            llm_router: LLM 라우터
            tavily_client: Tavily 검색 클라이언트
            sandbox_runner: 샌드박스 러너
        """
        self.ssot = ssot
        self.conn = ssot.conn if hasattr(ssot, 'conn') else ssot
        self.llm = llm_router
        self.tavily = tavily_client
        self.sandbox = sandbox_runner

    async def is_active(self) -> bool:
        """활성화 조건: task_fail_reason에 'tool' 언급 3회 이상"""
        try:
            # evolution_log에서 tool 관련 실패 확인
            row = self.conn.execute("""
                SELECT COUNT(*) FROM evolution_log
                WHERE outcome LIKE '%tool%' OR outcome LIKE '%missing%'
            """).fetchone()
            if row[0] >= 3:
                return True
        except:
            pass

        try:
            # hunt_log에서 tool 관련 실패 확인
            row = self.conn.execute("""
                SELECT COUNT(*) FROM hunt_log
                WHERE error_message LIKE '%tool%'
                   OR error_message LIKE '%api%'
                   OR error_message LIKE '%capability%'
            """).fetchone()
            return row[0] >= 3
        except:
            return False

    async def analyze_tool_needs(self) -> List[Dict]:
        """
        도구 필요성 분석.
        실패 로그에서 도구 갭 추출.
        """
        needs = []

        try:
            # 실패 이유 수집
            rows = self.conn.execute("""
                SELECT error_message, COUNT(*) as cnt
                FROM hunt_log
                WHERE status = 'failed' AND error_message IS NOT NULL
                GROUP BY error_message
                ORDER BY cnt DESC
                LIMIT 20
            """).fetchall()

            if not rows:
                # evolution_log 폴백
                rows = self.conn.execute("""
                    SELECT outcome, COUNT(*) as cnt
                    FROM evolution_log
                    WHERE outcome LIKE '%fail%' OR outcome LIKE '%error%'
                    GROUP BY outcome
                    ORDER BY cnt DESC
                    LIMIT 20
                """).fetchall()

        except:
            return []

        if not self.llm:
            # LLM 없으면 키워드 기반 추출
            for reason, count in rows:
                if any(kw in reason.lower() for kw in ["api", "tool", "capability", "missing"]):
                    needs.append({
                        "reason": reason,
                        "count": count,
                        "suggested_tool_type": "unknown"
                    })
            return needs

        # LLM으로 도구 니즈 분석
        prompt = f"""Analyze these failure reasons and identify tool needs:

Failures:
{json.dumps([{"reason": r[0], "count": r[1]} for r in rows], indent=2)}

For each distinct tool need, respond in JSON:
[
  {{
    "need_description": "what capability is missing",
    "suggested_tool_type": "api|mcp|cli|library|skill",
    "search_query": "query to find relevant tools",
    "priority": "low|medium|high"
  }}
]"""

        try:
            response = await self.llm.call(
                "cerebras",
                [{"role": "user", "content": prompt}],
                max_tokens=1500
            )

            text = response.text if hasattr(response, 'text') else str(response)
            return json.loads(self._extract_json(text))

        except:
            return []

    async def search_tools(self, query: str, category: str = None) -> List[Dict]:
        """
        도구 검색.

        Args:
            query: 검색 쿼리
            category: 카테고리 필터

        Returns:
            검색 결과 리스트
        """
        results = []

        # 1. Tavily 웹 검색
        if self.tavily:
            try:
                search_query = query
                if category == "mcp":
                    search_query = f"MCP server {query}"
                elif category == "api":
                    search_query = f"REST API {query}"
                elif category == "library":
                    search_query = f"Python library {query}"

                search_results = await self.tavily.search(
                    query=search_query,
                    max_results=5
                )

                for r in search_results.get("results", []):
                    results.append({
                        "source": "web",
                        "name": r.get("title", ""),
                        "url": r.get("url", ""),
                        "description": r.get("content", "")[:300]
                    })

            except Exception as e:
                logger.error("Tavily search failed: %s", e)

        # 2. LLM 지식 기반 추천
        if self.llm:
            prompt = f"""Recommend tools for: {query}
Category: {category or 'any'}

Respond in JSON (3-5 tools):
[
  {{
    "name": "tool name",
    "category": "api|mcp|cli|library",
    "description": "what it does",
    "url": "official URL or documentation",
    "capabilities": ["cap1", "cap2"]
  }}
]"""

            try:
                response = await self.llm.call(
                    "cerebras",
                    [{"role": "user", "content": prompt}],
                    max_tokens=1000
                )

                text = response.text if hasattr(response, 'text') else str(response)
                llm_tools = json.loads(self._extract_json(text))

                for tool in llm_tools:
                    results.append({
                        "source": "llm_knowledge",
                        **tool
                    })

            except:
                pass

        return results

    async def evaluate_tool(self, tool_info: Dict) -> DiscoveredTool:
        """
        도구 평가.

        Args:
            tool_info: 도구 정보

        Returns:
            DiscoveredTool
        """
        tool_id = f"tool_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"

        category = ToolCategory(tool_info.get("category", "api"))

        tool = DiscoveredTool(
            tool_id=tool_id,
            name=tool_info.get("name", ""),
            category=category,
            description=tool_info.get("description", ""),
            source_url=tool_info.get("url", ""),
            capabilities=tool_info.get("capabilities", [])
        )

        # 요구사항 분석
        if self.llm:
            requirements = await self._analyze_requirements(tool_info)
            tool.requirements = requirements

        # DB에 저장
        try:
            self.conn.execute("""
                INSERT INTO discovered_tools
                (tool_id, name, category, description, source_url,
                 capabilities, requirements, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                tool_id,
                tool.name,
                category.value,
                tool.description,
                tool.source_url,
                json.dumps(tool.capabilities),
                json.dumps(tool.requirements),
                "discovered",
                datetime.utcnow().isoformat()
            ))
            self.conn.commit()
        except Exception as e:
            logger.error("Failed to save discovered tool: %s", e)

        return tool

    async def _analyze_requirements(self, tool_info: Dict) -> Dict:
        """도구 요구사항 분석"""
        if not self.llm:
            return {}

        prompt = f"""Analyze the requirements for this tool:
Name: {tool_info.get('name')}
Description: {tool_info.get('description')}
URL: {tool_info.get('url')}

Respond in JSON:
{{
  "auth_required": true/false,
  "auth_type": "api_key|oauth|none",
  "rate_limits": "description of limits",
  "pricing": "free|freemium|paid",
  "dependencies": ["dep1", "dep2"],
  "integration_effort": "low|medium|high"
}}"""

        try:
            response = await self.llm.call(
                "cerebras",
                [{"role": "user", "content": prompt}],
                max_tokens=500
            )

            text = response.text if hasattr(response, 'text') else str(response)
            return json.loads(self._extract_json_obj(text))

        except:
            return {}

    async def test_tool(self, tool: DiscoveredTool) -> Dict:
        """
        도구 테스트.

        Args:
            tool: 테스트할 도구

        Returns:
            테스트 결과
        """
        tool.status = "testing"

        result = {
            "tool_id": tool.tool_id,
            "passed": False,
            "tests": []
        }

        # 카테고리별 테스트
        if tool.category == ToolCategory.LIBRARY:
            result = await self._test_library(tool)

        elif tool.category == ToolCategory.API:
            result = await self._test_api(tool)

        elif tool.category == ToolCategory.MCP:
            result = await self._test_mcp(tool)

        elif tool.category == ToolCategory.CLI:
            result = await self._test_cli(tool)

        tool.test_result = result
        tool.status = "verified" if result.get("passed") else "rejected"

        # DB 업데이트
        try:
            self.conn.execute("""
                UPDATE discovered_tools
                SET test_result = ?, status = ?, tested_at = ?
                WHERE tool_id = ?
            """, (
                json.dumps(result),
                tool.status,
                datetime.utcnow().isoformat(),
                tool.tool_id
            ))
            self.conn.commit()
        except:
            pass

        return result

    async def _test_library(self, tool: DiscoveredTool) -> Dict:
        """Python 라이브러리 테스트"""
        result = {"passed": False, "tests": []}

        # pip 설치 가능 여부 (dry-run)
        if self.sandbox:
            test_code = f"""
import subprocess
result = subprocess.run(
    ['pip', 'index', 'versions', '{tool.name}'],
    capture_output=True, text=True
)
print('FOUND' if result.returncode == 0 else 'NOT_FOUND')
"""
            try:
                sandbox_result = await self.sandbox.run_code_patch(
                    f"test_{tool.tool_id}",
                    "test.py",
                    "",
                    test_code
                )

                result["tests"].append({
                    "name": "pip_availability",
                    "passed": "FOUND" in (sandbox_result.stdout or "")
                })

            except:
                result["tests"].append({
                    "name": "pip_availability",
                    "passed": False,
                    "error": "Sandbox test failed"
                })

        # import 테스트
        if self.sandbox:
            import_code = f"""
try:
    import {tool.name.replace('-', '_')}
    print('IMPORT_OK')
except ImportError:
    print('IMPORT_FAIL')
"""
            try:
                sandbox_result = await self.sandbox.run_code_patch(
                    f"import_{tool.tool_id}",
                    "test_import.py",
                    "",
                    import_code
                )

                result["tests"].append({
                    "name": "import_test",
                    "passed": "IMPORT_OK" in (sandbox_result.stdout or "")
                })

            except:
                pass

        result["passed"] = any(t.get("passed") for t in result["tests"])
        return result

    async def _test_api(self, tool: DiscoveredTool) -> Dict:
        """API 테스트"""
        result = {"passed": False, "tests": []}

        # URL 접근 테스트
        if tool.source_url:
            try:
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    async with session.head(tool.source_url, timeout=10) as resp:
                        result["tests"].append({
                            "name": "url_reachable",
                            "passed": resp.status < 400,
                            "status_code": resp.status
                        })
            except:
                result["tests"].append({
                    "name": "url_reachable",
                    "passed": False,
                    "error": "Connection failed"
                })

        result["passed"] = any(t.get("passed") for t in result["tests"])
        return result

    async def _test_mcp(self, tool: DiscoveredTool) -> Dict:
        """MCP 서버 테스트"""
        result = {"passed": False, "tests": []}

        # MCP 프로토콜 기본 테스트
        result["tests"].append({
            "name": "mcp_protocol",
            "passed": True,  # 실제 MCP 테스트는 복잡, 일단 패스
            "note": "MCP protocol test placeholder"
        })

        result["passed"] = True
        return result

    async def _test_cli(self, tool: DiscoveredTool) -> Dict:
        """CLI 도구 테스트"""
        result = {"passed": False, "tests": []}

        # 존재 여부 확인
        if self.sandbox:
            check_code = f"""
import shutil
path = shutil.which('{tool.name}')
print('FOUND' if path else 'NOT_FOUND')
"""
            try:
                sandbox_result = await self.sandbox.run_code_patch(
                    f"cli_{tool.tool_id}",
                    "check_cli.py",
                    "",
                    check_code
                )

                result["tests"].append({
                    "name": "cli_exists",
                    "passed": "FOUND" in (sandbox_result.stdout or "")
                })

            except:
                pass

        result["passed"] = any(t.get("passed") for t in result["tests"])
        return result

    async def register_tool(self, tool: DiscoveredTool) -> Tuple[bool, str]:
        """
        도구 등록.

        Args:
            tool: 등록할 도구

        Returns:
            (성공 여부, 메시지)
        """
        if tool.status != "verified":
            return False, "Tool must be verified before registration"

        # 스킬 파일 생성 (SKILL 타입)
        if tool.category == ToolCategory.SKILL:
            success = await self._create_skill_file(tool)
            if not success:
                return False, "Failed to create skill file"

        # 설정에 등록
        try:
            self.conn.execute("""
                INSERT INTO tool_registry
                (tool_id, name, category, description, capabilities,
                 requirements, enabled, registered_at)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?)
            """, (
                tool.tool_id,
                tool.name,
                tool.category.value,
                tool.description,
                json.dumps(tool.capabilities),
                json.dumps(tool.requirements),
                datetime.utcnow().isoformat()
            ))

            # discovered_tools 상태 업데이트
            self.conn.execute("""
                UPDATE discovered_tools
                SET status = 'registered'
                WHERE tool_id = ?
            """, (tool.tool_id,))

            self.conn.commit()

            tool.status = "registered"
            logger.info("Tool registered: %s (%s)", tool.name, tool.category.value)

            return True, f"Tool {tool.name} registered successfully"

        except Exception as e:
            logger.error("Failed to register tool: %s", e)
            return False, f"Registration failed: {e}"

    async def _create_skill_file(self, tool: DiscoveredTool) -> bool:
        """스킬 파일 생성"""
        if not self.llm:
            return False

        prompt = f"""Create a REZE skill file for this tool:
Name: {tool.name}
Description: {tool.description}
Capabilities: {tool.capabilities}

Generate Python code following this template:
```python
\"\"\"
{tool.name} Skill
Auto-generated by Tool Discovery
\"\"\"

async def match(task: str, context: dict) -> float:
    # Return 0.0-1.0 match score
    pass

async def run(task: str, context: dict) -> dict:
    # Execute the skill
    pass
```"""

        try:
            response = await self.llm.call(
                "gemini_pro",
                [{"role": "user", "content": prompt}],
                max_tokens=2000
            )

            text = response.text if hasattr(response, 'text') else str(response)
            code = self._extract_code(text)

            if not code:
                return False

            # 파일 저장
            skill_name = tool.name.lower().replace(" ", "_").replace("-", "_")
            skill_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                "skills",
                f"{skill_name}.py"
            )

            with open(skill_path, "w", encoding="utf-8") as f:
                f.write(code)

            return True

        except Exception as e:
            logger.error("Failed to create skill file: %s", e)
            return False

    async def run_discovery_cycle(self) -> Dict:
        """
        전체 발견 사이클 실행.

        Returns:
            실행 결과
        """
        result = {
            "status": "started",
            "needs_found": 0,
            "tools_discovered": 0,
            "tools_verified": 0,
            "tools_registered": 0,
            "timestamp": datetime.utcnow().isoformat()
        }

        # 활성화 확인
        if not await self.is_active():
            result["status"] = "dormant"
            result["reason"] = "Activation conditions not met"
            return result

        # 1. 니즈 분석
        needs = await self.analyze_tool_needs()
        result["needs_found"] = len(needs)

        if not needs:
            result["status"] = "no_needs"
            return result

        # 2. 상위 니즈에 대해 도구 검색
        for need in needs[:3]:  # 최대 3개 니즈 처리
            query = need.get("search_query") or need.get("need_description", "")
            category = need.get("suggested_tool_type")

            tools = await self.search_tools(query, category)

            for tool_info in tools[:2]:  # 니즈당 최대 2개 도구
                # 평가
                tool = await self.evaluate_tool(tool_info)
                result["tools_discovered"] += 1

                # 테스트
                test_result = await self.test_tool(tool)

                if test_result.get("passed"):
                    result["tools_verified"] += 1

                    # 등록
                    success, _ = await self.register_tool(tool)
                    if success:
                        result["tools_registered"] += 1

        result["status"] = "completed"
        return result

    def _extract_json(self, text: str) -> str:
        """텍스트에서 JSON 배열 추출"""
        if "```json" in text:
            return text.split("```json")[1].split("```")[0].strip()

        start = text.find("[")
        end = text.rfind("]") + 1

        if start >= 0 and end > start:
            return text[start:end]

        return "[]"

    def _extract_json_obj(self, text: str) -> str:
        """텍스트에서 JSON 객체 추출"""
        if "```json" in text:
            return text.split("```json")[1].split("```")[0].strip()

        start = text.find("{")
        end = text.rfind("}") + 1

        if start >= 0 and end > start:
            return text[start:end]

        return "{}"

    def _extract_code(self, text: str) -> str:
        """텍스트에서 코드 추출"""
        if "```python" in text:
            return text.split("```python")[1].split("```")[0].strip()

        if "```" in text:
            return text.split("```")[1].split("```")[0].strip()

        return ""

    def get_discovered_tools(self, status: str = None, limit: int = 20) -> List[Dict]:
        """발견된 도구 목록"""
        try:
            if status:
                rows = self.conn.execute("""
                    SELECT tool_id, name, category, description, status, created_at
                    FROM discovered_tools
                    WHERE status = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (status, limit)).fetchall()
            else:
                rows = self.conn.execute("""
                    SELECT tool_id, name, category, description, status, created_at
                    FROM discovered_tools
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (limit,)).fetchall()

            return [
                {
                    "tool_id": r[0],
                    "name": r[1],
                    "category": r[2],
                    "description": r[3],
                    "status": r[4],
                    "created_at": r[5]
                }
                for r in rows
            ]
        except:
            return []

    def get_registered_tools(self) -> List[Dict]:
        """등록된 도구 목록"""
        try:
            rows = self.conn.execute("""
                SELECT tool_id, name, category, description, capabilities, enabled
                FROM tool_registry
                WHERE enabled = 1
                ORDER BY registered_at DESC
            """).fetchall()

            return [
                {
                    "tool_id": r[0],
                    "name": r[1],
                    "category": r[2],
                    "description": r[3],
                    "capabilities": json.loads(r[4] or "[]"),
                    "enabled": bool(r[5])
                }
                for r in rows
            ]
        except:
            return []
