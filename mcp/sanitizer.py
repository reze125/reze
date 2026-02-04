"""MCP Output Sanitizer - 출력 정제 및 민감 정보 마스킹."""
import re
from typing import List, Tuple

import logging
logger = logging.getLogger("REZE.mcp")


class OutputSanitizer:
    """MCP 도구 출력 정제기."""

    # 민감 정보 패턴 (redaction.py 확장)
    PATTERNS: List[Tuple[str, str]] = [
        # API Keys
        (r'sk-[a-zA-Z0-9]{20,}', '***SK_REDACTED***'),
        (r'gsk_[a-zA-Z0-9]{20,}', '***GSK_REDACTED***'),
        (r'tvly-[a-zA-Z0-9]{20,}', '***TAVILY_REDACTED***'),
        (r'AIzaSy[a-zA-Z0-9_-]{33}', '***GEMINI_REDACTED***'),
        (r'csk-[a-zA-Z0-9]{20,}', '***CEREBRAS_REDACTED***'),
        (r'ghp_[a-zA-Z0-9]{36}', '***GITHUB_REDACTED***'),
        (r'npm_[a-zA-Z0-9]{36}', '***NPM_REDACTED***'),

        # Tokens
        (r'Bearer\s+[a-zA-Z0-9._-]{20,}', 'Bearer ***REDACTED***'),
        (r'token["\']?\s*[:=]\s*["\']?[a-zA-Z0-9._-]{20,}', 'token=***REDACTED***'),
        (r'api[_-]?key["\']?\s*[:=]\s*["\']?[a-zA-Z0-9._-]{16,}', 'api_key=***REDACTED***'),

        # Credentials
        (r'(?i)(password|passwd|pwd|secret)\s*[=:]\s*\S+', r'\1=***REDACTED***'),
        (r'(?i)(private[_-]?key)\s*[=:]\s*\S+', r'\1=***REDACTED***'),

        # Connection strings
        (r'(?i)(mongodb|postgres|mysql|redis)://[^\s]+', r'\1://***REDACTED***'),

        # File paths with secrets
        (r'/\.env\b', '/[ENV_FILE]'),
        (r'/\.ssh/', '/[SSH_DIR]/'),
        (r'/\.aws/', '/[AWS_DIR]/'),
        (r'/\.gnupg/', '/[GPG_DIR]/'),
    ]

    def __init__(self, max_output_size: int = 50000):
        """
        Args:
            max_output_size: 최대 출력 크기 (bytes)
        """
        self._compiled = [(re.compile(p), r) for p, r in self.PATTERNS]
        self.max_output_size = max_output_size

    def sanitize(self, text: str) -> str:
        """
        출력 정제.

        Args:
            text: 원본 텍스트

        Returns:
            정제된 텍스트
        """
        if not text:
            return text

        # 1. 크기 제한
        if len(text) > self.max_output_size:
            text = text[:self.max_output_size] + "\n...[TRUNCATED]"
            logger.debug(f"[SANITIZER] Output truncated to {self.max_output_size} bytes")

        # 2. 민감 정보 마스킹
        for pattern, replacement in self._compiled:
            text = pattern.sub(replacement, text)

        # 3. NULL 바이트 제거
        text = text.replace('\x00', '')

        # 4. 제어 문자 제거 (탭, 개행 제외)
        text = ''.join(c for c in text if c >= ' ' or c in '\t\n\r')

        return text

    def add_pattern(self, pattern: str, replacement: str):
        """
        커스텀 마스킹 패턴 추가.

        Args:
            pattern: 정규식 패턴
            replacement: 대체 문자열
        """
        self._compiled.append((re.compile(pattern), replacement))
        logger.debug(f"[SANITIZER] Added custom pattern: {pattern[:30]}...")
