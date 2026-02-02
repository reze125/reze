"""REZE Tools — 5개 범용 도구 실행기"""
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
    """5개 도구 실행기. 권한 검사 → 실행 → 마스킹."""

    def __init__(self, ssot: SSOT, permissions: PermissionSystem):
        self.ssot = ssot
        self.permissions = permissions
        self.repl = SecurePythonREPL()
        self.fs = FilesystemTool()
        self.credentials = CredentialStore()

    async def execute(self, tool: str, tool_input: Any, source: str = "api") -> str:
        """도구 실행 메인 진입점."""
        # 1. 권한 검사
        tier = self.permissions.assess(tool, tool_input, source)

        if tier == PermissionTier.CRITICAL:
            return f"BLOCKED: '{tool}' 명령이 CRITICAL 등급입니다. 수동 승인이 필요합니다."

        if tier == PermissionTier.DANGEROUS:
            # DANGEROUS는 api/schedule 소스에서는 STANDARD로 취급 (v3.3 설계)
            if source not in ("api", "schedule"):
                return f"BLOCKED: '{tool}' 명령이 DANGEROUS 등급입니다. source={source}에서 자동 실행 불가."
            logger.warning(f"DANGEROUS but allowed (source={source}): {tool} {str(tool_input)[:80]}")

        # 2. 실행
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
        """HTTP 요청 실행."""
        if isinstance(request, str):
            try:
                request = json.loads(request)
            except json.JSONDecodeError:
                # URL만 넘어온 경우 GET으로 처리
                request = {"url": request, "method": "GET"}

        url = request.get("url", "")
        method = request.get("method", "GET").upper()
        headers = request.get("headers", {})
        body = request.get("body")

        if not url:
            return "ERROR: No URL provided"

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

    async def _exec_web_search(self, query: str) -> str:
        """Tavily 웹 검색."""
        api_key = config.TAVILY_API_KEY
        if not api_key:
            return "ERROR: TAVILY_API_KEY not set"

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
            return f"ERROR: Web search failed — {e}"
