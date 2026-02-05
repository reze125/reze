"""
Phase 5 Wave 1: PREDATOR RSS Absorber
REZE v6.0 SOVEREIGN - Stage 1: 흡수 (Absorb)

$0 API Cost - RSS 피드만 사용
feedparser 라이브러리 필요: pip install feedparser

실행: python -m fish.predator.absorber
"""

import asyncio
import sqlite3
import logging
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
import json
import uuid

try:
    import feedparser
    FEEDPARSER_AVAILABLE = True
except ImportError:
    FEEDPARSER_AVAILABLE = False

logger = logging.getLogger("reze.predator.absorber")


# ═══════════════════════════════════════════════════════════════
# 기본 RSS 소스 (14개, $0 Cost)
# ═══════════════════════════════════════════════════════════════

DEFAULT_RSS_SOURCES = [
    # ─── Tech / AI ───
    {
        "source_id": "hackernews",
        "name": "Hacker News",
        "url": "https://hnrss.org/frontpage",
        "category": "tech",
        "language": "en",
        "priority": 10
    },
    {
        "source_id": "techcrunch",
        "name": "TechCrunch",
        "url": "https://techcrunch.com/feed/",
        "category": "tech",
        "language": "en",
        "priority": 8
    },
    {
        "source_id": "mit_tech_review",
        "name": "MIT Technology Review",
        "url": "https://www.technologyreview.com/feed/",
        "category": "tech",
        "language": "en",
        "priority": 9
    },
    {
        "source_id": "theverge",
        "name": "The Verge",
        "url": "https://www.theverge.com/rss/index.xml",
        "category": "tech",
        "language": "en",
        "priority": 7
    },

    # ─── AI / ML ───
    {
        "source_id": "arxiv_ai",
        "name": "arXiv AI",
        "url": "https://rss.arxiv.org/rss/cs.AI",
        "category": "ai",
        "language": "en",
        "priority": 10
    },
    {
        "source_id": "openai_blog",
        "name": "OpenAI Blog",
        "url": "https://openai.com/blog/rss.xml",
        "category": "ai",
        "language": "en",
        "priority": 10
    },

    # ─── Dev / Engineering ───
    {
        "source_id": "github_trending",
        "name": "GitHub Trending",
        "url": "https://rsshub.app/github/trending/daily",
        "category": "dev",
        "language": "en",
        "priority": 8
    },
    {
        "source_id": "devto",
        "name": "DEV.to",
        "url": "https://dev.to/feed",
        "category": "dev",
        "language": "en",
        "priority": 7
    },

    # ─── Business / Startup ───
    {
        "source_id": "ycombinator",
        "name": "Y Combinator Blog",
        "url": "https://www.ycombinator.com/blog/rss/",
        "category": "startup",
        "language": "en",
        "priority": 9
    },
    {
        "source_id": "firstround",
        "name": "First Round Review",
        "url": "https://review.firstround.com/feed.xml",
        "category": "startup",
        "language": "en",
        "priority": 8
    },

    # ─── Korean Tech ───
    {
        "source_id": "geekn",
        "name": "GeekNews",
        "url": "https://news.hada.io/rss",
        "category": "tech",
        "language": "ko",
        "priority": 9
    },
    {
        "source_id": "disquiet",
        "name": "Disquiet",
        "url": "https://disquiet.io/rss.xml",
        "category": "startup",
        "language": "ko",
        "priority": 8
    },

    # ─── Marketing / SEO ───
    {
        "source_id": "moz_blog",
        "name": "Moz Blog",
        "url": "https://moz.com/blog/feed",
        "category": "marketing",
        "language": "en",
        "priority": 7
    },
    {
        "source_id": "searchenginejournal",
        "name": "Search Engine Journal",
        "url": "https://www.searchenginejournal.com/feed/",
        "category": "marketing",
        "language": "en",
        "priority": 6
    },
]


@dataclass
class AbsorbResult:
    """흡수 결과"""
    source_id: str
    source_name: str
    items_fetched: int = 0
    items_new: int = 0
    items_duplicate: int = 0
    items_error: int = 0
    duration_sec: float = 0.0
    error: Optional[str] = None


