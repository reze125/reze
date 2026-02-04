"""MCP (Model Context Protocol) Client Module.

외부 MCP 서버와 통신하기 위한 클라이언트 구현:
- StdioTransport: subprocess 기반 로컬 MCP 서버 연결
- HTTPTransport: aiohttp 기반 원격 MCP 서버 연결
- OutputSanitizer: 민감 정보 마스킹
- MCPClient: 통합 클라이언트
"""

from mcp.sanitizer import OutputSanitizer
from mcp.transport_stdio import StdioTransport
from mcp.transport_http import HTTPTransport
from mcp.client import MCPClient, MCPTool, TransportType

__all__ = [
    "OutputSanitizer",
    "StdioTransport",
    "HTTPTransport",
    "MCPClient",
    "MCPTool",
    "TransportType",
]
