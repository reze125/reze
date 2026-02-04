"""GPTCache Manager - 시맨틱 캐시.

유사한 질문에 대해 캐시된 응답 반환. API 호출 최대 10x 절감.

핵심 원칙:
1. 정확한 문자열 매칭 + 키워드 오버랩 매칭
2. TTL 기반 자동 만료 (실시간 1시간, FAQ 7일, 스케줄 결과 24시간)
3. 피드백 기반 캐시 무효화 (실패한 응답은 삭제)

NOTE: 임베딩 기반 시맨틱 매칭은 Phase 3에서 Qdrant 통합 시 추가.
현재는 정확 매칭 + 키워드 오버랩으로 시작.
"""

import sqlite3
import hashlib
import json
import time
import re
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List

logger = logging.getLogger("REZE.gptcache")

# TTL 설정 (초)
TTL_CONFIG = {
    "realtime": 3600,       # 1시간 (헬스체크, 상태 조회)
    "daily": 86400,         # 24시간 (스케줄러 결과, 일일 리포트)
    "weekly": 604800,       # 7일 (FAQ, 고정 지식)
    "default": 21600,       # 6시간
}

# 키워드 유사도 매칭 임계값
KEYWORD_SIMILARITY_THRESHOLD = 0.7


class GPTCacheManager:
    """
    GPTCache - LLM 응답 시맨틱 캐시.

    캐시 저장소: SQLite (추가 인프라 불필요)
    유사도 매칭: 문자열 해시 (정확 매칭) + 키워드 오버랩 (근사 매칭)
    """

    def __init__(self, db_path: str = None):
        """
        Args:
            db_path: SQLite DB 경로. None이면 기본 경로 사용.
        """
        if db_path is None:
            base_dir = Path(__file__).parent.parent
            db_path = str(base_dir / "cache" / "gptcache.db")

        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._init_tables()

        # 통계
        self._hits = 0
        self._misses = 0

    def _init_tables(self):
        """캐시 테이블 초기화."""
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS cache_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query_hash TEXT NOT NULL,
                query_text TEXT NOT NULL,
                query_keywords TEXT,
                response TEXT NOT NULL,
                model TEXT,
                ttl_category TEXT DEFAULT 'default',
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                hit_count INTEGER DEFAULT 0,
                last_hit_at REAL
            )
        """)
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_cache_hash ON cache_entries(query_hash)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_cache_expires ON cache_entries(expires_at)"
        )
        self.conn.commit()

    def _hash_query(self, query: str) -> str:
        """쿼리 해시 생성."""
        normalized = query.strip().lower()
        return hashlib.sha256(normalized.encode()).hexdigest()[:32]

    def _extract_keywords(self, text: str) -> List[str]:
        """텍스트에서 키워드 추출."""
        # 한글/영어 단어 추출
        words = re.findall(r'[가-힣]+|[a-zA-Z]+', text.lower())
        # 2글자 이상만
        words = [w for w in words if len(w) >= 2]
        # 불용어 제거 (간단한 목록)
        stopwords = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
                     'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
                     'would', 'could', 'should', 'may', 'might', 'must', 'shall',
                     '이', '그', '저', '것', '등', '및', '또는', '그리고'}
        words = [w for w in words if w not in stopwords]
        # 빈도순 정렬 후 상위 10개
        from collections import Counter
        counter = Counter(words)
        return [w for w, _ in counter.most_common(10)]

    def _keyword_similarity(self, keywords1: List[str], keywords2: List[str]) -> float:
        """두 키워드 리스트의 유사도 (Jaccard)."""
        if not keywords1 or not keywords2:
            return 0.0
        set1, set2 = set(keywords1), set(keywords2)
        intersection = len(set1 & set2)
        union = len(set1 | set2)
        return intersection / union if union > 0 else 0.0

    def get(self, query: str) -> Optional[Dict[str, Any]]:
        """
        캐시에서 응답 조회.

        1단계: query_hash 정확 매칭 (O(1))
        2단계: 키워드 오버랩 매칭 (상위 후보 중 유사도 70%+ 시 반환)

        Args:
            query: 쿼리 문자열

        Returns:
            {"response": ..., "model": ..., "cached": True} or None
        """
        now = time.time()
        query_hash = self._hash_query(query)

        # 1단계: 정확 매칭
        row = self.conn.execute("""
            SELECT id, response, model, hit_count
            FROM cache_entries
            WHERE query_hash = ? AND expires_at > ?
            ORDER BY created_at DESC
            LIMIT 1
        """, (query_hash, now)).fetchone()

        if row:
            entry_id, response, model, hit_count = row
            # 히트 카운트 업데이트
            self.conn.execute("""
                UPDATE cache_entries
                SET hit_count = ?, last_hit_at = ?
                WHERE id = ?
            """, (hit_count + 1, now, entry_id))
            self.conn.commit()

            self._hits += 1
            logger.info(f"[GPTCache] EXACT HIT - model: {model}, hits: {hit_count + 1}")
            return {"response": response, "model": model, "cached": True, "match_type": "exact"}

        # 2단계: 키워드 유사도 매칭
        query_keywords = self._extract_keywords(query)
        if not query_keywords:
            self._misses += 1
            return None

        # 최근 1000개 항목에서 유사도 검색
        rows = self.conn.execute("""
            SELECT id, query_keywords, response, model, hit_count
            FROM cache_entries
            WHERE expires_at > ? AND query_keywords IS NOT NULL
            ORDER BY created_at DESC
            LIMIT 1000
        """, (now,)).fetchall()

        best_match = None
        best_similarity = 0.0

        for row in rows:
            entry_id, stored_keywords_json, response, model, hit_count = row
            try:
                stored_keywords = json.loads(stored_keywords_json)
            except (json.JSONDecodeError, TypeError):
                continue

            similarity = self._keyword_similarity(query_keywords, stored_keywords)
            if similarity > best_similarity and similarity >= KEYWORD_SIMILARITY_THRESHOLD:
                best_similarity = similarity
                best_match = (entry_id, response, model, hit_count)

        if best_match:
            entry_id, response, model, hit_count = best_match
            # 히트 카운트 업데이트
            self.conn.execute("""
                UPDATE cache_entries
                SET hit_count = ?, last_hit_at = ?
                WHERE id = ?
            """, (hit_count + 1, now, entry_id))
            self.conn.commit()

            self._hits += 1
            logger.info(
                f"[GPTCache] KEYWORD HIT - similarity: {best_similarity:.2f}, "
                f"model: {model}, hits: {hit_count + 1}"
            )
            return {
                "response": response,
                "model": model,
                "cached": True,
                "match_type": "keyword",
                "similarity": best_similarity
            }

        self._misses += 1
        return None

    def set(
        self,
        query: str,
        response: str,
        model: str = None,
        ttl_category: str = "default"
    ):
        """
        캐시에 응답 저장.

        Args:
            query: 쿼리 문자열
            response: LLM 응답
            model: 사용된 모델
            ttl_category: TTL 카테고리 (realtime/daily/weekly/default)
        """
        now = time.time()
        query_hash = self._hash_query(query)
        keywords = self._extract_keywords(query)
        ttl = TTL_CONFIG.get(ttl_category, TTL_CONFIG["default"])
        expires_at = now + ttl

        # 기존 항목이 있으면 업데이트, 없으면 삽입
        existing = self.conn.execute(
            "SELECT id FROM cache_entries WHERE query_hash = ?",
            (query_hash,)
        ).fetchone()

        if existing:
            self.conn.execute("""
                UPDATE cache_entries
                SET response = ?, model = ?, ttl_category = ?,
                    created_at = ?, expires_at = ?, query_keywords = ?
                WHERE id = ?
            """, (response, model, ttl_category, now, expires_at,
                  json.dumps(keywords, ensure_ascii=False), existing[0]))
        else:
            self.conn.execute("""
                INSERT INTO cache_entries
                (query_hash, query_text, query_keywords, response, model,
                 ttl_category, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (query_hash, query[:500], json.dumps(keywords, ensure_ascii=False),
                  response, model, ttl_category, now, expires_at))

        self.conn.commit()
        logger.debug(f"[GPTCache] SET - ttl: {ttl_category} ({ttl}s), model: {model}")

    def invalidate(self, query: str):
        """캐시 항목 무효화."""
        query_hash = self._hash_query(query)
        cursor = self.conn.execute(
            "DELETE FROM cache_entries WHERE query_hash = ?",
            (query_hash,)
        )
        if cursor.rowcount > 0:
            self.conn.commit()
            logger.info(f"[GPTCache] Invalidated {cursor.rowcount} entries")

    def cleanup(self) -> int:
        """만료된 캐시 정리."""
        now = time.time()
        cursor = self.conn.execute(
            "DELETE FROM cache_entries WHERE expires_at < ?",
            (now,)
        )
        deleted = cursor.rowcount
        self.conn.commit()

        if deleted > 0:
            logger.info(f"[GPTCache] Cleanup: {deleted} expired entries removed")

        return deleted

    def stats(self) -> Dict[str, Any]:
        """캐시 통계."""
        row = self.conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(hit_count) as total_hits,
                COUNT(CASE WHEN ttl_category = 'realtime' THEN 1 END) as realtime,
                COUNT(CASE WHEN ttl_category = 'daily' THEN 1 END) as daily,
                COUNT(CASE WHEN ttl_category = 'weekly' THEN 1 END) as weekly,
                COUNT(CASE WHEN ttl_category = 'default' THEN 1 END) as default_cat
            FROM cache_entries
            WHERE expires_at > ?
        """, (time.time(),)).fetchone()

        total_requests = self._hits + self._misses
        hit_rate = (self._hits / total_requests * 100) if total_requests > 0 else 0.0

        return {
            "total_entries": row[0] or 0,
            "total_hits": row[1] or 0,
            "session_hits": self._hits,
            "session_misses": self._misses,
            "hit_rate": round(hit_rate, 1),
            "by_category": {
                "realtime": row[2] or 0,
                "daily": row[3] or 0,
                "weekly": row[4] or 0,
                "default": row[5] or 0
            }
        }

    def determine_ttl(self, query: str) -> str:
        """
        쿼리 유형에 따른 TTL 카테고리 결정.

        Args:
            query: 쿼리 문자열

        Returns:
            TTL 카테고리 (realtime/daily/weekly/default)
        """
        query_lower = query.lower()

        # 실시간 조회 (1시간)
        realtime_keywords = ['status', '상태', 'health', '헬스', 'check', '체크',
                            'ping', 'alive', 'running', '실행중']
        if any(kw in query_lower for kw in realtime_keywords):
            return "realtime"

        # FAQ/고정 지식 (7일)
        faq_keywords = ['what is', '무엇', 'how to', '방법', 'explain', '설명',
                       'definition', '정의', 'difference', '차이']
        if any(kw in query_lower for kw in faq_keywords):
            return "weekly"

        # 일일 보고서/스케줄 (24시간)
        daily_keywords = ['daily', '일일', 'report', '보고', 'summary', '요약',
                         'schedule', '스케줄', 'today', '오늘']
        if any(kw in query_lower for kw in daily_keywords):
            return "daily"

        return "default"

    def close(self):
        """DB 연결 종료."""
        self.conn.close()


# 싱글톤 인스턴스
_cache_instance: Optional[GPTCacheManager] = None


def get_cache() -> GPTCacheManager:
    """GPTCache 싱글톤 인스턴스 반환."""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = GPTCacheManager()
    return _cache_instance
