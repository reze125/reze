"""REZE Tools v5.0 — 6개 범용 도구 실행기
shell, python, http, web_search, web_fetch, code_edit
"""
import json
import subprocess
from typing import Any, Optional

import aiohttp

import config
from ssot import SSOT
from redaction import mask_text
from reze_permissions import (
    PermissionSystem, SecurePythonREPL, FilesystemTool, PermissionTier
)

import logging
logger = logging.getLogger("REZE.tools")


class CredentialStore:
    """외부 API 인증 정보 관리. credentials.json (퍼미션 600)."""

    def __init__(self, path=None):
        self.path = path or (config.BASE_DIR / "credentials.json")
        self._creds: dict = {}
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                with open(self.path) as f:
                    self._creds = json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load credentials: {e}")

    def get(self, service: str) -> Optional[str]:
        return self._creds.get(service)

    def set(self, service: str, key: str):
        self._creds[service] = key
        with open(self.path, "w") as f:
            json.dump(self._creds, f, indent=2)
        self.path.chmod(0o600)

    def list_services(self) -> list[str]:
        return list(self._creds.keys())


class ToolExecutor:
    """6개 도구 실행기. 권한 검사 → 실행 → 마스킹."""

    # v6.0: 동적 스킬용 제한 도구 세트
    DYNAMIC_SKILL_TOOLS = {"web_search", "web_fetch", "file_read", "python_exec"}

    def __init__(self, ssot: SSOT, permissions: PermissionSystem):
        self.ssot = ssot
        self.permissions = permissions
        self.repl = SecurePythonREPL()
        self.fs = FilesystemTool()
        self.credentials = CredentialStore()
        # Tavily 멀티키 라운드로빈
        self._tavily_keys = config.TAVILY_API_KEYS if config.TAVILY_API_KEYS else (
            [config.TAVILY_API_KEY] if config.TAVILY_API_KEY else []
        )
        self._tavily_idx = 0
        # v6.0: MCP 클라이언트 저장소
        self.mcp_clients: dict = {}

    async def execute(self, tool: str, tool_input: Any, source: str = "api") -> str:
        """도구 실행 메인 진입점."""
        # 1. 권한 검사
        tier = self.permissions.assess(tool, tool_input, source)

        if tier == PermissionTier.CRITICAL:
            return f"BLOCKED: '{tool}' 명령이 CRITICAL 등급입니다. 수동 승인이 필요합니다."

        if tier == PermissionTier.DANGEROUS:
            # DANGEROUS는 TRUSTED_SOURCES에서는 허용 (v5.0: discovery, capability 등 포함)
            if source not in PermissionSystem.TRUSTED_SOURCES:
                return f"BLOCKED: '{tool}' 명령이 DANGEROUS 등급입니다. source={source}에서 자동 실행 불가."
            logger.warning(f"DANGEROUS but allowed (source={source}): {tool} {str(tool_input)[:80]}")

        # 2. 실행 (v5.0: 6개 도구)
        try:
            if tool == "shell":
                result = self._exec_shell(str(tool_input))
            elif tool == "python":
                result = self.repl.execute(str(tool_input))
            elif tool == "http":
                result = await self._exec_http(tool_input)
            elif tool == "filesystem":
                result = self._exec_filesystem(tool_input)
            elif tool == "web_search":
                result = await self._exec_web_search(str(tool_input))
            elif tool == "web_fetch":
                result = await self._exec_web_fetch(tool_input)
            elif tool == "code_edit":
                result = self._exec_code_edit(tool_input)
            elif tool == "screenshot":
                result = await self._exec_screenshot(tool_input)
            else:
                result = f"ERROR: Unknown tool '{tool}'"
        except Exception as e:
            result = f"ERROR: {type(e).__name__}: {e}"

        # 3. 마스킹
        masked = mask_text(result)

        # 4. 로그
        self.ssot.log_event(
            kind="tool_execution",
            raw_input=mask_text(f"{tool}: {str(tool_input)[:200]}"),
            output_preview=masked[:200],
            tier=tier,
        )

        return masked

    def _exec_shell(self, command: str) -> str:
        """bash 명령 실행."""
        try:
            result = subprocess.run(
                ["bash", "-c", command],
                capture_output=True, text=True,
                timeout=config.SHELL_TIMEOUT,
            )
            output = (result.stdout + result.stderr).strip()
            return output if output else "Executed (no output)"
        except subprocess.TimeoutExpired:
            return f"ERROR: Shell timeout ({config.SHELL_TIMEOUT}s)"
        except Exception as e:
            return f"ERROR: Shell failed — {e}"

    async def _exec_http(self, request: Any) -> str:
        """HTTP 요청 실행 (v5.0: 자동 인증 + JSON 파싱)."""
        import os

        if isinstance(request, str):
            try:
                request = json.loads(request)
            except json.JSONDecodeError:
                # URL만 넘어온 경우 GET으로 처리
                request = {"url": request, "method": "GET"}

        url = request.get("url", "")
        method = request.get("method", "GET").upper()
        headers = dict(request.get("headers", {}))
        body = request.get("body")

        if not url:
            return "ERROR: No URL provided"

        # v5.0: 서비스별 인증 자동 주입
        if "api.stripe.com" in url:
            headers.setdefault("Authorization", f"Bearer {os.getenv('STRIPE_API_KEY', '')}")
        elif "api.lemonsqueezy.com" in url:
            headers.setdefault("Authorization", f"Bearer {os.getenv('LEMONSQUEEZY_API_KEY', '')}")
        elif "api.github.com" in url:
            headers.setdefault("Authorization", f"token {os.getenv('GITHUB_TOKEN', '')}")
        elif "api.gumroad.com" in url:
            headers.setdefault("Authorization", f"Bearer {os.getenv('GUMROAD_ACCESS_TOKEN', '')}")
        elif "localhost" in url or "127.0.0.1" in url:
            headers.setdefault("Authorization", f"Bearer {os.getenv('REZE_API_KEY', '')}")

        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                kwargs = {"headers": headers}
                if body and method in ("POST", "PUT", "PATCH"):
                    if isinstance(body, dict):
                        kwargs["json"] = body
                    else:
                        try:
                            kwargs["json"] = json.loads(body)
                        except (json.JSONDecodeError, TypeError):
                            kwargs["data"] = str(body)

                async with session.request(method, url, **kwargs) as resp:
                    # v5.0: Content-Type에 따른 자동 파싱
                    content_type = resp.headers.get("Content-Type", "")
                    if "application/json" in content_type:
                        try:
                            data = await resp.json()
                            text = json.dumps(data, ensure_ascii=False, indent=2)
                        except:
                            text = await resp.text()
                    else:
                        text = await resp.text()

                    truncated = text[:config.MAX_OBSERVATION_CHARS]
                    return f"HTTP {resp.status}\n{truncated}"
        except Exception as e:
            return f"ERROR: HTTP request failed — {e}"

    def _exec_filesystem(self, request: Any) -> str:
        """파일시스템 작업."""
        if isinstance(request, str):
            try:
                request = json.loads(request)
            except json.JSONDecodeError:
                # 문자열이면 읽기로 간주
                return self.fs.read(request)

        op = request.get("operation", "read")
        path = request.get("path", "")

        if op == "read":
            return self.fs.read(path)
        elif op == "write":
            content = request.get("content", "")
            return self.fs.write(path, content)
        elif op == "list":
            return self.fs.list_dir(path or ".")
        return f"ERROR: Unknown filesystem operation '{op}'"

    def _next_tavily_key(self) -> str:
        """라운드로빈으로 다음 Tavily 키."""
        if not self._tavily_keys:
            return ""
        key = self._tavily_keys[self._tavily_idx % len(self._tavily_keys)]
        self._tavily_idx += 1
        return key

    async def _exec_web_search(self, query: str) -> str:
        """Tavily 웹 검색. 7키 라운드로빈."""
        if not self._tavily_keys:
            return "ERROR: TAVILY_API_KEY not set"

        last_error = None
        for _ in range(len(self._tavily_keys)):
            api_key = self._next_tavily_key()
            try:
                timeout = aiohttp.ClientTimeout(total=30)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(
                        "https://api.tavily.com/search",
                        json={
                            "api_key": api_key,
                            "query": query,
                            "max_results": 5,
                            "include_answer": True,
                        },
                    ) as resp:
                        data = await resp.json()
                        results = []
                        if data.get("answer"):
                            results.append(f"Answer: {data['answer']}")
                        for r in data.get("results", [])[:5]:
                            title = r.get("title", "")
                            content = r.get("content", "")[:150]
                            results.append(f"- {title}: {content}...")
                        return "\n\n".join(results) if results else "No results found"
            except Exception as e:
                last_error = e
                error_str = str(e).lower()
                if "429" in str(e) or "rate" in error_str:
                    logger.warning(f"Tavily key rate limited, trying next")
                    continue
                break

        return f"ERROR: Web search failed — {last_error}"

    # === v5.0: 신규 도구 ===

    async def _exec_web_fetch(self, request: Any) -> str:
        """URL에서 텍스트 콘텐츠 추출."""
        import re as regex_module

        if isinstance(request, str):
            url = request
        elif isinstance(request, dict):
            url = request.get("url", "")
        else:
            return "ERROR: url 필요"

        if not url.startswith(("http://", "https://")):
            return "ERROR: http:// 또는 https:// URL 필요"

        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers={
                    "User-Agent": "Mozilla/5.0 (compatible; REZE-Agent/5.0)"
                }) as resp:
                    if resp.status != 200:
                        return f"ERROR: HTTP {resp.status}"
                    html = await resp.text()

            # HTML → 텍스트 (간단한 태그 제거)
            text = regex_module.sub(r'<script[^>]*>.*?</script>', '', html, flags=regex_module.DOTALL)
            text = regex_module.sub(r'<style[^>]*>.*?</style>', '', text, flags=regex_module.DOTALL)
            text = regex_module.sub(r'<[^>]+>', ' ', text)
            text = regex_module.sub(r'\s+', ' ', text).strip()

            return text[:5000]
        except Exception as e:
            return f"ERROR: {e}"

    def _exec_code_edit(self, request: Any, source: str = "api") -> str:
        """파일 읽기/수정/생성 도구."""
        import os

        if isinstance(request, str):
            return "ERROR: dict 필요 {action, path, ...}"

        action = request.get("action", "read")
        path = request.get("path", "")

        # v6.0 Phase 2D-2: 쓰기/수정 시 VIGIL 검사
        if action in ("edit", "create"):
            try:
                from manus.vigil import get_vigil
                vigil = get_vigil(self.ssot)
                content = request.get("content", "") or request.get("new_str", "")
                vigil_result = vigil.check_file_content(path, content, source)
                if not vigil_result.allowed:
                    return f"BLOCKED by VIGIL: {vigil_result.reason}"
            except ImportError:
                pass  # VIGIL 모듈 없으면 스킵

        # 경로 보안 체크
        real_path = os.path.realpath(path) if path else ""
        ALLOWED_ROOTS = [
            "/home/reze/reze-agent/",
            "/home/reze/blogs/",
            "/home/reze/projects/",
            "/home/reze/ai-tools-lab/",
            "/tmp/reze/"
        ]
        if not any(real_path.startswith(root) for root in ALLOWED_ROOTS):
            return f"ERROR: 허용되지 않은 경로: {path}"

        try:
            if action == "read":
                line_range = request.get("line_range")
                with open(path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                if line_range:
                    start, end = line_range
                    lines = lines[max(0, start-1):end]
                numbered = [f"{i+1}: {l}" for i, l in enumerate(lines, start=line_range[0] if line_range else 1)]
                return "".join(numbered)[:5000]

            elif action == "edit":
                old_str = request.get("old_str", "")
                new_str = request.get("new_str", "")
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()
                if old_str not in content:
                    return f"ERROR: old_str not found in {path}"
                if content.count(old_str) > 1:
                    return f"ERROR: old_str이 {content.count(old_str)}번 발견됨 (unique해야 함)"
                content = content.replace(old_str, new_str, 1)
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(content)
                return f"OK: {path} 수정 완료"

            elif action == "create":
                file_content = request.get("content", "")
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(file_content)
                return f"OK: {path} 생성 완료 ({len(file_content)} bytes)"

            elif action == "list":
                import subprocess
                result = subprocess.run(
                    ["find", path, "-maxdepth", "2", "-type", "f"],
                    capture_output=True, text=True, timeout=5
                )
                return result.stdout[:3000]

            else:
                return f"ERROR: unknown action: {action} (read/edit/create/list)"

        except Exception as e:
            return f"ERROR: {e}"

    async def _exec_screenshot(self, request: Any) -> str:
        """웹사이트 스크린샷 캡처 (Playwright)."""
        from tools.screenshot import capture_screenshot, capture_tool_screenshot

        if isinstance(request, str):
            # URL만 전달된 경우
            result = await capture_screenshot(request)
        elif isinstance(request, dict):
            # 상세 옵션
            url = request.get("url", "")
            if not url:
                return "ERROR: url 필요"

            # AI 도구 스크린샷 (tool_name 있으면)
            tool_name = request.get("tool_name")
            if tool_name:
                result = await capture_tool_screenshot(tool_name, url)
            else:
                result = await capture_screenshot(
                    url=url,
                    filename=request.get("filename"),
                    width=request.get("width", 1280),
                    height=request.get("height", 720),
                    full_page=request.get("full_page", False),
                    timeout=request.get("timeout", 30000)
                )
        else:
            return "ERROR: url string 또는 {url, filename?, width?, height?, full_page?, tool_name?} 필요"

        if result.get("success"):
            return f"OK: Screenshot saved\nPath: {result['path']}\nWeb: {result['web_path']}\nMarkdown: {result['markdown']}"
        else:
            return f"ERROR: {result.get('error', 'Unknown error')}"

    def get_tool_catalog(self) -> str:
        """LLM에게 전달할 도구 카탈로그."""
        return """사용 가능한 도구:

1. shell: bash 명령어 실행
   입력: 명령어 문자열
   예: "docker ps --format '{{.Names}}:{{.Status}}'"
   예: "pm2 jlist"
   예: "free -m && df -h"
   참고: 파이프(|)와 AND(&&) 사용 가능

2. python: Python 코드 실행
   입력: 코드 문자열
   허용 import: json, re, math, datetime, collections, itertools, csv, pathlib, hashlib, base64, statistics, sqlite3, time, functools, random
   예: "import json\\ndata = json.loads('{\"a\":1}')\\nprint(data)"

3. http: HTTP 요청
   입력: {"method": "GET/POST/PUT/DELETE", "url": "...", "headers": {}, "body": {}}
   또는: URL 문자열 (GET)
   인증 자동 주입: Stripe, LemonSqueezy, GitHub, localhost

4. web_search: 웹 검색 (Tavily)
   입력: 검색 쿼리 문자열
   출력: 상위 5개 결과 (제목, URL, 요약)

5. web_fetch: 웹페이지 텍스트 추출
   입력: URL 문자열 또는 {"url": "..."}
   출력: 페이지 텍스트 (최대 5000자)

6. code_edit: 파일 읽기/수정/생성
   입력: {"action": "read|edit|create|list", "path": "...", ...}
   read: {"action": "read", "path": "파일경로", "line_range": [시작, 끝]}
   edit: {"action": "edit", "path": "파일경로", "old_str": "찾을문자열", "new_str": "바꿀문자열"}
   create: {"action": "create", "path": "파일경로", "content": "내용"}
   list: {"action": "list", "path": "디렉토리경로"}
   허용경로: /home/reze/reze-agent/, /home/reze/blogs/, /home/reze/projects/, /tmp/reze/

7. screenshot: 웹사이트 스크린샷 캡처 (Playwright)
   입력: URL 문자열 또는 {"url": "...", "filename": "...", "width": 1280, "height": 720, "full_page": false, "tool_name": "..."}
   출력: 저장된 파일 경로 + 웹 경로 + 마크다운 태그
   저장위치: ~/ai-tools-lab/public/screenshots/
   예: "https://cursor.sh" → /screenshots/cursor-20260205.png
   예: {"url": "https://claude.ai", "tool_name": "Claude"} → /screenshots/claude-screenshot.png"""

    # === v6.0: 제한된 도구 실행 (동적 스킬용) ===

    async def execute_restricted(
        self,
        tool: str,
        tool_input: Any,
        allowed_tools: set = None,
        source: str = "dynamic_skill"
    ) -> str:
        """
        제한된 도구만 허용하는 실행 메서드 (동적 스킬용).

        Args:
            tool: 실행할 도구 이름
            tool_input: 도구 입력
            allowed_tools: 허용된 도구 집합 (None이면 DYNAMIC_SKILL_TOOLS 사용)
            source: 실행 소스

        Returns:
            도구 실행 결과
        """
        if allowed_tools is None:
            allowed_tools = self.DYNAMIC_SKILL_TOOLS

        # 도구 허용 여부 검사
        if tool not in allowed_tools:
            return f"BLOCKED: Tool '{tool}' not allowed. Allowed: {sorted(allowed_tools)}"

        # file_read → code_edit의 read 모드로 매핑
        if tool == "file_read":
            if isinstance(tool_input, str):
                request = {"action": "read", "path": tool_input}
            elif isinstance(tool_input, dict):
                request = {"action": "read", "path": tool_input.get("path", ""), "line_range": tool_input.get("line_range")}
            else:
                return "ERROR: file_read requires path string or dict with 'path'"
            return self._exec_code_edit(request)

        # python_exec → python으로 매핑
        if tool == "python_exec":
            return self.repl.execute(str(tool_input))

        # 그 외 도구는 기존 execute 사용 (권한 검사 포함)
        return await self.execute(tool, tool_input, source)

    def get_restricted_catalog(self, allowed_tools: set = None) -> str:
        """제한된 도구 카탈로그 생성 (동적 스킬용)."""
        if allowed_tools is None:
            allowed_tools = self.DYNAMIC_SKILL_TOOLS

        catalog_parts = ["사용 가능한 도구:\n"]

        if "web_search" in allowed_tools:
            catalog_parts.append("""
1. web_search: 웹 검색 (Tavily)
   입력: 검색 쿼리 문자열
   출력: 상위 5개 결과 (제목, URL, 요약)
   예: "AI agent frameworks 2024"
""")

        if "web_fetch" in allowed_tools:
            catalog_parts.append("""
2. web_fetch: 웹페이지 텍스트 추출
   입력: URL 문자열 또는 {"url": "..."}
   출력: 페이지 텍스트 (최대 5000자)
   예: "https://example.com/article"
""")

        if "file_read" in allowed_tools:
            catalog_parts.append("""
3. file_read: 파일 읽기 (읽기 전용)
   입력: 파일 경로 문자열 또는 {"path": "...", "line_range": [시작, 끝]}
   출력: 파일 내용 (줄 번호 포함, 최대 5000자)
   허용경로: /home/reze/reze-agent/, /home/reze/blogs/, /home/reze/projects/, /tmp/reze/
   예: "/home/reze/reze-agent/config.py"
""")

        if "python_exec" in allowed_tools:
            catalog_parts.append("""
4. python_exec: Python 코드 실행
   입력: 코드 문자열
   허용 import: json, re, math, datetime, collections, itertools, csv, pathlib, hashlib, base64, statistics, sqlite3, time, functools, random
   예: "import json\\ndata = {'key': 'value'}\\nprint(json.dumps(data))"
""")

        return "".join(catalog_parts).strip()

    # ================================================================
    # v6.0 Phase 2B-5: MCP Client Integration
    # ================================================================

    async def connect_mcp(
        self,
        server_id: str,
        transport_type: str,
        stdio_command: list = None,
        stdio_env: dict = None,
        http_url: str = None,
        http_api_key: str = None,
        timeout: int = 30
    ) -> dict:
        """
        MCP 서버 연결.

        Args:
            server_id: 서버 식별자
            transport_type: "stdio" 또는 "http"
            stdio_command: stdio용 명령 (예: ["npx", "-y", "@modelcontextprotocol/server-filesystem"])
            stdio_env: stdio용 환경 변수
            http_url: HTTP용 서버 URL
            http_api_key: HTTP용 API 키
            timeout: 요청 타임아웃 (초)

        Returns:
            {"success": bool, "server_id": str, "tools": list} 또는 {"success": False, "error": str}
        """
        from mcp import MCPClient, TransportType

        # 이미 연결된 서버인지 확인
        if server_id in self.mcp_clients:
            client = self.mcp_clients[server_id]
            if client.is_connected():
                return {
                    "success": True,
                    "server_id": server_id,
                    "tools": client.get_tool_names(),
                    "message": "Already connected"
                }

        try:
            client = MCPClient(
                transport_type=TransportType(transport_type),
                stdio_command=stdio_command,
                stdio_env=stdio_env,
                http_url=http_url,
                http_api_key=http_api_key,
                timeout=timeout
            )

            if await client.connect():
                self.mcp_clients[server_id] = client
                logger.info(f"[MCP] Connected to server '{server_id}' with {len(client.tools)} tools")
                return {
                    "success": True,
                    "server_id": server_id,
                    "tools": client.get_tool_names(),
                    "server_info": client.server_info
                }
            else:
                return {"success": False, "error": "Connection failed"}

        except ValueError as e:
            return {"success": False, "error": str(e)}
        except Exception as e:
            logger.error(f"[MCP] Connection error: {e}")
            return {"success": False, "error": str(e)}

    async def call_mcp(
        self,
        server_id: str,
        tool_name: str,
        arguments: dict = None
    ) -> str:
        """
        MCP 도구 호출.

        Args:
            server_id: 서버 식별자
            tool_name: 도구 이름
            arguments: 도구 인자

        Returns:
            도구 실행 결과
        """
        if server_id not in self.mcp_clients:
            return f"ERROR: MCP server '{server_id}' not connected"

        client = self.mcp_clients[server_id]
        if not client.is_connected():
            return f"ERROR: MCP server '{server_id}' disconnected"

        result = await client.call_tool(tool_name, arguments or {})

        # 로그
        self.ssot.log_event(
            kind="mcp_tool_call",
            raw_input=f"{server_id}/{tool_name}: {str(arguments)[:200]}",
            output_preview=result[:200]
        )

        return result

    async def disconnect_mcp(self, server_id: str) -> dict:
        """
        MCP 서버 연결 해제.

        Args:
            server_id: 서버 식별자

        Returns:
            {"status": "disconnected"} 또는 {"error": str}
        """
        if server_id not in self.mcp_clients:
            return {"error": f"Server '{server_id}' not found"}

        client = self.mcp_clients[server_id]
        await client.close()
        del self.mcp_clients[server_id]

        logger.info(f"[MCP] Disconnected from server '{server_id}'")
        return {"status": "disconnected", "server_id": server_id}

    def list_mcp_servers(self) -> list:
        """
        연결된 MCP 서버 목록.

        Returns:
            [{"server_id": str, "transport": str, "tools": list, "connected": bool}]
        """
        servers = []
        for sid, client in self.mcp_clients.items():
            servers.append({
                "server_id": sid,
                "transport": client.transport_type.value,
                "tools": client.get_tool_names(),
                "connected": client.is_connected(),
                "server_info": client.server_info
            })
        return servers
