"""MCP Client - 통합 MCP 클라이언트."""
import uuid
from typing import Optional, Dict, Any, List, Union
from dataclasses import dataclass, field
from enum import Enum

from mcp.transport_stdio import StdioTransport
from mcp.transport_http import HTTPTransport
from mcp.sanitizer import OutputSanitizer

import logging
logger = logging.getLogger("REZE.mcp")


class TransportType(Enum):
    """전송 유형."""
    STDIO = "stdio"
    HTTP = "http"


@dataclass
class MCPTool:
    """MCP 서버에서 제공하는 도구."""
    name: str
    description: str
    input_schema: Dict[str, Any] = field(default_factory=dict)


class MCPClient:
    """통합 MCP 클라이언트."""

    def __init__(
        self,
        transport_type: TransportType,
        stdio_command: List[str] = None,
        stdio_env: Dict[str, str] = None,
        http_url: str = None,
        http_api_key: str = None,
        timeout: int = 30
    ):
        """
        Args:
            transport_type: 전송 유형 (stdio/http)
            stdio_command: stdio 전송용 명령
            stdio_env: stdio 전송용 환경 변수
            http_url: HTTP 전송용 서버 URL
            http_api_key: HTTP 전송용 API 키
            timeout: 요청 타임아웃 (초)
        """
        self.transport_type = transport_type
        self.sanitizer = OutputSanitizer()

        if transport_type == TransportType.STDIO:
            if not stdio_command:
                raise ValueError("stdio_command required for STDIO transport")
            self.transport = StdioTransport(
                command=stdio_command,
                env=stdio_env,
                timeout=timeout
            )
        else:
            if not http_url:
                raise ValueError("http_url required for HTTP transport")
            self.transport = HTTPTransport(
                base_url=http_url,
                api_key=http_api_key,
                timeout=timeout
            )

        self.tools: List[MCPTool] = []
        self.server_info: Dict[str, Any] = {}
        self.initialized = False

    async def connect(self) -> bool:
        """
        서버 연결 및 초기화.

        Returns:
            성공 여부
        """
        # 1. 전송 연결
        if not await self.transport.connect():
            logger.error("[MCP] Transport connection failed")
            return False

        # 2. Initialize handshake
        init_response = await self._send_rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "roots": {"listChanged": True},
                "sampling": {}
            },
            "clientInfo": {
                "name": "reze-agent",
                "version": "6.0"
            }
        })

        if init_response.get("error"):
            logger.error(f"[MCP] Initialize failed: {init_response['error']}")
            return False

        self.server_info = init_response.get("result", {}).get("serverInfo", {})
        logger.info(f"[MCP] Connected to server: {self.server_info.get('name', 'unknown')}")

        # 3. Send initialized notification
        await self._send_notification("notifications/initialized", {})

        # 4. List available tools
        tools_response = await self._send_rpc("tools/list", {})

        if tools_response.get("error"):
            logger.warning(f"[MCP] tools/list failed: {tools_response['error']}")
            # 일부 서버는 도구가 없을 수 있음
            self.tools = []
        else:
            tools_data = tools_response.get("result", {}).get("tools", [])
            self.tools = [
                MCPTool(
                    name=t["name"],
                    description=t.get("description", ""),
                    input_schema=t.get("inputSchema", {})
                )
                for t in tools_data
            ]
            logger.info(f"[MCP] Available tools: {[t.name for t in self.tools]}")

        self.initialized = True
        return True

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any] = None) -> str:
        """
        도구 호출.

        Args:
            tool_name: 도구 이름
            arguments: 도구 인자

        Returns:
            도구 실행 결과 (정제됨)
        """
        if not self.initialized:
            return "ERROR: MCP client not initialized"

        # 도구 존재 확인
        tool = next((t for t in self.tools if t.name == tool_name), None)
        if not tool:
            available = ", ".join(t.name for t in self.tools)
            return f"ERROR: Tool '{tool_name}' not found. Available: {available}"

        response = await self._send_rpc("tools/call", {
            "name": tool_name,
            "arguments": arguments or {}
        })

        if response.get("error"):
            error = response["error"]
            return f"ERROR: {error.get('message', 'Unknown error')} (code: {error.get('code', 'N/A')})"

        result = response.get("result", {})
        content = result.get("content", [])

        # 콘텐츠 타입별 처리
        output_parts = []
        for c in content:
            if c.get("type") == "text":
                output_parts.append(c.get("text", ""))
            elif c.get("type") == "image":
                output_parts.append(f"[Image: {c.get('mimeType', 'unknown')}]")
            elif c.get("type") == "resource":
                output_parts.append(f"[Resource: {c.get('uri', 'unknown')}]")

        raw_output = "\n".join(output_parts) if output_parts else "(no output)"

        # 출력 정제
        return self.sanitizer.sanitize(raw_output)

    async def list_resources(self) -> List[Dict[str, Any]]:
        """
        리소스 목록 조회.

        Returns:
            리소스 목록
        """
        if not self.initialized:
            return []

        response = await self._send_rpc("resources/list", {})
        if response.get("error"):
            return []

        return response.get("result", {}).get("resources", [])

    async def read_resource(self, uri: str) -> str:
        """
        리소스 읽기.

        Args:
            uri: 리소스 URI

        Returns:
            리소스 내용
        """
        if not self.initialized:
            return "ERROR: MCP client not initialized"

        response = await self._send_rpc("resources/read", {"uri": uri})

        if response.get("error"):
            return f"ERROR: {response['error'].get('message', 'Unknown')}"

        contents = response.get("result", {}).get("contents", [])
        text_parts = [c.get("text", "") for c in contents if "text" in c]

        return self.sanitizer.sanitize("\n".join(text_parts))

    async def _send_rpc(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """JSON-RPC 요청 전송."""
        message = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": method,
            "params": params
        }
        return await self.transport.send(message)

    async def _send_notification(self, method: str, params: Dict[str, Any]):
        """JSON-RPC 알림 전송 (응답 없음)."""
        message = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params
        }
        # 알림은 id가 없고 응답을 기다리지 않음
        await self.transport.send(message)

    async def close(self):
        """연결 종료."""
        if self.transport:
            await self.transport.close()
            self.initialized = False
            logger.info("[MCP] Client closed")

    def is_connected(self) -> bool:
        """연결 상태 확인."""
        return self.initialized and self.transport.is_connected()

    def get_tool_names(self) -> List[str]:
        """도구 이름 목록."""
        return [t.name for t in self.tools]

    def get_tool_schema(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """도구 스키마 조회."""
        tool = next((t for t in self.tools if t.name == tool_name), None)
        return tool.input_schema if tool else None
