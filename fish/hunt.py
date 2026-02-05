"""
EVENT HORIZON v3.0 — Hunt System
5가지 사냥 전략 + Accretion Disk (6 Sources)
"""

import asyncio
import logging
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from enum import Enum

logger = logging.getLogger("reze.fish.hunt")


class HuntStrategy(Enum):
    """5가지 사냥 전략"""
    H1_TRENDING_NEWS = "trending_news"      # 트렌딩 뉴스 포착
    H2_TOOL_DISCOVERY = "tool_discovery"    # 새 도구 발견
    H3_COMPETITOR_GAP = "competitor_gap"    # 경쟁자 갭 분석
    H4_AFFILIATE = "affiliate"              # 어필리에이트 기회
    H5_EVERGREEN = "evergreen"              # 에버그린 예측


class Source(Enum):
    """6개 Accretion Disk 소스"""
    TAVILY = "tavily"
    PRODUCTHUNT = "producthunt"
    HACKERNEWS = "hackernews"
    GITHUB = "github"
    REDDIT = "reddit"
    GA4 = "ga4"


@dataclass
class Prey:
    """사냥감 (발견된 콘텐츠 기회)"""
    strategy: HuntStrategy
    source: Source
    target: str                 # URL, 키워드, 툴명 등
    title: str
    score: float = 0.0          # 0.0-1.0 사냥 가치
    urgency: str = "low"        # low, medium, high, critical
    metadata: dict = field(default_factory=dict)
    discovered_at: datetime = field(default_factory=datetime.now)


@dataclass
class HuntResult:
    """사냥 결과"""
    success: bool
    prey: Optional[Prey] = None
    strategy: HuntStrategy = None
    source: Source = None
    tokens_used: int = 0
    duration_ms: int = 0
    error: str = ""


