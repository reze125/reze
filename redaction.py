"""REZE Redaction - 민감 정보 마스킹"""
import re

_KEY_PATTERNS = [
    (r'sk-[a-zA-Z0-9]{20,}', '***SK_REDACTED***'),
    (r'gsk_[a-zA-Z0-9]{20,}', '***GSK_REDACTED***'),
    (r'tvly-[a-zA-Z0-9]{20,}', '***TAVILY_REDACTED***'),
    (r'AIzaSy[a-zA-Z0-9_-]{33}', '***GEMINI_REDACTED***'),
    (r'csk-[a-zA-Z0-9]{20,}', '***CEREBRAS_REDACTED***'),
    (r'reze_sk_[a-zA-Z0-9]{20,}', '***REZE_REDACTED***'),
    (r'Bearer\s+[a-zA-Z0-9._-]{20,}', 'Bearer ***REDACTED***'),
    (r'(?i)(password|passwd|pwd)\s*[=:]\s*\S+', r'\1=***REDACTED***'),
]

_compiled = [(re.compile(p), r) for p, r in _KEY_PATTERNS]


def mask_text(text: str) -> str:
    """텍스트 내 API 키/비밀번호를 마스킹."""
    for pattern, replacement in _compiled:
        text = pattern.sub(replacement, text)
    return text


def mask_headers(headers: dict) -> dict:
    """HTTP 헤더의 민감 값 마스킹."""
    masked = {}
    sensitive_keys = {"authorization", "x-api-key", "api-key", "cookie"}
    for k, v in headers.items():
        if k.lower() in sensitive_keys:
            masked[k] = "***REDACTED***"
        else:
            masked[k] = v
    return masked
