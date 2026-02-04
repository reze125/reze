"""MCP HTTP Transport - aiohttp 기반 원격 MCP 서버 연결."""
import aiohttp
import json
from typing import Optional, Dict, Any

import logging
logger = logging.getLogger("REZE.mcp")


class HTTPTransport:
    """HTTP/SSE 기반 MCP 전송."""

    def __init__(
        self,
        base_url: str,
        api_key: Optional[str] = None,
        timeout: int = 30,
        headers: Optional[Dict[str, str]] = None
    ):
        """
        Args:
            base_url: MCP 서버 기본 URL
            api_key: Bearer 토큰 (선택)
            timeout: 요청 타임아웃 (초)
            headers: 추가 HTTP 헤더
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.extra_headers = headers or {}
        self.session: Optional[aiohttp.ClientSession] = None

    async def connect(self) -> bool:
        """
        세션 생성.

        Returns:
            성공 여부
        """
        try:
            headers = {**self.extra_headers}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            self.session = aiohttp.ClientSession(
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            )

            logger.info(f"[HTTP] Connected to: {self.base_url}")
            return True

        except Exception as e:
            logger.error(f"[HTTP] Failed to create session: {e}")
            return False

    async def send(self, message: dict) -> dict:
        """
        JSON-RPC 요청 전송.

        Args:
            message: JSON-RPC 요청

        Returns:
            JSON-RPC 응답
        """
        if not self.session:
            return {"error": {"code": -1, "message": "Session not connected"}}

        try:
            # MCP HTTP 전송은 /rpc 또는 /mcp 엔드포인트 사용
            endpoints = ["/rpc", "/mcp", ""]

            for endpoint in endpoints:
                url = f"{self.base_url}{endpoint}"
                try:
                    async with self.session.post(url, json=message) as resp:
                        if resp.status == 404:
                            continue  # 다음 엔드포인트 시도

                        if resp.status != 200:
                            text = await resp.text()
                            return {
                                "error": {
                                    "code": resp.status,
                                    "message": f"HTTP {resp.status}: {text[:200]}"
                                }
                            }

                        response = await resp.json()
                        logger.debug(f"[HTTP] Response from {url}")
                        return response

                except aiohttp.ClientError as e:
                    logger.debug(f"[HTTP] Endpoint {endpoint} failed: {e}")
                    continue

            return {"error": {"code": -2, "message": "All endpoints failed"}}

        except asyncio.TimeoutError:
            logger.error(f"[HTTP] Timeout ({self.timeout}s)")
            return {"error": {"code": -3, "message": f"Timeout ({self.timeout}s)"}}
        except Exception as e:
            logger.error(f"[HTTP] Request error: {e}")
            return {"error": {"code": -4, "message": str(e)}}

    async def close(self):
        """세션 종료."""
        if self.session:
            try:
                await self.session.close()
                logger.info("[HTTP] Session closed")
            except Exception as e:
                logger.error(f"[HTTP] Error closing session: {e}")
            finally:
                self.session = None

    def is_connected(self) -> bool:
        """연결 상태 확인."""
        return self.session is not None and not self.session.closed
