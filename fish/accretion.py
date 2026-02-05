"""
EVENT HORIZON v3.0 — Accretion Disk
6개 소스에서 콘텐츠 기회를 빨아들이는 시스템

Sources:
1. Tavily (Web Search)
2. ProductHunt (New Tools)
3. Hacker News (Tech News)
4. GitHub Trending (Open Source)
5. Reddit (Community Insights)
6. GA4 (Internal Analytics)
"""

import asyncio
import logging
import json
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from enum import Enum

logger = logging.getLogger("reze.fish.accretion")


@dataclass
class ContentSignal:
    """Accretion Disk에서 감지된 콘텐츠 시그널"""
    source: str
    signal_type: str          # trending, new_tool, discussion, opportunity
    title: str
    url: str = ""
    score: float = 0.0        # 0.0-1.0 relevance/importance
    metadata: dict = field(default_factory=dict)
    detected_at: datetime = field(default_factory=datetime.now)


class AccretionDisk:
    """
    6개 소스에서 콘텐츠 기회를 수집하는 시스템.
    블랙홀처럼 주변의 모든 정보를 빨아들인다.
    """

    def __init__(self, ssot, config: dict = None):
        self.ssot = ssot
        self.config = config or {}

        # API 키 로드
        self._tavily_key = None
        self._load_api_keys()

    def _load_api_keys(self):
        """API 키 로드"""
        try:
            import config as app_config
            self._tavily_key = app_config.get_tavily_key()
        except Exception as e:
            logger.warning("AccretionDisk: Failed to load API keys: %s", e)

    # ═══════════════════════════════════════════════════════════════════════
    # 1. TAVILY — Web Search
    # ═══════════════════════════════════════════════════════════════════════

    async def scan_tavily(self, queries: List[str] = None) -> List[ContentSignal]:
        """Tavily로 웹 검색"""
        if not self._tavily_key:
            logger.warning("Tavily API key not available")
            return []

        queries = queries or [
            "AI tools launch 2025",
            "new AI startup funding",
            "best AI productivity tools",
            "AI writing assistant comparison",
        ]

        signals = []
        for query in queries[:3]:  # 비용 절약
            try:
                result = subprocess.run(
                    [
                        "curl", "-s", "-X", "POST",
                        "https://api.tavily.com/search",
                        "-H", "Content-Type: application/json",
                        "-d", json.dumps({
                            "api_key": self._tavily_key,
                            "query": query,
                            "search_depth": "basic",
                            "max_results": 5
                        })
                    ],
                    capture_output=True, text=True, timeout=15
                )

                data = json.loads(result.stdout)
                for item in data.get("results", [])[:3]:
                    signals.append(ContentSignal(
                        source="tavily",
                        signal_type="search",
                        title=item.get("title", ""),
                        url=item.get("url", ""),
                        score=min(item.get("score", 0.5), 1.0),
                        metadata={
                            "query": query,
                            "snippet": item.get("content", "")[:200],
                        }
                    ))
            except Exception as e:
                logger.warning("Tavily scan failed [%s]: %s", query, e)

        return signals

    # ═══════════════════════════════════════════════════════════════════════
    # 2. PRODUCTHUNT — New Tools
    # ═══════════════════════════════════════════════════════════════════════

    async def scan_producthunt(self) -> List[ContentSignal]:
        """ProductHunt에서 새 AI 도구 스캔"""
        signals = []

        try:
            # ProductHunt RSS/API (간단 버전 - 실제로는 GraphQL API 사용)
            result = subprocess.run(
                ["curl", "-s", "https://www.producthunt.com/feed?category=artificial-intelligence"],
                capture_output=True, text=True, timeout=15
            )

            # RSS 파싱 (간단한 정규식)
            import re
            titles = re.findall(r'<title><!\[CDATA\[(.*?)\]\]></title>', result.stdout)
            links = re.findall(r'<link>(https://www\.producthunt\.com/posts/[^<]+)</link>', result.stdout)

            for title, link in zip(titles[:5], links[:5]):
                if "AI" in title.upper() or "ARTIFICIAL" in title.upper():
                    signals.append(ContentSignal(
                        source="producthunt",
                        signal_type="new_tool",
                        title=title,
                        url=link,
                        score=0.6,
                        metadata={"category": "artificial-intelligence"}
                    ))
        except Exception as e:
            logger.warning("ProductHunt scan failed: %s", e)

        return signals

    # ═══════════════════════════════════════════════════════════════════════
    # 3. HACKER NEWS — Tech News
    # ═══════════════════════════════════════════════════════════════════════

    async def scan_hackernews(self, min_score: int = 50) -> List[ContentSignal]:
        """Hacker News 프론트페이지 스캔"""
        signals = []

        try:
            # HN API - Top stories
            result = subprocess.run(
                ["curl", "-s", "https://hacker-news.firebaseio.com/v0/topstories.json"],
                capture_output=True, text=True, timeout=10
            )

            story_ids = json.loads(result.stdout)[:30]

            for story_id in story_ids[:10]:  # 상위 10개만
                try:
                    detail = subprocess.run(
                        ["curl", "-s", f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json"],
                        capture_output=True, text=True, timeout=5
                    )
                    story = json.loads(detail.stdout)

                    title = story.get("title", "")
                    score = story.get("score", 0)

                    # AI 관련 + 최소 점수 필터
                    ai_keywords = ["ai", "gpt", "llm", "chatgpt", "claude", "gemini", "openai", "anthropic", "machine learning"]
                    is_ai_related = any(kw in title.lower() for kw in ai_keywords)

                    if is_ai_related and score >= min_score:
                        signals.append(ContentSignal(
                            source="hackernews",
                            signal_type="trending",
                            title=title,
                            url=story.get("url", f"https://news.ycombinator.com/item?id={story_id}"),
                            score=min(score / 500, 1.0),  # 500점 = 1.0
                            metadata={
                                "hn_score": score,
                                "comments": story.get("descendants", 0),
                                "hn_id": story_id,
                            }
                        ))
                except:
                    continue

        except Exception as e:
            logger.warning("HackerNews scan failed: %s", e)

        return signals

    # ═══════════════════════════════════════════════════════════════════════
    # 4. GITHUB — Open Source Trending
    # ═══════════════════════════════════════════════════════════════════════

    async def scan_github(self, language: str = None) -> List[ContentSignal]:
        """GitHub Trending AI 레포 스캔"""
        signals = []

        try:
            # GitHub Search API
            query = "AI OR LLM OR GPT language:python created:>2024-01-01"
            if language:
                query = f"AI OR LLM language:{language} created:>2024-01-01"

            result = subprocess.run(
                [
                    "curl", "-s",
                    f"https://api.github.com/search/repositories?q={query}&sort=stars&order=desc&per_page=10"
                ],
                capture_output=True, text=True, timeout=15
            )

            data = json.loads(result.stdout)

            for repo in data.get("items", [])[:5]:
                stars = repo.get("stargazers_count", 0)
                if stars >= 100:  # 최소 100스타
                    signals.append(ContentSignal(
                        source="github",
                        signal_type="trending_repo",
                        title=repo.get("full_name", ""),
                        url=repo.get("html_url", ""),
                        score=min(stars / 10000, 1.0),
                        metadata={
                            "stars": stars,
                            "description": repo.get("description", "")[:200],
                            "language": repo.get("language", ""),
                            "forks": repo.get("forks_count", 0),
                        }
                    ))
        except Exception as e:
            logger.warning("GitHub scan failed: %s", e)

        return signals

    # ═══════════════════════════════════════════════════════════════════════
    # 5. REDDIT — Community Insights
    # ═══════════════════════════════════════════════════════════════════════

    async def scan_reddit(self, subreddits: List[str] = None) -> List[ContentSignal]:
        """Reddit AI 서브레딧 스캔"""
        signals = []
        subreddits = subreddits or ["artificial", "MachineLearning", "ChatGPT", "LocalLLaMA"]

        for subreddit in subreddits[:2]:  # 2개만
            try:
                result = subprocess.run(
                    [
                        "curl", "-s", "-A", "REZE Bot/1.0",
                        f"https://www.reddit.com/r/{subreddit}/hot.json?limit=10"
                    ],
                    capture_output=True, text=True, timeout=10
                )

                data = json.loads(result.stdout)
                posts = data.get("data", {}).get("children", [])

                for post in posts[:5]:
                    post_data = post.get("data", {})
                    score = post_data.get("score", 0)

                    if score >= 100:  # 최소 100 업보트
                        signals.append(ContentSignal(
                            source="reddit",
                            signal_type="discussion",
                            title=post_data.get("title", ""),
                            url=f"https://reddit.com{post_data.get('permalink', '')}",
                            score=min(score / 1000, 1.0),
                            metadata={
                                "subreddit": subreddit,
                                "upvotes": score,
                                "comments": post_data.get("num_comments", 0),
                                "is_self": post_data.get("is_self", False),
                            }
                        ))
            except Exception as e:
                logger.warning("Reddit scan failed [%s]: %s", subreddit, e)

        return signals

    # ═══════════════════════════════════════════════════════════════════════
    # 6. GA4 — Internal Analytics (Placeholder)
    # ═══════════════════════════════════════════════════════════════════════

    async def scan_ga4(self) -> List[ContentSignal]:
        """GA4에서 트래픽 기회 스캔 (향후 구현)"""
        signals = []

        # GA4 API 연동은 별도 인증 필요
        # 현재는 SSOT의 기존 데이터 활용
        try:
            # 최근 검색 쿼리에서 기회 발견
            rows = self.ssot.conn.execute("""
                SELECT data FROM signals
                WHERE kind='search_query'
                AND created_at > datetime('now', '-7 days')
                LIMIT 20
            """).fetchall()

            for row in rows:
                try:
                    data = json.loads(row[0])
                    query = data.get("query", "")
                    impressions = data.get("impressions", 0)
                    clicks = data.get("clicks", 0)

                    # 노출은 많은데 클릭이 적은 = 개선 기회
                    if impressions > 100 and clicks / max(impressions, 1) < 0.02:
                        signals.append(ContentSignal(
                            source="ga4",
                            signal_type="opportunity",
                            title=f"Low CTR: {query}",
                            score=min(impressions / 1000, 1.0),
                            metadata={
                                "query": query,
                                "impressions": impressions,
                                "clicks": clicks,
                                "ctr": clicks / max(impressions, 1),
                            }
                        ))
                except:
                    continue
        except Exception as e:
            logger.warning("GA4 scan failed: %s", e)

        return signals

    # ═══════════════════════════════════════════════════════════════════════
    # 전체 스캔
    # ═══════════════════════════════════════════════════════════════════════

    async def full_scan(self) -> Dict[str, List[ContentSignal]]:
        """모든 소스 스캔"""
        import time
        start = time.time()

        results = {
            "tavily": [],
            "producthunt": [],
            "hackernews": [],
            "github": [],
            "reddit": [],
            "ga4": [],
        }

        # 병렬 실행
        tasks = [
            ("tavily", self.scan_tavily()),
            ("producthunt", self.scan_producthunt()),
            ("hackernews", self.scan_hackernews()),
            ("github", self.scan_github()),
            ("reddit", self.scan_reddit()),
            ("ga4", self.scan_ga4()),
        ]

        for source, coro in tasks:
            try:
                signals = await coro
                results[source] = signals
                logger.info("AccretionDisk: %s returned %d signals", source, len(signals))
            except Exception as e:
                logger.error("AccretionDisk: %s failed: %s", source, e)

        # 결과 저장
        total_signals = sum(len(s) for s in results.values())
        self._save_scan_results(results, time.time() - start)

        logger.info("AccretionDisk: Full scan complete. %d signals in %.1fs",
                   total_signals, time.time() - start)

        return results

    def _save_scan_results(self, results: Dict[str, List[ContentSignal]], duration: float):
        """스캔 결과를 territory_scan 테이블에 저장"""
        try:
            for source, signals in results.items():
                interesting = [s for s in signals if s.score >= 0.5]
                self.ssot.conn.execute(
                    """INSERT INTO territory_scan
                       (source, scan_type, results_count, interesting_count,
                        scan_duration_ms, success, data)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        source,
                        "full_scan",
                        len(signals),
                        len(interesting),
                        int(duration * 1000 / max(len(results), 1)),
                        1 if signals else 0,
                        json.dumps([{
                            "title": s.title,
                            "url": s.url,
                            "score": s.score,
                            "type": s.signal_type,
                        } for s in signals[:5]])
                    )
                )
            self.ssot.conn.commit()
        except Exception as e:
            logger.error("Failed to save scan results: %s", e)

    # ═══════════════════════════════════════════════════════════════════════
    # 콘텐츠 기회 추출
    # ═══════════════════════════════════════════════════════════════════════

    def extract_opportunities(self, signals: Dict[str, List[ContentSignal]],
                            min_score: float = 0.5) -> List[ContentSignal]:
        """스캔 결과에서 블로그 기회 추출"""
        opportunities = []

        for source, source_signals in signals.items():
            for signal in source_signals:
                if signal.score >= min_score:
                    opportunities.append(signal)

        # 점수순 정렬
        opportunities.sort(key=lambda x: x.score, reverse=True)

        return opportunities[:10]  # 상위 10개만
