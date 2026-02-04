"""REZE v6.0 — LLM Response Cache Layer.

Lightweight cache for LLM responses using SQLite.
- Hash-based exact matching (fast)
- Keyword similarity matching (Phase 2 Gap Fix)
- TTL per role type
- Hit/miss statistics
"""

import hashlib
import json
import sqlite3
import time
import re
import logging
from pathlib import Path
from typing import Optional, List
from collections import Counter

logger = logging.getLogger("REZE.cache")

# 키워드 유사도 매칭 임계값
KEYWORD_SIMILARITY_THRESHOLD = 0.6


class REZECache:
    """SQLite-based LLM response cache with TTL support."""

    # TTL by step_type (hours)
    DEFAULT_TTLS = {
        "writing": 72,        # 블로그 콘텐츠: 3일
        "analysis": 24,       # 분석 리포트: 1일
        "creative": 48,       # 창의적 콘텐츠: 2일
        "reasoning": 12,      # 논리적 추론: 12시간
        "classification": 24, # 분류: 1일
        "evaluation": 6,      # 평가: 6시간
        "planning": 6,        # 계획: 6시간
        "reflection": 168,    # 반성: 7일
        "summarization": 24,  # 요약: 1일
        # tool_call, extraction, quick은 캐싱하지 않음
    }

    # 캐싱하지 않는 역할들 (실시간 데이터 필요)
    NO_CACHE_ROLES = {"tool_call", "extraction", "quick", "research"}

    def __init__(self, db_path: str = "reze_data/llm_cache.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._init_db()
        self.stats = {"hits": 0, "misses": 0, "skipped": 0, "invalidations": 0}

    def _init_db(self):
        """캐시 테이블 초기화."""
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS llm_cache (
                cache_key TEXT PRIMARY KEY,
                step_type TEXT NOT NULL,
                prompt_hash TEXT NOT NULL,
                prompt_keywords TEXT,
                response TEXT NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                hit_count INTEGER DEFAULT 0
            )
        """)
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_cache_expires ON llm_cache(expires_at)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_cache_type ON llm_cache(step_type)")
        # 키워드 컬럼이 없으면 추가 (마이그레이션)
        try:
            self.conn.execute("ALTER TABLE llm_cache ADD COLUMN prompt_keywords TEXT")
        except sqlite3.OperationalError:
            pass  # 이미 존재
        self.conn.commit()

    def _extract_keywords(self, text: str) -> List[str]:
        """텍스트에서 키워드 추출 (Phase 2 Gap Fix)."""
        # 한글/영어 단어 추출
        words = re.findall(r'[가-힣]+|[a-zA-Z]+', text.lower())
        # 2글자 이상만
        words = [w for w in words if len(w) >= 2]
        # 불용어 제거
        stopwords = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
                     'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
                     'would', 'could', 'should', 'may', 'might', 'must', 'shall',
                     'this', 'that', 'these', 'those', 'it', 'its',
                     '이', '그', '저', '것', '등', '및', '또는', '그리고', '을', '를', '에', '의'}
        words = [w for w in words if w not in stopwords]
        # 빈도순 정렬 후 상위 10개
        counter = Counter(words)
        return [w for w, _ in counter.most_common(10)]

    def _keyword_similarity(self, keywords1: List[str], keywords2: List[str]) -> float:
        """두 키워드 리스트의 Jaccard 유사도."""
        if not keywords1 or not keywords2:
            return 0.0
        set1, set2 = set(keywords1), set(keywords2)
        intersection = len(set1 & set2)
        union = len(set1 | set2)
        return intersection / union if union > 0 else 0.0

    def _make_key(self, prompt: str, step_type: str, system: str = "") -> str:
        """프롬프트 + 역할 + 시스템 프롬프트로 캐시 키 생성."""
        content = f"{step_type}:{system[:500]}:{prompt}"
        return hashlib.sha256(content.encode()).hexdigest()

    def should_cache(self, step_type: str) -> bool:
        """이 역할은 캐싱해야 하는가?"""
        return step_type not in self.NO_CACHE_ROLES

    def get(self, prompt: str, step_type: str, system: str = "") -> Optional[str]:
        """캐시에서 응답 조회. 없거나 만료되면 None.

        Phase 2 Gap Fix: 정확 매칭 실패 시 키워드 유사도 매칭 시도.
        """
        if not self.should_cache(step_type):
            self.stats["skipped"] += 1
            return None

        cache_key = self._make_key(prompt, step_type, system)
        now = time.time()

        # 1단계: 정확 매칭
        cursor = self.conn.execute("""
            SELECT response FROM llm_cache
            WHERE cache_key = ? AND expires_at > ?
        """, (cache_key, now))

        row = cursor.fetchone()
        if row:
            # Hit count 업데이트
            self.conn.execute("""
                UPDATE llm_cache SET hit_count = hit_count + 1
                WHERE cache_key = ?
            """, (cache_key,))
            self.conn.commit()
            self.stats["hits"] += 1
            logger.debug(f"Cache EXACT HIT for {step_type}: {cache_key[:16]}...")
            return row[0]

        # 2단계: 키워드 유사도 매칭 (Phase 2 Gap Fix)
        query_keywords = self._extract_keywords(prompt)
        if query_keywords:
            # 같은 step_type의 최근 100개 항목에서 유사도 검색
            rows = self.conn.execute("""
                SELECT cache_key, prompt_keywords, response
                FROM llm_cache
                WHERE step_type = ? AND expires_at > ? AND prompt_keywords IS NOT NULL
                ORDER BY created_at DESC
                LIMIT 100
            """, (step_type, now)).fetchall()

            best_match = None
            best_similarity = 0.0

            for row in rows:
                row_key, stored_keywords_json, response = row
                try:
                    stored_keywords = json.loads(stored_keywords_json)
                except (json.JSONDecodeError, TypeError):
                    continue

                similarity = self._keyword_similarity(query_keywords, stored_keywords)
                if similarity > best_similarity and similarity >= KEYWORD_SIMILARITY_THRESHOLD:
                    best_similarity = similarity
                    best_match = (row_key, response)

            if best_match:
                # Hit count 업데이트
                self.conn.execute("""
                    UPDATE llm_cache SET hit_count = hit_count + 1
                    WHERE cache_key = ?
                """, (best_match[0],))
                self.conn.commit()
                self.stats["hits"] += 1
                logger.info(f"Cache KEYWORD HIT for {step_type}: similarity={best_similarity:.2f}")
                return best_match[1]

        self.stats["misses"] += 1
        return None

    def set(self, prompt: str, step_type: str, response: str, system: str = "", ttl_hours: int = None):
        """응답을 캐시에 저장. Phase 2 Gap Fix: 키워드 저장 추가."""
        if not self.should_cache(step_type):
            return

        if not response or len(response) < 10:
            # 너무 짧은 응답은 캐싱하지 않음
            return

        cache_key = self._make_key(prompt, step_type, system)
        prompt_hash = hashlib.md5(prompt.encode()).hexdigest()
        # Phase 2 Gap Fix: 키워드 추출 및 저장
        keywords = self._extract_keywords(prompt)
        keywords_json = json.dumps(keywords, ensure_ascii=False) if keywords else None

        ttl = ttl_hours or self.DEFAULT_TTLS.get(step_type, 24)
        now = time.time()
        expires_at = now + (ttl * 3600)

        self.conn.execute("""
            INSERT OR REPLACE INTO llm_cache
            (cache_key, step_type, prompt_hash, prompt_keywords, response, created_at, expires_at, hit_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0)
        """, (cache_key, step_type, prompt_hash, keywords_json, response, now, expires_at))
        self.conn.commit()
        logger.debug(f"Cache SET for {step_type}: {cache_key[:16]}... (TTL: {ttl}h, keywords: {len(keywords) if keywords else 0})")

    def invalidate(self, prompt: str, step_type: str, system: str = ""):
        """특정 캐시 항목 무효화."""
        cache_key = self._make_key(prompt, step_type, system)
        cursor = self.conn.execute("DELETE FROM llm_cache WHERE cache_key = ?", (cache_key,))
        if cursor.rowcount > 0:
            self.stats["invalidations"] += 1
        self.conn.commit()

    def invalidate_by_type(self, step_type: str):
        """특정 역할의 모든 캐시 무효화."""
        cursor = self.conn.execute("DELETE FROM llm_cache WHERE step_type = ?", (step_type,))
        self.stats["invalidations"] += cursor.rowcount
        self.conn.commit()
        logger.info(f"Invalidated {cursor.rowcount} cache entries for {step_type}")

    def cleanup_expired(self) -> int:
        """만료된 캐시 항목 정리."""
        now = time.time()
        cursor = self.conn.execute("DELETE FROM llm_cache WHERE expires_at < ?", (now,))
        deleted = cursor.rowcount
        self.conn.commit()
        if deleted > 0:
            logger.info(f"Cleaned up {deleted} expired cache entries")
        return deleted

    def get_stats(self) -> dict:
        """캐시 통계 반환."""
        total_requests = self.stats["hits"] + self.stats["misses"]
        hit_rate = self.stats["hits"] / total_requests if total_requests > 0 else 0

        # DB 통계
        cursor = self.conn.execute("""
            SELECT COUNT(*), SUM(hit_count),
                   SUM(LENGTH(response)) / 1024.0 / 1024.0
            FROM llm_cache WHERE expires_at > ?
        """, (time.time(),))
        row = cursor.fetchone()
        active_entries = row[0] or 0
        total_hits_stored = row[1] or 0
        size_mb = row[2] or 0

        # 역할별 통계
        cursor = self.conn.execute("""
            SELECT step_type, COUNT(*), SUM(hit_count)
            FROM llm_cache WHERE expires_at > ?
            GROUP BY step_type
        """, (time.time(),))
        by_type = {r[0]: {"count": r[1], "hits": r[2] or 0} for r in cursor.fetchall()}

        return {
            "hits": self.stats["hits"],
            "misses": self.stats["misses"],
            "skipped": self.stats["skipped"],
            "invalidations": self.stats["invalidations"],
            "hit_rate": round(hit_rate, 4),
            "active_entries": active_entries,
            "total_hits_stored": total_hits_stored,
            "size_mb": round(size_mb, 2),
            "by_type": by_type
        }

    def close(self):
        """DB 연결 종료."""
        self.conn.close()
