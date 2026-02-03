"""
Groq API 키 5개 로테이션. rate limit 시 자동 다음 키 전환.
GROQ_API_KEY_1 ~ GROQ_API_KEY_5 환경변수 사용.
"""

import os
import time
import httpx
from itertools import cycle
from typing import Optional, List
from dotenv import load_dotenv

# Auto-load .env from addon directory
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))


class GroqRotator:
    def __init__(self):
        self.keys = self._load_keys()
        self._cycle = cycle(range(len(self.keys))) if self.keys else None
        self._current_idx = 0
        self._fail_counts = {i: 0 for i in range(len(self.keys))}

    def _load_keys(self) -> List[str]:
        keys = []
        for i in range(1, 6):
            k = os.environ.get(f"GROQ_API_KEY_{i}", "")
            if k:
                keys.append(k)
        if not keys:
            single = os.environ.get("GROQ_API_KEY", "")
            if single:
                keys.append(single)
        return keys

    def next_key(self) -> str:
        if not self.keys:
            return ""
        self._current_idx = next(self._cycle)
        return self.keys[self._current_idx]

    def chat(self, messages: list, model: str = "llama-3.3-70b-versatile",
             max_tokens: int = 4096, temperature: float = 0.3,
             max_retries: int = 5) -> Optional[str]:
        last_error = None
        for attempt in range(max_retries):
            key = self.next_key()
            if not key:
                return None
            try:
                resp = httpx.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json={"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature},
                    timeout=60
                )
                if resp.status_code == 200:
                    self._fail_counts[self._current_idx] = 0
                    return resp.json()["choices"][0]["message"]["content"]
                elif resp.status_code == 429:
                    self._fail_counts[self._current_idx] += 1
                    time.sleep(min(2 ** attempt, 10))
                    continue
                elif resp.status_code == 401:
                    self._fail_counts[self._current_idx] = 99
                    continue
                else:
                    last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                    continue
            except httpx.TimeoutException:
                last_error = "Timeout"
                continue
            except Exception as e:
                last_error = str(e)
                continue
        return None

    def status(self) -> dict:
        return {"total_keys": len(self.keys), "fail_counts": self._fail_counts, "current_idx": self._current_idx}


_rotator = None

def get_groq() -> GroqRotator:
    global _rotator
    if _rotator is None:
        _rotator = GroqRotator()
    return _rotator


if __name__ == "__main__":
    g = GroqRotator()
    print(f"로드된 키: {len(g.keys)}개")
    for i, k in enumerate(g.keys):
        print(f"  KEY_{i+1}: {k[:8]}...{k[-4:]}") if k else None
    if g.keys:
        result = g.chat([{"role": "user", "content": "Say hello in Korean"}],
                         model="llama-3.1-8b-instant", max_tokens=50)
        print(f"테스트: {result}" if result else "LLM 호출 실패 (키 확인 필요)")
    else:
        print("Groq 키가 없습니다. addon/.env에 GROQ_API_KEY_1~5를 설정하세요.")
