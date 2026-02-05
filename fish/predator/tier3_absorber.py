"""
TIER 3: 월간 흡수 모듈 4개
매월 1일 실행. Tavily 기반 심층 리서치.

1. ConferenceHarvester — AI 컨퍼런스 발표/논문
2. PostmortemCollector — AI 프로젝트 실패 사례
3. OpenDataHarvester  — 새 데이터셋/벤치마크
4. EcosystemMap        — AI 에이전트 생태계 전체 스캔
"""

import json
import hashlib
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Dict, Any, List
from .tavily_util import get_tavily_pool

logger = logging.getLogger("predator.tier3")


class BaseTier3Module:
    """TIER 3 공통 베이스."""

    MODULE_NAME = "base"
    CATEGORY = "general"
    QUERIES = []
    MAX_PER_QUERY = 5  # 월간이라 더 깊게

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
        """심층 스캔."""
        all_items = []
        errors = []

        for query in self.QUERIES:
            try:
                # 월간은 advanced depth
                results = await self.tavily.search(
                    query=query,
                    max_results=self.MAX_PER_QUERY,
                    search_depth="advanced"
                )
                for r in results:
                    item = {
                        "source_module": f"tier3_{self.MODULE_NAME}",
                        "category": self.CATEGORY,
                        "title": r.get("title", ""),
                        "summary": r.get("content", "")[:800],
                        "url": r.get("url", ""),
                        "tags": [self.CATEGORY, self.MODULE_NAME, "tier3"],
                        "relevance_score": min(r.get("score", 0.5), 1.0),
                        "confidence": 0.7,
                        "query": query
                    }
                    all_items.append(item)
            except Exception as e:
                errors.append({"query": query, "error": str(e)})

        stored = self._store(all_items)

        result = {
            "module": self.MODULE_NAME,
            "raw": len(all_items),
            "stored": stored,
            "errors": len(errors),
            "scanned_at": datetime.now(timezone.utc).isoformat()
        }
        logger.info(f"[TIER3:{self.MODULE_NAME}] {result['raw']} found -> {stored} stored")
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
                absorb_id = f"t3_{self.MODULE_NAME}_{url_hash}"
                source_id = f"tier3_{self.MODULE_NAME}"
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
                        item.get("summary", "")[:800],
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


class ConferenceHarvester(BaseTier3Module):
    """AI 컨퍼런스 발표/논문 수확."""
    MODULE_NAME = "conference"
    CATEGORY = "paper"
    QUERIES = [
        "NeurIPS 2025 2026 AI agent paper highlights",
        "ICML 2025 2026 autonomous agent best paper",
        "ICLR 2025 2026 LLM agent research",
        "ACL 2025 2026 language model agent",
        "AI agent conference talk keynote 2025 2026"
    ]


class PostmortemCollector(BaseTier3Module):
    """AI 프로젝트 실패 사례 수집."""
    MODULE_NAME = "postmortem"
    CATEGORY = "survival"
    QUERIES = [
        "AI agent project failed postmortem lessons",
        "autonomous agent shutdown why discontinued",
        "AI startup failed lessons learned 2024 2025",
        "LLM agent production failure case study"
    ]


class OpenDataHarvester(BaseTier3Module):
    """새 데이터셋/벤치마크 수확."""
    MODULE_NAME = "opendata"
    CATEGORY = "tool"
    QUERIES = [
        "new AI agent benchmark dataset 2025 2026",
        "SWE-bench WebArena GAIA update latest",
        "AI agent evaluation benchmark new",
        "autonomous agent testing framework open source"
    ]


class EcosystemMap(BaseTier3Module):
    """AI 에이전트 생태계 전체 스캔."""
    MODULE_NAME = "ecosystem"
    CATEGORY = "evolution"
    QUERIES = [
        "AI agent ecosystem map 2025 2026 landscape",
        "autonomous agent framework comparison latest",
        "AI agent market size growth forecast",
        "LLM agent platform overview comprehensive",
        "multi-agent system production real world deployment",
        "AI agent infrastructure tools emerging"
    ]


class Tier3Absorber:
    """TIER 3 전체 통합 실행."""

    MODULES = [
        ConferenceHarvester,
        PostmortemCollector,
        OpenDataHarvester,
        EcosystemMap,
    ]

    def __init__(self, db_path: str = None):
        self.db_path = db_path

    async def monthly_absorb(self) -> Dict[str, Any]:
        """월간 흡수 전체 실행."""
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
                logger.error(f"TIER3 {ModuleClass.MODULE_NAME} error: {e}")
                results[ModuleClass.MODULE_NAME] = {"error": str(e)}
                total_errors += 1

        summary = {
            "tier": 3,
            "modules": len(self.MODULES),
            "total_stored": total_stored,
            "total_errors": total_errors,
            "details": results,
            "absorbed_at": datetime.now(timezone.utc).isoformat()
        }
        logger.info(f"[TIER3] Monthly: {total_stored} items from {len(self.MODULES)} modules")
        return summary
