"""
TIER 2: 주간 흡수 모듈 6개
매주 월요일 실행. Tavily 기반.

1. PatentScanner    — AI 에이전트 관련 특허
2. FundingRadar     — AI 스타트업 펀딩 뉴스
3. JobSignal        — AI 에이전트 채용 트렌드
4. RegulationWatch  — AI 규제/정책 변화
5. CompetitionWatch — 경쟁 에이전트 프로젝트 동향
6. TechStackTrend   — 인기 기술 스택 변화
"""

import json
import hashlib
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Dict, Any, List
from .tavily_util import get_tavily_pool

logger = logging.getLogger("predator.tier2")


class BaseTier2Module:
    """TIER 2 공통 베이스."""

    MODULE_NAME = "base"
    CATEGORY = "general"
    QUERIES = []  # 서브클래스에서 정의
    MAX_PER_QUERY = 3

    def __init__(self, db_path: str = None):
        self.db_path = db_path or self._find_db()
        self.tavily = get_tavily_pool()

    def _find_db(self) -> str:
        import os
        for p in [
            os.path.expanduser("~/reze-agent/reze_data/ssot.sqlite"),
            os.path.expanduser("~/reze-agent/fish/predator/predator.db"),
        ]:
            if os.path.exists(p):
                return p
        return os.path.expanduser("~/reze-agent/reze_data/ssot.sqlite")

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    async def scan(self) -> Dict[str, Any]:
        """스캔 실행."""
        all_items = []
        errors = []

        for query in self.QUERIES:
            try:
                results = await self.tavily.search(
                    query=query,
                    max_results=self.MAX_PER_QUERY,
                    search_depth="basic"
                )
                for r in results:
                    item = {
                        "source_module": f"tier2_{self.MODULE_NAME}",
                        "category": self.CATEGORY,
                        "title": r.get("title", ""),
                        "summary": r.get("content", "")[:500],
                        "url": r.get("url", ""),
                        "tags": [self.CATEGORY, self.MODULE_NAME, "tier2"],
                        "relevance_score": min(r.get("score", 0.5), 1.0),
                        "confidence": 0.6,
                        "query": query
                    }
                    all_items.append(item)
            except Exception as e:
                errors.append({"query": query, "error": str(e)})

        # 중복 제거 + 저장
        stored = self._store(all_items)

        result = {
            "module": self.MODULE_NAME,
            "raw": len(all_items),
            "stored": stored,
            "errors": len(errors),
            "scanned_at": datetime.now(timezone.utc).isoformat()
        }
        logger.info(f"[TIER2:{self.MODULE_NAME}] {result['raw']} found -> {stored} stored")
        return result

    def _store(self, items: list) -> int:
        """absorbed_raw에 저장."""
        conn = self._get_conn()
        count = 0
        now = datetime.now(timezone.utc).isoformat()

        try:
            for item in items:
                url = item.get("url", "")
                if not url:
                    continue
                url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
                absorb_id = f"t2_{self.MODULE_NAME}_{url_hash}"
                source_id = f"tier2_{self.MODULE_NAME}"
                guid = url_hash

                existing = conn.execute(
                    "SELECT 1 FROM absorbed_raw WHERE absorb_id = ?", (absorb_id,)
                ).fetchone()
                if existing:
                    continue

                try:
                    conn.execute("""
                        INSERT INTO absorbed_raw
                        (absorb_id, source_id, guid, title, link, summary,
                         content, tags, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        absorb_id,
                        source_id,
                        guid,
                        item.get("title", "")[:200],
                        url,
                        item.get("summary", "")[:500],
                        json.dumps(item, ensure_ascii=False),
                        json.dumps(item.get("tags", [])),
                        now
                    ))
                    count += 1
                except Exception as e:
                    logger.debug(f"Store skip: {e}")

            conn.commit()
        finally:
            conn.close()

        return count


class PatentScanner(BaseTier2Module):
    """AI 에이전트 관련 특허 스캔."""
    MODULE_NAME = "patent"
    CATEGORY = "industry"
    QUERIES = [
        "AI agent patent 2025 2026 autonomous",
        "LLM agent system patent filed",
        "self-improving AI agent patent",
        "multi-agent collaboration patent"
    ]


class FundingRadar(BaseTier2Module):
    """AI 스타트업 펀딩 뉴스."""
    MODULE_NAME = "funding"
    CATEGORY = "industry"
    QUERIES = [
        "AI agent startup funding 2025 2026",
        "autonomous agent company raised series",
        "AI automation startup investment round",
        "LLM agent framework funding"
    ]


class JobSignal(BaseTier2Module):
    """AI 에이전트 채용 트렌드."""
    MODULE_NAME = "job"
    CATEGORY = "strategy"
    QUERIES = [
        "AI agent engineer hiring trend 2025 2026",
        "autonomous agent developer job market",
        "LLM agent skills demand",
        "AI automation job growth"
    ]


class RegulationWatch(BaseTier2Module):
    """AI 규제/정책 변화."""
    MODULE_NAME = "regulation"
    CATEGORY = "survival"
    QUERIES = [
        "AI regulation 2025 2026 new policy",
        "autonomous AI agent law regulation",
        "EU AI Act enforcement agent",
        "AI content regulation SEO impact"
    ]


class CompetitionWatch(BaseTier2Module):
    """경쟁 에이전트 프로젝트 동향."""
    MODULE_NAME = "competition"
    CATEGORY = "evolution"
    QUERIES = [
        "AutoGPT update 2025 2026 new features",
        "CrewAI vs LangGraph comparison latest",
        "autonomous AI agent project new release",
        "OpenAI agent framework latest",
        "Claude agent mode autonomous"
    ]


class TechStackTrend(BaseTier2Module):
    """인기 기술 스택 변화."""
    MODULE_NAME = "techstack"
    CATEGORY = "tool"
    QUERIES = [
        "AI agent tech stack 2025 2026 popular",
        "LLM framework trend FastAPI vs alternatives",
        "vector database comparison 2025 2026",
        "AI agent deployment best practices latest"
    ]


class Tier2Absorber:
    """TIER 2 전체 통합 실행."""

    MODULES = [
        PatentScanner,
        FundingRadar,
        JobSignal,
        RegulationWatch,
        CompetitionWatch,
        TechStackTrend,
    ]

    def __init__(self, db_path: str = None):
        self.db_path = db_path

    async def weekly_absorb(self) -> Dict[str, Any]:
        """주간 흡수 전체 실행."""
        results = {}
        total_stored = 0
        total_errors = 0

        for ModuleClass in self.MODULES:
            try:
                module = ModuleClass(self.db_path)
                result = await module.scan()
                results[result["module"]] = result
                total_stored += result.get("stored", 0)
                total_errors += result.get("errors", 0)
            except Exception as e:
                logger.error(f"TIER2 {ModuleClass.MODULE_NAME} error: {e}")
                results[ModuleClass.MODULE_NAME] = {"error": str(e)}
                total_errors += 1

        summary = {
            "tier": 2,
            "modules": len(self.MODULES),
            "total_stored": total_stored,
            "total_errors": total_errors,
            "details": results,
            "absorbed_at": datetime.now(timezone.utc).isoformat()
        }
        logger.info(f"[TIER2] Weekly: {total_stored} items from {len(self.MODULES)} modules")
        return summary
