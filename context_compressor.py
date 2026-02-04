"""REZE v6.0 — Context Compressor.

Reduces token usage by compressing messages before LLM calls.
Uses rule-based compression (no external model dependencies).

Compression strategies:
1. Trim whitespace and normalize
2. Truncate old messages more aggressively
3. Compress repeated patterns
4. Summarize long tool outputs

Phase 2 Gap Fix:
- Provider-specific token limits (Cerebras 8K, Groq 32K, Gemini 1M)
- More aggressive compression for Cerebras
"""

import re
import logging
from typing import Tuple

logger = logging.getLogger("REZE.compressor")

# 프로바이더별 토큰 한도 (Phase 2 Gap Fix)
PROVIDER_TOKEN_LIMITS = {
    "cerebras": 6000,      # 8K 한도, 안전 마진 확보
    "groq": 28000,         # 32K 한도
    "gemini_pro": 100000,  # 1M 한도지만 비용상 제한
    "gemini_flash": 100000,
    "openrouter": 28000,   # 대부분 32K
    "default": 12000
}


class ContextCompressor:
    """Rule-based context compression for LLM calls."""

    # 압축하지 않는 역할들 (정확성 중요)
    NO_COMPRESS_ROLES = {"tool_call", "extraction", "quick"}

    # 메시지 역할별 최대 길이
    MAX_LENGTHS = {
        "system": 4000,      # 시스템 프롬프트: 유지
        "user": 2000,        # 사용자 입력: 적당히
        "assistant": 1500,   # 어시스턴트 응답: 약간 압축
        "observation": 1000, # 도구 출력: 공격적 압축
    }

    # 압축할 반복 패턴
    PATTERNS_TO_COMPRESS = [
        (r'\n{3,}', '\n\n'),           # 연속 줄바꿈 → 2개로
        (r'[ \t]{2,}', ' '),           # 연속 공백 → 1개로
        (r'─{5,}', '───'),             # 긴 구분선 축소
        (r'={5,}', '==='),
        (r'-{5,}', '---'),
        (r'\.{4,}', '...'),            # 긴 점 → 3개로
        (r'#+ ', '# '),                # 마크다운 헤딩 간소화 (선택적)
    ]

    def __init__(self, min_tokens: int = 2000):
        """
        Args:
            min_tokens: 이 토큰 수 이하면 압축하지 않음
        """
        self.min_tokens = min_tokens
        self.stats = {
            "compressions": 0,
            "total_original": 0,
            "total_compressed": 0
        }

    def should_compress(self, step_type: str) -> bool:
        """이 역할에 대해 압축해야 하는가?"""
        return step_type not in self.NO_COMPRESS_ROLES

    def estimate_tokens(self, text: str) -> int:
        """대략적인 토큰 수 추정 (4글자 = 1토큰)."""
        return len(text) // 4

    def compress(self, messages: list[dict], system: str = "",
                 step_type: str = "default", target_provider: str = None) -> Tuple[list[dict], str]:
        """메시지와 시스템 프롬프트 압축.

        Phase 2 Gap Fix: target_provider별 차등 압축.
        - cerebras: 8K 한도 → 공격적 압축
        - groq: 32K 한도 → 보통 압축
        - gemini: 1M 한도 → 거의 압축 안 함

        Returns:
            (compressed_messages, compressed_system)
        """
        if not self.should_compress(step_type):
            return messages, system

        # 전체 길이 추정
        total_chars = sum(len(m.get("content", "")) for m in messages) + len(system)
        estimated_tokens = total_chars // 4

        # Phase 2 Gap Fix: 프로바이더별 토큰 한도 적용
        token_limit = PROVIDER_TOKEN_LIMITS.get(target_provider, PROVIDER_TOKEN_LIMITS["default"])

        # 토큰 한도 이하면 압축 불필요
        if estimated_tokens < min(self.min_tokens, token_limit * 0.7):
            return messages, system

        # 프로바이더별 압축 강도 결정
        compression_ratio = 1.0
        if target_provider == "cerebras":
            # Cerebras는 공격적 압축 (8K 한도)
            compression_ratio = 0.5 if estimated_tokens > token_limit else 0.7
        elif target_provider in ("groq", "openrouter"):
            compression_ratio = 0.7 if estimated_tokens > token_limit else 0.85
        else:
            compression_ratio = 0.85

        original_chars = total_chars

        # 1. 시스템 프롬프트 압축 (패턴 정리만, 내용 유지)
        system_max = int(self.MAX_LENGTHS["system"] * compression_ratio)
        compressed_system = self._compress_text(system, system_max)

        # 2. 메시지 압축 (Phase 2 Gap Fix: compression_ratio 적용)
        compressed_messages = []
        for i, msg in enumerate(messages):
            content = msg.get("content", "")
            role = msg.get("role", "user")

            # 최근 메시지는 덜 압축
            is_recent = i >= len(messages) - 3
            recent_multiplier = 1.5 if is_recent else 1.0

            if role == "user":
                # Observation인지 체크
                if content.startswith("Observation:"):
                    # 도구 출력은 가장 공격적으로 압축
                    max_len = int(self.MAX_LENGTHS["observation"] * compression_ratio * 0.8 * recent_multiplier)
                    compressed = self._compress_observation(content, max_len)
                else:
                    # 사용자 질문은 보존 (최근 것은 거의 원본 유지)
                    max_len = int(self.MAX_LENGTHS["user"] * recent_multiplier)
                    compressed = self._compress_text(content, max_len)
            elif role == "assistant":
                # 어시스턴트 응답은 중간 수준 압축
                max_len = int(self.MAX_LENGTHS["assistant"] * compression_ratio * recent_multiplier)
                compressed = self._compress_text(content, max_len)
            else:
                compressed = content

            compressed_messages.append({
                "role": role,
                "content": compressed
            })

        # 통계 업데이트
        compressed_chars = sum(len(m.get("content", "")) for m in compressed_messages) + len(compressed_system)
        self.stats["compressions"] += 1
        self.stats["total_original"] += original_chars
        self.stats["total_compressed"] += compressed_chars

        ratio = compressed_chars / original_chars if original_chars > 0 else 1.0
        if ratio < 0.9:
            logger.info(f"Compressed context: {original_chars} → {compressed_chars} chars ({ratio:.1%})")

        return compressed_messages, compressed_system

    def _compress_text(self, text: str, max_length: int) -> str:
        """텍스트 압축: 패턴 정리 + 길이 제한."""
        if not text:
            return text

        # 패턴 압축
        compressed = text
        for pattern, replacement in self.PATTERNS_TO_COMPRESS:
            compressed = re.sub(pattern, replacement, compressed)

        # 앞뒤 공백 정리
        compressed = compressed.strip()

        # 길이 제한
        if len(compressed) > max_length:
            # 앞부분 우선, 뒷부분 일부 유지
            front_len = int(max_length * 0.7)
            back_len = int(max_length * 0.25)
            compressed = compressed[:front_len] + "\n...[truncated]...\n" + compressed[-back_len:]

        return compressed

    def _compress_observation(self, observation: str, max_length: int) -> str:
        """도구 출력 압축: 더 공격적."""
        if not observation:
            return observation

        # 패턴 압축
        compressed = observation
        for pattern, replacement in self.PATTERNS_TO_COMPRESS:
            compressed = re.sub(pattern, replacement, compressed)

        # JSON 출력 압축 (긴 배열/객체)
        compressed = re.sub(r'\[\s*\{[^}]{500,}', '[{...', compressed)
        compressed = re.sub(r'\{[^}]{1000,}\}', '{...large object...}', compressed)

        # 로그 스타일 출력 압축 (타임스탬프 등)
        compressed = re.sub(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[.\d]*[Z]?', '[TIME]', compressed)

        # 경로 중복 제거
        compressed = re.sub(r'/home/\w+/', '~/', compressed)

        # 길이 제한
        if len(compressed) > max_length:
            front_len = int(max_length * 0.6)
            back_len = int(max_length * 0.3)
            compressed = compressed[:front_len] + "\n...[output truncated]...\n" + compressed[-back_len:]

        return compressed

    def get_stats(self) -> dict:
        """압축 통계 반환."""
        total_orig = self.stats["total_original"]
        total_comp = self.stats["total_compressed"]
        ratio = total_comp / total_orig if total_orig > 0 else 1.0

        return {
            "compressions": self.stats["compressions"],
            "total_original_chars": total_orig,
            "total_compressed_chars": total_comp,
            "overall_ratio": round(ratio, 4),
            "savings_percent": round((1 - ratio) * 100, 2)
        }

    def reset_stats(self):
        """통계 초기화."""
        self.stats = {
            "compressions": 0,
            "total_original": 0,
            "total_compressed": 0
        }
