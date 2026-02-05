"""
Tavily API 유틸리티
- 6키 라운드로빈
- rate limit 방어
- 결과 정규화
"""

import os
import logging
import time
from typing import List, Dict, Any, Optional

logger = logging.getLogger("predator.tavily")


class TavilyPool:
    """Tavily API 키 풀 — 라운드로빈."""

    def __init__(self):
        self.keys = self._load_keys()
        self._index = 0
        self._call_count = 0
        self._daily_limit_per_key = 100  # 안전 마진

    def _load_keys(self) -> List[str]:
        """환경변수에서 Tavily 키 로드."""
        keys = []
        # TAVILY_API_KEY, TAVILY_API_KEY_2, ... TAVILY_API_KEY_6
        main_key = os.environ.get("TAVILY_API_KEY", "")
        if main_key:
            keys.append(main_key)
        for i in range(2, 10):
            key = os.environ.get(f"TAVILY_API_KEY_{i}", "")
            if key:
                keys.append(key)
        if not keys:
            logger.warning("No Tavily API keys found")
        else:
            logger.info(f"Tavily pool: {len(keys)} keys loaded")
        return keys

    def _next_key(self) -> Optional[str]:
        """다음 키 반환 (라운드로빈)."""
        if not self.keys:
            return None
        key = self.keys[self._index % len(self.keys)]
        self._index += 1
        self._call_count += 1
        return key

    async def search(self, query: str, max_results: int = 5,
                     search_depth: str = "basic") -> List[Dict]:
        """Tavily 검색."""
        key = self._next_key()
        if not key:
            logger.error("No Tavily keys available")
            return []

        try:
            from tavily import TavilyClient
            client = TavilyClient(api_key=key)
            response = client.search(
                query=query,
                max_results=max_results,
                search_depth=search_depth
            )
            results = response.get("results", [])
            return [
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "content": r.get("content", "")[:500],
                    "score": r.get("score", 0),
                }
                for r in results
            ]
        except Exception as e:
            error_msg = str(e)
            if "rate" in error_msg.lower() or "limit" in error_msg.lower():
                logger.warning(f"Tavily rate limit on key #{self._index}: {e}")
                # 다음 키로 재시도
                return await self.search(query, max_results, search_depth)
            logger.error(f"Tavily error: {e}")
            return []

    async def extract(self, url: str) -> str:
        """URL 본문 추출."""
        key = self._next_key()
        if not key:
            return ""
        try:
            from tavily import TavilyClient
            client = TavilyClient(api_key=key)
            response = client.extract(urls=[url])
            results = response.get("results", [])
            if results:
                return results[0].get("raw_content", "")[:3000]
            return ""
        except Exception as e:
            logger.warning(f"Tavily extract error: {e}")
            return ""

    def get_stats(self) -> dict:
        return {
            "keys": len(self.keys),
            "total_calls": self._call_count,
            "current_index": self._index % max(len(self.keys), 1)
        }


# 싱글톤
_pool = None

def get_tavily_pool() -> TavilyPool:
    global _pool
    if _pool is None:
        _pool = TavilyPool()
    return _pool
