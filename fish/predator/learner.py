"""
Phase 5 Wave 2: PREDATOR Experience Learner
REZE v6.0 SOVEREIGN - Stage 3: 학습 (Learn)

소화된 경험들에서 패턴을 발견하고 실행 가능한 전략을 생성한다.
"""

import json
import hashlib
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger("reze.predator.learner")


@dataclass
class LearnResult:
    """학습 결과."""
    categories_processed: int = 0
    strategies_generated: int = 0
    strategies_updated: int = 0
    skipped_categories: int = 0
    duration_sec: float = 0.0
    strategies: List[str] = field(default_factory=list)


PATTERN_DISCOVERY_PROMPT = """너는 REZE라는 자율형 AI 에이전트의 학습 시스템이다.
같은 카테고리의 소화된 경험들에서 실행 가능한 전략을 발견하라.

카테고리: {category}
경험 수: {count}건

각 경험의 핵심 인사이트:
{insights}

이미 등록된 전략:
{existing_strategies}

요구사항:
1. 여러 경험에서 반복되는 패턴을 찾아라
2. 그 패턴을 실행 가능한 전략으로 만들어라
3. 이미 있는 전략과 중복이면 "pattern_found": false
4. 전략은 REZE가 자동으로 실행할 수 있어야 함

반드시 JSON만 응답:
{{
  "pattern_found": true,
  "pattern_description": "발견한 패턴 (50자)",
  "strategy": {{
    "name": "전략 이름 (20자 이내)",
    "category": "{category}",
    "description": "전략 설명 (100자)",
    "action_type": "prompt_update|strategy_change|tool_add|config_update|watch_add|none",
    "action_template": {{
      "target": "수정 대상",
      "change": "구체적 변경 내용",
      "rollback": "실패 시 원복 방법"
    }},
    "confidence": 0.7,
    "conditions": "적용 조건",
    "expected_impact": "예상 효과"
  }}
}}

패턴 없으면:
{{"pattern_found": false, "reason": "이유"}}"""