class Hunter:
    """
    EVENT HORIZON 사냥 시스템.
    물고기가 먹이를 찾는 5가지 전략을 구현.
    """

    # 전략별 소스 매핑
    STRATEGY_SOURCES = {
        HuntStrategy.H1_TRENDING_NEWS: [Source.TAVILY, Source.HACKERNEWS, Source.REDDIT],
        HuntStrategy.H2_TOOL_DISCOVERY: [Source.PRODUCTHUNT, Source.GITHUB, Source.HACKERNEWS],
        HuntStrategy.H3_COMPETITOR_GAP: [Source.TAVILY, Source.GA4],
        HuntStrategy.H4_AFFILIATE: [Source.TAVILY, Source.PRODUCTHUNT],
        HuntStrategy.H5_EVERGREEN: [Source.GA4, Source.TAVILY],
    }

    # 전략별 최소 휴식 시간 (시간)
    STRATEGY_COOLDOWN = {
        HuntStrategy.H1_TRENDING_NEWS: 2,      # 2시간마다 트렌드 체크
        HuntStrategy.H2_TOOL_DISCOVERY: 6,     # 6시간마다 새 도구 탐색
        HuntStrategy.H3_COMPETITOR_GAP: 24,    # 하루에 한 번
        HuntStrategy.H4_AFFILIATE: 12,         # 12시간마다
        HuntStrategy.H5_EVERGREEN: 48,         # 이틀에 한 번
    }

    def __init__(self, ssot, router, config: dict = None):
        """
        ssot: SSOT 인스턴스
        router: ModelRouter (C3PO)
        config: 추가 설정 (API 키 등)
        """
        self.ssot = ssot
        self.router = router
        self.config = config or {}

        # API 키
        self._tavily_key = None
        self._load_api_keys()

    def _load_api_keys(self):
        """API 키 로드"""
        try:
            import config as app_config
            self._tavily_key = app_config.get_tavily_key()
        except Exception as e:
            logger.warning("Hunt: Failed to load API keys: %s", e)

    # ═══════════════════════════════════════════════════════════════════════
    # 사냥 가능 여부 판단
    # ═══════════════════════════════════════════════════════════════════════

    def can_hunt(self, strategy: HuntStrategy = None) -> tuple[bool, Optional[HuntStrategy]]:
        """
        사냥 가능 여부 및 최적 전략 반환.

        Returns:
            (can_hunt: bool, best_strategy: HuntStrategy or None)
        """
        if strategy:
            # 특정 전략 체크
            if self._check_cooldown(strategy):
                return True, strategy
            return False, None

        # 전략 우선순위: H1 > H2 > H4 > H3 > H5
        priority_order = [
            HuntStrategy.H1_TRENDING_NEWS,
            HuntStrategy.H2_TOOL_DISCOVERY,
            HuntStrategy.H4_AFFILIATE,
            HuntStrategy.H3_COMPETITOR_GAP,
            HuntStrategy.H5_EVERGREEN,
        ]

        for strat in priority_order:
            if self._check_cooldown(strat):
                return True, strat

        return False, None

    def _check_cooldown(self, strategy: HuntStrategy) -> bool:
        """쿨다운 체크 — 최근 사냥 이후 충분한 시간이 지났는지"""
        cooldown_hours = self.STRATEGY_COOLDOWN.get(strategy, 6)

        try:
            row = self.ssot.conn.execute(
                """SELECT MAX(created_at) FROM hunt_memory
                   WHERE strategy=? AND success=1""",
                (strategy.value,)
            ).fetchone()

            if row and row[0]:
                last_hunt = datetime.fromisoformat(row[0].replace("Z", "+00:00"))
                elapsed = (datetime.now() - last_hunt.replace(tzinfo=None)).total_seconds() / 3600
                return elapsed >= cooldown_hours

            return True  # 기록 없으면 사냥 가능
        except:
            return True

    def get_hunt_stats(self) -> dict:
        """사냥 통계"""
        try:
            stats = {}
            for strategy in HuntStrategy:
                row = self.ssot.conn.execute(
                    """SELECT COUNT(*) as total,
                              SUM(CASE WHEN success=1 THEN 1 ELSE 0 END) as success,
                              AVG(score) as avg_score
                       FROM hunt_memory WHERE strategy=?""",
                    (strategy.value,)
                ).fetchone()

                stats[strategy.value] = {
                    "total": row[0] or 0,
                    "success": row[1] or 0,
                    "success_rate": (row[1] or 0) / max(row[0] or 1, 1),
                    "avg_score": round(row[2] or 0, 3),
                }
            return stats
        except:
            return {}

    # ═══════════════════════════════════════════════════════════════════════
    # 사냥 실행
    # ═══════════════════════════════════════════════════════════════════════

    async def hunt(self, strategy: HuntStrategy = None) -> HuntResult:
        """
        사냥 실행. 전략이 지정되지 않으면 자동 선택.
        """
        import time
        start = time.time()

        # 전략 선택
        if not strategy:
            can, strategy = self.can_hunt()
            if not can:
                return HuntResult(success=False, error="No hunt available (cooldown)")

        logger.info("Hunt: Starting %s", strategy.value)

        try:
            # 전략별 사냥 실행
            if strategy == HuntStrategy.H1_TRENDING_NEWS:
                result = await self._hunt_trending_news()
            elif strategy == HuntStrategy.H2_TOOL_DISCOVERY:
                result = await self._hunt_tool_discovery()
            elif strategy == HuntStrategy.H3_COMPETITOR_GAP:
                result = await self._hunt_competitor_gap()
            elif strategy == HuntStrategy.H4_AFFILIATE:
                result = await self._hunt_affiliate()
            elif strategy == HuntStrategy.H5_EVERGREEN:
                result = await self._hunt_evergreen()
            else:
                result = HuntResult(success=False, error=f"Unknown strategy: {strategy}")

            result.strategy = strategy
            result.duration_ms = int((time.time() - start) * 1000)

            # 사냥 기록 저장
            if result.success and result.prey:
                self._save_hunt_memory(result)

            return result

        except Exception as e:
            logger.error("Hunt failed [%s]: %s", strategy.value, e, exc_info=True)
            return HuntResult(
                success=False,
                strategy=strategy,
                error=str(e),
                duration_ms=int((time.time() - start) * 1000)
            )

    def _save_hunt_memory(self, result: HuntResult):
        """사냥 기억 저장"""
        try:
            self.ssot.conn.execute(
                """INSERT INTO hunt_memory
                   (strategy, source, query, target, success, score, tokens_used, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    result.strategy.value if result.strategy else "",
                    result.source.value if result.source else "",
                    result.prey.metadata.get("query", "") if result.prey else "",
                    result.prey.target if result.prey else "",
                    1 if result.success else 0,
                    result.prey.score if result.prey else 0,
                    result.tokens_used,
                    json.dumps(result.prey.metadata if result.prey else {})
                )
            )
            self.ssot.conn.commit()
        except Exception as e:
            logger.error("Failed to save hunt memory: %s", e)

    # ═══════════════════════════════════════════════════════════════════════
    # H1: Trending News (트렌딩 뉴스 포착)
    # ═══════════════════════════════════════════════════════════════════════

    async def _hunt_trending_news(self) -> HuntResult:
        """AI/Tech 트렌딩 뉴스 검색"""
        queries = [
            "AI tool launch today",
            "new AI startup announcement",
            "ChatGPT update news",
            "AI productivity tool release",
        ]

        for query in queries:
            prey = await self._search_tavily(query, HuntStrategy.H1_TRENDING_NEWS)
            if prey and prey.score >= 0.5:
                return HuntResult(
                    success=True,
                    prey=prey,
                    source=Source.TAVILY,
                )

        return HuntResult(success=False, error="No trending news found")

    # ═══════════════════════════════════════════════════════════════════════
    # H2: Tool Discovery (새 도구 발견)
    # ═══════════════════════════════════════════════════════════════════════

    async def _hunt_tool_discovery(self) -> HuntResult:
        """ProductHunt, GitHub에서 새 AI 도구 발견"""
        # ProductHunt 스크래핑 (간단 버전)
        prey = await self._scan_producthunt()
        if prey and prey.score >= 0.5:
            return HuntResult(success=True, prey=prey, source=Source.PRODUCTHUNT)

        # GitHub Trending
        prey = await self._scan_github_trending()
        if prey and prey.score >= 0.5:
            return HuntResult(success=True, prey=prey, source=Source.GITHUB)

        return HuntResult(success=False, error="No new tools found")

    async def _scan_producthunt(self) -> Optional[Prey]:
        """ProductHunt AI 카테고리 스캔"""
        try:
            import subprocess
            result = subprocess.run(
                ["curl", "-s", "https://www.producthunt.com/topics/artificial-intelligence"],
                capture_output=True, text=True, timeout=10
            )
            # 간단한 파싱 (실제로는 더 정교한 파싱 필요)
            if "AI" in result.stdout:
                return Prey(
                    strategy=HuntStrategy.H2_TOOL_DISCOVERY,
                    source=Source.PRODUCTHUNT,
                    target="https://www.producthunt.com/topics/artificial-intelligence",
                    title="ProductHunt AI Tools",
                    score=0.3,
                    metadata={"scan_type": "category"}
                )
        except Exception as e:
            logger.warning("ProductHunt scan failed: %s", e)
        return None

    async def _scan_github_trending(self) -> Optional[Prey]:
        """GitHub Trending AI 레포 스캔"""
        try:
            import subprocess
            result = subprocess.run(
                ["curl", "-s", "https://api.github.com/search/repositories?q=AI+created:>2024-01-01&sort=stars&order=desc&per_page=5"],
                capture_output=True, text=True, timeout=10
            )
            data = json.loads(result.stdout)
            if data.get("items"):
                top = data["items"][0]
                return Prey(
                    strategy=HuntStrategy.H2_TOOL_DISCOVERY,
                    source=Source.GITHUB,
                    target=top.get("html_url", ""),
                    title=top.get("full_name", ""),
                    score=min(top.get("stargazers_count", 0) / 10000, 1.0),
                    metadata={"stars": top.get("stargazers_count", 0)}
                )
        except Exception as e:
            logger.warning("GitHub trending scan failed: %s", e)
        return None

    # ═══════════════════════════════════════════════════════════════════════
    # H3: Competitor Gap (경쟁자 갭 분석)
    # ═══════════════════════════════════════════════════════════════════════

    async def _hunt_competitor_gap(self) -> HuntResult:
        """경쟁자 블로그에서 우리가 없는 주제 발견"""
        competitors = [
            "futuretools.io",
            "theresanaiforthat.com",
            "toolify.ai",
        ]

        for competitor in competitors:
            query = f"site:{competitor} AI tools 2025"
            prey = await self._search_tavily(query, HuntStrategy.H3_COMPETITOR_GAP)
            if prey and prey.score >= 0.4:
                return HuntResult(success=True, prey=prey, source=Source.TAVILY)

        return HuntResult(success=False, error="No competitor gaps found")

    # ═══════════════════════════════════════════════════════════════════════
    # H4: Affiliate Opportunity (어필리에이트 기회)
    # ═══════════════════════════════════════════════════════════════════════

    async def _hunt_affiliate(self) -> HuntResult:
        """높은 커미션 어필리에이트 프로그램 발견"""
        queries = [
            "AI tool affiliate program launch",
            "SaaS affiliate high commission",
            "AI software partner program",
        ]

        for query in queries:
            prey = await self._search_tavily(query, HuntStrategy.H4_AFFILIATE)
            if prey and prey.score >= 0.5:
                return HuntResult(success=True, prey=prey, source=Source.TAVILY)

        return HuntResult(success=False, error="No affiliate opportunities found")

    # ═══════════════════════════════════════════════════════════════════════
    # H5: Evergreen Prediction (에버그린 예측)
    # ═══════════════════════════════════════════════════════════════════════

    async def _hunt_evergreen(self) -> HuntResult:
        """장기적으로 트래픽을 유지할 에버그린 주제 발견"""
        # GA4 데이터 기반 + 키워드 트렌드 분석
        queries = [
            "best AI tools for",
            "how to use AI for",
            "AI alternatives to",
        ]

        for query in queries:
            prey = await self._search_tavily(query, HuntStrategy.H5_EVERGREEN)
            if prey and prey.score >= 0.4:
                return HuntResult(success=True, prey=prey, source=Source.TAVILY)

        return HuntResult(success=False, error="No evergreen topics found")

    # ═══════════════════════════════════════════════════════════════════════
    # Tavily Search (공통)
    # ═══════════════════════════════════════════════════════════════════════

    async def _search_tavily(self, query: str, strategy: HuntStrategy) -> Optional[Prey]:
        """Tavily API로 검색"""
        if not self._tavily_key:
            logger.warning("Tavily API key not available")
            return None

        try:
            import subprocess
            import urllib.parse

            encoded_query = urllib.parse.quote(query)
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
            results = data.get("results", [])

            if results:
                top = results[0]
                # 점수 계산: relevance + 최신성
                score = min(top.get("score", 0.5), 1.0)

                return Prey(
                    strategy=strategy,
                    source=Source.TAVILY,
                    target=top.get("url", ""),
                    title=top.get("title", ""),
                    score=score,
                    metadata={
                        "query": query,
                        "snippet": top.get("content", "")[:200],
                        "results_count": len(results)
                    }
                )
        except Exception as e:
            logger.warning("Tavily search failed [%s]: %s", query, e)

        return None

    # ═══════════════════════════════════════════════════════════════════════
    # Territory Scan (영역 스캔)
    # ═══════════════════════════════════════════════════════════════════════

    async def scan_territory(self, source: Source) -> dict:
        """특정 소스 영역 스캔"""
        import time
        start = time.time()

        result = {
            "source": source.value,
            "success": False,
            "results_count": 0,
            "interesting": [],
            "duration_ms": 0
        }

        try:
            if source == Source.TAVILY:
                prey = await self._search_tavily("AI tools news today", HuntStrategy.H1_TRENDING_NEWS)
                if prey:
                    result["success"] = True
                    result["results_count"] = prey.metadata.get("results_count", 0)
                    result["interesting"].append(prey.title)

            elif source == Source.PRODUCTHUNT:
                prey = await self._scan_producthunt()
                if prey:
                    result["success"] = True
                    result["results_count"] = 1

            elif source == Source.GITHUB:
                prey = await self._scan_github_trending()
                if prey:
                    result["success"] = True
                    result["results_count"] = 1
                    result["interesting"].append(prey.title)

            # 영역 스캔 기록
            self._save_territory_scan(
                source=source.value,
                scan_type="monitor",
                results_count=result["results_count"],
                interesting_count=len(result["interesting"]),
                duration_ms=int((time.time() - start) * 1000),
                success=result["success"],
                data=result
            )

        except Exception as e:
            logger.error("Territory scan failed [%s]: %s", source.value, e)
            result["error"] = str(e)

        result["duration_ms"] = int((time.time() - start) * 1000)
        return result

    def _save_territory_scan(self, **kwargs):
        """영역 스캔 기록 저장"""
        try:
            self.ssot.conn.execute(
                """INSERT INTO territory_scan
                   (source, scan_type, query, results_count, interesting_count,
                    scan_duration_ms, success, data)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    kwargs.get("source", ""),
                    kwargs.get("scan_type", ""),
                    kwargs.get("query", ""),
                    kwargs.get("results_count", 0),
                    kwargs.get("interesting_count", 0),
                    kwargs.get("duration_ms", 0),
                    1 if kwargs.get("success") else 0,
                    json.dumps(kwargs.get("data", {}))
                )
            )
            self.ssot.conn.commit()
        except Exception as e:
            logger.error("Failed to save territory scan: %s", e)
