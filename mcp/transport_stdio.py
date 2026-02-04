"""MCP Stdio Transport - subprocess 기반 로컬 MCP 서버 연결."""
import asyncio
import json
import os
import subprocess
from typing import Optional, Dict, Any, List

import logging
logger = logging.getLogger("REZE.mcp")


class StdioTransport:
    """Subprocess 기반 stdio 전송."""

    def __init__(
        self,
        command: List[str],
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None,
        timeout: int = 30
    ):
        """
        Args:
            command: 실행할 명령 (예: ["npx", "-y", "@modelcontextprotocol/server-filesystem"])
            env: 환경 변수 (기본: 현재 환경 상속)
            cwd: 작업 디렉토리
            timeout: 응답 타임아웃 (초)
        """
        self.command = command
        self.env = {**os.environ, **(env or {})}
        self.cwd = cwd
        self.timeout = timeout
        self.process: Optional[subprocess.Popen] = None
        self._lock = asyncio.Lock()

    async def connect(self) -> bool:
        """
        서버 프로세스 시작.

        Returns:
            성공 여부
        """
        try:
            self.process = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self.env,
                cwd=self.cwd,
                text=True,
                bufsize=1  # 라인 버퍼링
            )

            # 프로세스가 정상 실행 중인지 확인
            if self.process.poll() is not None:
                stderr = self.process.stderr.read()
                logger.error(f"[STDIO] Process exited immediately: {stderr}")
                return False

            logger.info(f"[STDIO] Started process: {' '.join(self.command)}")
            return True

        except FileNotFoundError as e:
            logger.error(f"[STDIO] Command not found: {self.command[0]}")
            return False
        except Exception as e:
            logger.error(f"[STDIO] Failed to start process: {e}")
            return False

    async def send(self, message: dict) -> dict:
        """
        JSON-RPC 메시지 전송 및 응답 수신.

        Args:
            message: JSON-RPC 요청

        Returns:
            JSON-RPC 응답
        """
        if not self.process or self.process.poll() is not None:
            return {"error": {"code": -1, "message": "Process not running"}}

        async with self._lock:
            try:
                # Write to stdin
                json_msg = json.dumps(message) + "\n"
                self.process.stdin.write(json_msg)
                self.process.stdin.flush()

                logger.debug(f"[STDIO] Sent: {message.get('method', 'unknown')}")

                # Read from stdout with timeout
                loop = asyncio.get_event_loop()
                response_line = await asyncio.wait_for(
                    loop.run_in_executor(None, self.process.stdout.readline),
                    timeout=self.timeout
                )

                if not response_line:
                    return {"error": {"code": -2, "message": "Empty response"}}

                response = json.loads(response_line)
                logger.debug(f"[STDIO] Received response for: {message.get('id', 'unknown')}")
                return response

            except asyncio.TimeoutError:
                logger.error(f"[STDIO] Timeout waiting for response")
                return {"error": {"code": -3, "message": f"Timeout ({self.timeout}s)"}}
            except json.JSONDecodeError as e:
                logger.error(f"[STDIO] Invalid JSON response: {e}")
                return {"error": {"code": -4, "message": f"Invalid JSON: {e}"}}
            except Exception as e:
                logger.error(f"[STDIO] Send error: {e}")
                return {"error": {"code": -5, "message": str(e)}}

    async def close(self):
        """프로세스 종료."""
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
                logger.info("[STDIO] Process terminated")
            except subprocess.TimeoutExpired:
                self.process.kill()
                logger.warning("[STDIO] Process killed after timeout")
            except Exception as e:
                logger.error(f"[STDIO] Error closing process: {e}")
            finally:
                self.process = None

    def is_connected(self) -> bool:
        """연결 상태 확인."""
        return self.process is not None and self.process.poll() is None