class ExperienceLearner:
    """소화된 경험들에서 패턴을 발견하고 전략을 생성."""

    MIN_DIGESTED_FOR_LEARNING = 5
    MIN_PER_CATEGORY = 2

    def __init__(self, db_path: str = None, llm_router=None):
        self.db_path = db_path or str(
            Path.home() / "reze-agent" / "reze_data" / "ssot.sqlite"
        )
        self.llm_router = llm_router

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    async def learn(self) -> LearnResult:
        """소화된 경험들에서 학습."""
        import time
        start = time.time()
        conn = self._get_conn()

        try:
            # 고득점 인사이트 조회 (learn_status='pending')
            digested = conn.execute("""
                SELECT insight_id, insight_type, summary, key_points,
                       combined_score, domains, source_id
                FROM digested_insights
                WHERE combined_score >= 0.5
                  AND learn_status = 'pending'
                ORDER BY combined_score DESC
                LIMIT 100
            """).fetchall()

            if len(digested) < self.MIN_DIGESTED_FOR_LEARNING:
                return LearnResult(
                    duration_sec=time.time() - start,
                    strategies=[f"소화 {len(digested)}건, 최소 {self.MIN_DIGESTED_FOR_LEARNING}건 필요"]
                )

            # insight_type별 그룹화
            by_category = {}
            for exp in digested:
                cat = exp["insight_type"] or "general"
                if cat not in by_category:
                    by_category[cat] = []
                by_category[cat].append(dict(exp))

            result = LearnResult()
            result.categories_processed = len(by_category)

            for category, exps in by_category.items():
                if len(exps) < self.MIN_PER_CATEGORY:
                    result.skipped_categories += 1
                    continue

                strategy = await self._find_pattern(conn, category, exps)

                if strategy and strategy.get("pattern_found"):
                    strat = strategy.get("strategy", {})
                    if strat:
                        registered = self._register_strategy(conn, strat, exps)
                        if registered == "new":
                            result.strategies_generated += 1
                        elif registered == "updated":
                            result.strategies_updated += 1
                        result.strategies.append(strat.get("name", "unknown"))

            conn.commit()
            result.duration_sec = time.time() - start

            logger.info(
                f"[Learn] {result.strategies_generated} new, "
                f"{result.strategies_updated} updated from {result.categories_processed} categories"
            )
            return result

        finally:
            conn.close()

    async def _find_pattern(self, conn, category: str, experiences: list) -> Optional[dict]:
        """같은 카테고리 경험들에서 패턴 발견."""
        insights = [exp.get("summary", "") for exp in experiences if exp.get("summary")]

        # 기존 전략 조회
        existing = conn.execute("""
            SELECT pattern_id, description, pattern_type
            FROM learned_patterns
            WHERE pattern_type = ?
        """, (category,)).fetchall()

        existing_str = json.dumps([dict(e) for e in existing], ensure_ascii=False) if existing else "없음"

        prompt = PATTERN_DISCOVERY_PROMPT.format(
            category=category,
            count=len(experiences),
            insights="\n".join(f"- {i[:200]}" for i in insights[:20]),
            existing_strategies=existing_str
        )

        try:
            response = await self._call_llm(prompt)
            return self._parse_json(response)
        except Exception as e:
            logger.warning(f"Pattern discovery failed for {category}: {e}")
            return None

    def _register_strategy(self, conn, strategy: dict, source_exps: list) -> str:
        """전략을 learned_patterns 테이블에 등록."""
        now = datetime.now(timezone.utc).isoformat()
        name = strategy.get("name", "unnamed")
        pattern_id = f"pat_{hashlib.md5(name.encode()).hexdigest()[:12]}"

        # insight_ids 수집
        insight_ids = [e.get("insight_id", "") for e in source_exps]

        # 이미 존재하는지 확인
        existing = conn.execute(
            "SELECT id FROM learned_patterns WHERE pattern_id = ?",
            (pattern_id,)
        ).fetchone()

        pattern_data = json.dumps({
            "action_type": strategy.get("action_type", "none"),
            "action_template": strategy.get("action_template", {}),
            "conditions": strategy.get("conditions", ""),
            "expected_impact": strategy.get("expected_impact", "")
        }, ensure_ascii=False)

        if existing:
            conn.execute("""
                UPDATE learned_patterns SET
                    examples_count = examples_count + ?,
                    confidence = MAX(confidence, ?),
                    last_reinforced_at = ?
                WHERE pattern_id = ?
            """, (
                len(source_exps),
                strategy.get("confidence", 0.5),
                now,
                pattern_id
            ))
            return "updated"
        else:
            conn.execute("""
                INSERT INTO learned_patterns
                (pattern_id, insight_ids, pattern_type, description,
                 pattern_data, confidence, examples_count, apply_status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)
            """, (
                pattern_id,
                json.dumps(insight_ids),
                strategy.get("category", "general"),
                strategy.get("description", ""),
                pattern_data,
                strategy.get("confidence", 0.5),
                len(source_exps),
                now
            ))

            # 소스 인사이트들의 learn_status 업데이트
            for iid in insight_ids:
                if iid:
                    conn.execute("""
                        UPDATE digested_insights
                        SET learn_status = 'learned'
                        WHERE insight_id = ?
                    """, (iid,))

            return "new"

    async def _call_llm(self, prompt: str) -> str:
        """LLM 호출."""
        if self.llm_router:
            try:
                result = await self.llm_router.call("learn", prompt, temperature=0.3)
                return result.get("content", "")
            except Exception as e:
                logger.warning(f"Router error: {e}")

        # Fallback: Cerebras
        import os
        cerebras_key = os.environ.get("CEREBRAS_API_KEY")
        if cerebras_key:
            try:
                from cerebras.cloud.sdk import Cerebras
                client = Cerebras(api_key=cerebras_key)
                resp = client.chat.completions.create(
                    model="llama-3.3-70b",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=800,
                    temperature=0.3
                )
                return resp.choices[0].message.content
            except Exception as e:
                logger.warning(f"Cerebras error: {e}")

        raise RuntimeError("No LLM available")

    def _parse_json(self, text: str) -> Optional[dict]:
        """JSON 파싱."""
        if not text:
            return None
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    return json.loads(text[start:end])
                except:
                    pass
        return None

    async def learn_batch(self, max_categories: int = 10) -> Dict[str, Any]:
        """배치 학습 (편의 메서드)."""
        result = await self.learn()
        return {
            "categories": result.categories_processed,
            "new_strategies": result.strategies_generated,
            "updated_strategies": result.strategies_updated,
            "skipped": result.skipped_categories,
            "strategy_names": result.strategies,
            "duration_sec": result.duration_sec
        }

    def get_pending_patterns(self, limit: int = 20) -> List[Dict[str, Any]]:
        """적용 대기 중인 패턴."""
        conn = self._get_conn()
        cursor = conn.execute("""
            SELECT pattern_id, pattern_type, description, pattern_data,
                   confidence, examples_count, created_at
            FROM learned_patterns
            WHERE apply_status = 'pending'
            ORDER BY confidence DESC
            LIMIT ?
        """, (limit,))
        patterns = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return patterns

    def get_stats(self) -> Dict[str, Any]:
        """학습 통계."""
        conn = self._get_conn()

        stats = conn.execute("""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN apply_status = 'pending' THEN 1 ELSE 0 END) as pending,
                   SUM(CASE WHEN apply_status = 'applied' THEN 1 ELSE 0 END) as applied,
                   AVG(confidence) as avg_confidence
            FROM learned_patterns
        """).fetchone()

        by_type = conn.execute("""
            SELECT pattern_type, COUNT(*) as count
            FROM learned_patterns
            GROUP BY pattern_type
        """).fetchall()

        conn.close()

        return {
            "total_patterns": stats["total"] or 0,
            "pending": stats["pending"] or 0,
            "applied": stats["applied"] or 0,
            "avg_confidence": round(stats["avg_confidence"] or 0, 3),
            "by_type": {row["pattern_type"]: row["count"] for row in by_type}
        }