@dataclass
class AbsorbCycleResult:
    """흡수 사이클 결과"""
    cycle_id: str
    sources_processed: int = 0
    total_fetched: int = 0
    total_new: int = 0
    total_duplicate: int = 0
    total_error: int = 0
    duration_sec: float = 0.0
    results: List[AbsorbResult] = field(default_factory=list)
    error: Optional[str] = None


class RSSAbsorber:
    """
    RSS 피드 흡수 엔진

    $0 API Cost - feedparser로 RSS 직접 파싱
    """

    def __init__(
        self,
        db_path: str = None,
        max_items_per_source: int = 50,
        fetch_timeout: int = 30
    ):
        if not FEEDPARSER_AVAILABLE:
            raise ImportError("feedparser not installed. Run: pip install feedparser")

        self.db_path = db_path or str(
            Path.home() / "reze-agent" / "reze_data" / "ssot.sqlite"
        )
        self.max_items_per_source = max_items_per_source
        self.fetch_timeout = fetch_timeout

    def _get_conn(self) -> sqlite3.Connection:
        """WAL 모드 연결"""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    def init_default_sources(self) -> int:
        """기본 RSS 소스 등록"""
        conn = self._get_conn()
        now = datetime.now().isoformat()
        count = 0

        for source in DEFAULT_RSS_SOURCES:
            try:
                conn.execute("""
                    INSERT OR IGNORE INTO rss_sources
                    (source_id, name, url, category, language, priority, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    source["source_id"],
                    source["name"],
                    source["url"],
                    source["category"],
                    source.get("language", "en"),
                    source.get("priority", 5),
                    now
                ))
                if conn.total_changes:
                    count += 1
            except Exception as e:
                logger.warning(f"Failed to add source {source['name']}: {e}")

        conn.commit()
        conn.close()
        logger.info(f"📡 Initialized {count} RSS sources")
        return count

    def get_active_sources(self) -> List[Dict[str, Any]]:
        """활성 소스 목록"""
        conn = self._get_conn()
        cursor = conn.execute("""
            SELECT source_id, name, url, category, language, priority,
                   last_fetched_at, fetch_interval_minutes, total_items_absorbed
            FROM rss_sources
            WHERE active = 1
            ORDER BY priority DESC, last_fetched_at ASC NULLS FIRST
        """)
        sources = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return sources

    def _should_fetch(self, source: Dict[str, Any]) -> bool:
        """소스 갱신 필요 여부"""
        last_fetched = source.get("last_fetched_at")
        if not last_fetched:
            return True

        try:
            last_dt = datetime.fromisoformat(last_fetched)
            interval = source.get("fetch_interval_minutes", 60)
            next_fetch = last_dt + timedelta(minutes=interval)
            return datetime.now() > next_fetch
        except:
            return True

    def _generate_absorb_id(self, source_id: str, guid: str) -> str:
        """흡수 ID 생성"""
        content = f"{source_id}:{guid}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def _parse_feed(self, url: str) -> Tuple[List[Dict], Optional[str]]:
        """RSS 피드 파싱"""
        try:
            feed = feedparser.parse(url)

            if feed.bozo and feed.bozo_exception:
                return [], f"Parse error: {feed.bozo_exception}"

            entries = []
            for entry in feed.entries[:self.max_items_per_source]:
                # 기본 필드 추출
                item = {
                    "guid": entry.get("id") or entry.get("link") or str(uuid.uuid4()),
                    "title": entry.get("title", ""),
                    "link": entry.get("link", ""),
                    "published": None,
                    "summary": entry.get("summary", ""),
                    "content": "",
                    "author": entry.get("author", ""),
                    "tags": []
                }

                # published date
                if entry.get("published_parsed"):
                    try:
                        item["published"] = datetime(*entry.published_parsed[:6]).isoformat()
                    except:
                        pass
                elif entry.get("updated_parsed"):
                    try:
                        item["published"] = datetime(*entry.updated_parsed[:6]).isoformat()
                    except:
                        pass

                # content (if available)
                if entry.get("content"):
                    item["content"] = entry.content[0].get("value", "")

                # tags
                if entry.get("tags"):
                    item["tags"] = [t.get("term", "") for t in entry.tags if t.get("term")]

                entries.append(item)

            return entries, None

        except Exception as e:
            return [], str(e)

    async def absorb_source(self, source: Dict[str, Any]) -> AbsorbResult:
        """단일 소스 흡수"""
        start_time = datetime.now()
        source_id = source["source_id"]
        source_name = source["name"]
        url = source["url"]

        result = AbsorbResult(source_id=source_id, source_name=source_name)

        # RSS 파싱 (blocking call in thread)
        loop = asyncio.get_event_loop()
        entries, error = await loop.run_in_executor(
            None, self._parse_feed, url
        )

        if error:
            result.error = error
            self._record_error(source_id, "parse_error", error)
            result.duration_sec = (datetime.now() - start_time).total_seconds()
            return result

        result.items_fetched = len(entries)

        # DB 저장
        conn = self._get_conn()
        now = datetime.now().isoformat()

        for entry in entries:
            absorb_id = self._generate_absorb_id(source_id, entry["guid"])

            try:
                conn.execute("""
                    INSERT INTO absorbed_raw
                    (absorb_id, source_id, guid, title, link, published_at,
                     summary, content, author, tags, digest_status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                """, (
                    absorb_id,
                    source_id,
                    entry["guid"],
                    entry["title"],
                    entry["link"],
                    entry["published"],
                    entry["summary"][:2000] if entry["summary"] else None,
                    entry["content"][:5000] if entry["content"] else None,
                    entry["author"],
                    json.dumps(entry["tags"]) if entry["tags"] else None,
                    now
                ))
                result.items_new += 1
            except sqlite3.IntegrityError:
                result.items_duplicate += 1
            except Exception as e:
                result.items_error += 1
                logger.warning(f"Error saving entry {entry['title'][:30]}: {e}")

        # 소스 업데이트
        conn.execute("""
            UPDATE rss_sources
            SET last_fetched_at = ?,
                total_items_absorbed = total_items_absorbed + ?
            WHERE source_id = ?
        """, (now, result.items_new, source_id))

        conn.commit()
        conn.close()

        result.duration_sec = (datetime.now() - start_time).total_seconds()
        logger.info(
            f"📥 {source_name}: {result.items_new} new, "
            f"{result.items_duplicate} dup, {result.items_error} err "
            f"({result.duration_sec:.1f}s)"
        )

        return result

    def _record_error(self, source_id: str, error_type: str, message: str):
        """에러 기록"""
        conn = self._get_conn()
        error_id = f"err_{uuid.uuid4().hex[:8]}"
        now = datetime.now().isoformat()

        try:
            conn.execute("""
                INSERT INTO absorption_errors
                (error_id, source_id, error_type, error_message, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (error_id, source_id, error_type, message, now))

            # 소스 에러 카운트 증가
            conn.execute("""
                UPDATE rss_sources
                SET error_count = error_count + 1
                WHERE source_id = ?
            """, (source_id,))

            conn.commit()
        except Exception as e:
            logger.warning(f"Failed to record error: {e}")
        finally:
            conn.close()

    async def run_absorb_cycle(
        self,
        force: bool = False,
        max_sources: int = None
    ) -> AbsorbCycleResult:
        """
        흡수 사이클 실행

        Args:
            force: True면 fetch_interval 무시
            max_sources: 최대 소스 수 (None이면 전체)
        """
        cycle_id = f"absorb_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        start_time = datetime.now()

        result = AbsorbCycleResult(cycle_id=cycle_id)

        try:
            sources = self.get_active_sources()
            if max_sources:
                sources = sources[:max_sources]

            # 갱신 필요한 소스만
            if not force:
                sources = [s for s in sources if self._should_fetch(s)]

            result.sources_processed = len(sources)

            if not sources:
                logger.info("📡 No sources need update")
                return result

            # 병렬 흡수 (5개씩 배치)
            batch_size = 5
            for i in range(0, len(sources), batch_size):
                batch = sources[i:i + batch_size]
                tasks = [self.absorb_source(s) for s in batch]
                batch_results = await asyncio.gather(*tasks, return_exceptions=True)

                for r in batch_results:
                    if isinstance(r, Exception):
                        result.total_error += 1
                        logger.error(f"Absorb exception: {r}")
                    else:
                        result.results.append(r)
                        result.total_fetched += r.items_fetched
                        result.total_new += r.items_new
                        result.total_duplicate += r.items_duplicate
                        result.total_error += r.items_error

            result.duration_sec = (datetime.now() - start_time).total_seconds()

            # 사이클 로그
            self._log_cycle(result)

            logger.info(
                f"🔄 Absorb cycle complete: {result.sources_processed} sources, "
                f"{result.total_new} new items ({result.duration_sec:.1f}s)"
            )

        except Exception as e:
            result.error = str(e)
            logger.error(f"Absorb cycle error: {e}")

        return result

    def _log_cycle(self, result: AbsorbCycleResult):
        """사이클 로그 저장"""
        conn = self._get_conn()
        now = datetime.now().isoformat()

        try:
            conn.execute("""
                INSERT INTO predator_cycles
                (cycle_id, stage, items_processed, items_success, items_failed,
                 duration_sec, created_at, completed_at)
                VALUES (?, 'absorb', ?, ?, ?, ?, ?, ?)
            """, (
                result.cycle_id,
                result.total_fetched,
                result.total_new,
                result.total_error,
                result.duration_sec,
                now,
                now
            ))
            conn.commit()
        except Exception as e:
            logger.warning(f"Failed to log cycle: {e}")
        finally:
            conn.close()

    def get_pending_items(self, limit: int = 100) -> List[Dict[str, Any]]:
        """소화 대기 아이템"""
        conn = self._get_conn()
        cursor = conn.execute("""
            SELECT absorb_id, source_id, title, link, published_at,
                   summary, content, author, tags
            FROM absorbed_raw
            WHERE digest_status = 'pending'
            ORDER BY published_at DESC NULLS LAST
            LIMIT ?
        """, (limit,))
        items = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return items

    def get_stats(self) -> Dict[str, Any]:
        """흡수 통계"""
        conn = self._get_conn()

        # 소스 통계
        sources = conn.execute("""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN active = 1 THEN 1 ELSE 0 END) as active,
                   SUM(total_items_absorbed) as total_absorbed
            FROM rss_sources
        """).fetchone()

        # 아이템 통계
        items = conn.execute("""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN digest_status = 'pending' THEN 1 ELSE 0 END) as pending,
                   SUM(CASE WHEN digest_status = 'digested' THEN 1 ELSE 0 END) as digested
            FROM absorbed_raw
        """).fetchone()

        # 최근 에러
        errors = conn.execute("""
            SELECT COUNT(*) as count FROM absorption_errors
            WHERE created_at > datetime('now', '-24 hours')
        """).fetchone()

        conn.close()

        return {
            "sources": {
                "total": sources["total"] or 0,
                "active": sources["active"] or 0,
                "total_absorbed": sources["total_absorbed"] or 0
            },
            "items": {
                "total": items["total"] or 0,
                "pending": items["pending"] or 0,
                "digested": items["digested"] or 0
            },
            "errors_24h": errors["count"] or 0
        }


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

async def main():
    """테스트 실행"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )

    absorber = RSSAbsorber()

    # 기본 소스 등록
    print("\n📡 Initializing default RSS sources...")
    absorber.init_default_sources()

    # 소스 목록
    sources = absorber.get_active_sources()
    print(f"\n📋 Active sources: {len(sources)}")
    for s in sources[:5]:
        print(f"   - {s['name']} ({s['category']})")

    # 흡수 실행
    print("\n🔄 Running absorb cycle (max 3 sources for test)...")
    result = await absorber.run_absorb_cycle(force=True, max_sources=3)

    print(f"\n📊 Absorb Result:")
    print(f"   Sources: {result.sources_processed}")
    print(f"   Fetched: {result.total_fetched}")
    print(f"   New: {result.total_new}")
    print(f"   Duplicate: {result.total_duplicate}")
    print(f"   Errors: {result.total_error}")
    print(f"   Duration: {result.duration_sec:.1f}s")

    # 통계
    stats = absorber.get_stats()
    print(f"\n📈 Stats:")
    print(f"   Total absorbed: {stats['sources']['total_absorbed']}")
    print(f"   Pending digest: {stats['items']['pending']}")


if __name__ == "__main__":
    asyncio.run(main())
