"""
Phase 5 Wave 1: PREDATOR Experience Digester
REZE v6.0 SOVEREIGN - Stage 2: 소화 (Digest)

LLM을 사용하여 흡수된 콘텐츠에서 인사이트 추출

실행: python -m fish.predator.digester
"""

import asyncio
import sqlite3
import logging
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger("reze.predator.digester")


# ═══════════════════════════════════════════════════════════════
# 인사이트 유형
# ═══════════════════════════════════════════════════════════════

INSIGHT_TYPES = {
    "trend": "새로운 트렌드 또는 패턴",
    "technique": "실용적인 기술 또는 방법론",
    "tool": "유용한 도구 또는 라이브러리",
    "strategy": "비즈니스/마케팅 전략",
    "case_study": "성공/실패 사례",
    "insight": "일반적인 인사이트",
    "news": "중요 뉴스",
    "opinion": "주목할 의견"
}


@dataclass
class DigestResult:
    """단일 소화 결과"""
    absorb_id: str
    insight_id: Optional[str] = None
    insight_type: Optional[str] = None
    summary: Optional[str] = None
    relevance_score: float = 0.0
    actionability_score: float = 0.0
    novelty_score: float = 0.0
    combined_score: float = 0.0
    success: bool = False
    error: Optional[str] = None


@dataclass
class DigestCycleResult:
    """소화 사이클 결과"""
    cycle_id: str
    items_processed: int = 0
    items_digested: int = 0
    items_skipped: int = 0
    items_error: int = 0
    high_value_count: int = 0
    duration_sec: float = 0.0
    results: List[DigestResult] = field(default_factory=list)
    error: Optional[str] = None


class ExperienceDigester:
    """
    경험 소화 엔진

    흡수된 콘텐츠를 분석하여 인사이트 추출
    """

    def __init__(
        self,
        llm_router=None,
        db_path: str = None,
        min_relevance: float = 0.3,
        batch_size: int = 10
    ):
        """
        Args:
            llm_router: LLM 라우터 (None이면 Cerebras 직접 호출)
            db_path: DB 경로
            min_relevance: 최소 관련성 점수 (이하면 스킵)
            batch_size: 배치 크기
        """
        self.llm_router = llm_router
        self.db_path = db_path or str(
            Path.home() / "reze-agent" / "reze_data" / "ssot.sqlite"
        )
        self.min_relevance = min_relevance
        self.batch_size = batch_size

        # 관심 도메인 (점수 가중치용)
        self.focus_domains = [
            "ai", "llm", "startup", "saas", "seo",
            "marketing", "automation", "python", "agent"
        ]

    def _get_conn(self) -> sqlite3.Connection:
        """WAL 모드 연결"""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    async def _call_llm(self, prompt: str, temperature: float = 0.3) -> Optional[str]:
        """LLM 호출"""
        if self.llm_router:
            try:
                result = await self.llm_router.call("digest", prompt, temperature=temperature)
                return result.get("content", "")
            except Exception as e:
                logger.error(f"LLM router error: {e}")
                return None

        # Fallback: Cerebras 직접 호출
        try:
            from cerebras.cloud.sdk import AsyncCerebras
            import os

            client = AsyncCerebras(api_key=os.getenv("CEREBRAS_API_KEY"))
            response = await client.chat.completions.create(
                model="llama-3.3-70b",
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=1000
            )
            return response.choices[0].message.content

        except Exception as e:
            logger.error(f"Cerebras error: {e}")
            return None

    def _build_digest_prompt(self, item: Dict[str, Any]) -> str:
        """소화 프롬프트 생성"""
        title = item.get("title", "")
        summary = item.get("summary", "")[:1000]
        content = item.get("content", "")[:2000] if item.get("content") else ""

        return f"""당신은 기술/비즈니스 콘텐츠 분석 전문가입니다.

아래 콘텐츠를 분석하여 JSON 형식으로 인사이트를 추출하세요.

## 콘텐츠
제목: {title}
요약: {summary}
{f"본문: {content}" if content else ""}

## 출력 형식 (JSON)
{{
    "insight_type": "trend|technique|tool|strategy|case_study|insight|news|opinion 중 하나",
    "summary": "2-3문장 핵심 요약",
    "key_points": ["핵심 포인트 1", "핵심 포인트 2", ...],
    "relevance_score": 0.0-1.0 (AI/스타트업/SaaS 관련성),
    "actionability_score": 0.0-1.0 (실행 가능성),
    "novelty_score": 0.0-1.0 (새로움/독창성),
    "domains": ["관련 도메인 태그"],
    "entities": ["언급된 주요 기업/인물/기술"]
}}

중요:
- 광고성 콘텐츠는 relevance_score 0.1 이하
- 실용적 가치가 없으면 actionability_score 0.1 이하
- 기존에 많이 알려진 내용이면 novelty_score 0.3 이하
- JSON만 출력 (다른 텍스트 없이)"""

    async def digest_item(self, item: Dict[str, Any]) -> DigestResult:
        """단일 아이템 소화"""
        absorb_id = item["absorb_id"]
        result = DigestResult(absorb_id=absorb_id)

        try:
            # LLM 호출
            prompt = self._build_digest_prompt(item)
            response = await self._call_llm(prompt)

            if not response:
                result.error = "LLM response empty"
                return result

            # JSON 파싱
            try:
                # JSON 블록 추출
                if "```json" in response:
                    response = response.split("```json")[1].split("```")[0]
                elif "```" in response:
                    response = response.split("```")[1].split("```")[0]

                data = json.loads(response.strip())
            except json.JSONDecodeError as e:
                result.error = f"JSON parse error: {e}"
                return result

            # 결과 추출
            result.insight_type = data.get("insight_type", "insight")
            result.summary = data.get("summary", "")
            result.relevance_score = float(data.get("relevance_score", 0.5))
            result.actionability_score = float(data.get("actionability_score", 0.5))
            result.novelty_score = float(data.get("novelty_score", 0.5))

            # 종합 점수 계산 (가중 평균)
            result.combined_score = (
                result.relevance_score * 0.4 +
                result.actionability_score * 0.35 +
                result.novelty_score * 0.25
            )

            # 최소 관련성 체크
            if result.relevance_score < self.min_relevance:
                result.success = False
                result.error = f"Below relevance threshold ({result.relevance_score:.2f} < {self.min_relevance})"
                self._mark_item_skipped(absorb_id)
                return result

            # DB 저장
            insight_id = f"ins_{uuid.uuid4().hex[:12]}"
            result.insight_id = insight_id

            self._save_insight(
                insight_id=insight_id,
                absorb_id=absorb_id,
                source_id=item.get("source_id", ""),
                data=data,
                scores={
                    "relevance": result.relevance_score,
                    "actionability": result.actionability_score,
                    "novelty": result.novelty_score,
                    "combined": result.combined_score
                }
            )

            result.success = True

        except Exception as e:
            result.error = str(e)
            logger.error(f"Digest error for {absorb_id}: {e}")

        return result

    def _save_insight(
        self,
        insight_id: str,
        absorb_id: str,
        source_id: str,
        data: Dict[str, Any],
        scores: Dict[str, float]
    ):
        """인사이트 저장"""
        conn = self._get_conn()
        now = datetime.now().isoformat()

        try:
            conn.execute("""
                INSERT INTO digested_insights
                (insight_id, absorb_id, source_id, insight_type, summary,
                 key_points, relevance_score, actionability_score, novelty_score,
                 combined_score, domains, entities, learn_status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
            """, (
                insight_id,
                absorb_id,
                source_id,
                data.get("insight_type", "insight"),
                data.get("summary", ""),
                json.dumps(data.get("key_points", [])),
                scores["relevance"],
                scores["actionability"],
                scores["novelty"],
                scores["combined"],
                json.dumps(data.get("domains", [])),
                json.dumps(data.get("entities", [])),
                now
            ))

            # absorbed_raw 상태 업데이트
            conn.execute("""
                UPDATE absorbed_raw
                SET digest_status = 'digested'
                WHERE absorb_id = ?
            """, (absorb_id,))

            conn.commit()
        finally:
            conn.close()

    def _mark_item_skipped(self, absorb_id: str):
        """아이템 스킵 표시"""
        conn = self._get_conn()
        try:
            conn.execute("""
                UPDATE absorbed_raw
                SET digest_status = 'skipped'
                WHERE absorb_id = ?
            """, (absorb_id,))
            conn.commit()
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

    async def run_digest_cycle(
        self,
        max_items: int = None
    ) -> DigestCycleResult:
        """
        소화 사이클 실행

        Args:
            max_items: 최대 처리 수 (None이면 배치 크기)
        """
        cycle_id = f"digest_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        start_time = datetime.now()

        result = DigestCycleResult(cycle_id=cycle_id)

        try:
            limit = max_items or self.batch_size
            items = self.get_pending_items(limit=limit)

            if not items:
                logger.info("📝 No pending items to digest")
                return result

            result.items_processed = len(items)

            for item in items:
                digest_result = await self.digest_item(item)
                result.results.append(digest_result)

                if digest_result.success:
                    result.items_digested += 1
                    if digest_result.combined_score >= 0.7:
                        result.high_value_count += 1
                elif "threshold" in str(digest_result.error):
                    result.items_skipped += 1
                else:
                    result.items_error += 1

                # 간단한 rate limiting
                await asyncio.sleep(0.5)

            result.duration_sec = (datetime.now() - start_time).total_seconds()

            # 사이클 로그
            self._log_cycle(result)

            logger.info(
                f"🧠 Digest cycle: {result.items_digested} digested, "
                f"{result.items_skipped} skipped, {result.items_error} errors "
                f"(high-value: {result.high_value_count})"
            )

        except Exception as e:
            result.error = str(e)
            logger.error(f"Digest cycle error: {e}")

        return result

    def _log_cycle(self, result: DigestCycleResult):
        """사이클 로그 저장"""
        conn = self._get_conn()
        now = datetime.now().isoformat()

        try:
            conn.execute("""
                INSERT INTO predator_cycles
                (cycle_id, stage, items_processed, items_success, items_failed,
                 duration_sec, created_at, completed_at)
                VALUES (?, 'digest', ?, ?, ?, ?, ?, ?)
            """, (
                result.cycle_id,
                result.items_processed,
                result.items_digested,
                result.items_error,
                result.duration_sec,
                now,
                now
            ))
            conn.commit()
        finally:
            conn.close()

    def get_high_value_insights(
        self,
        min_score: float = 0.7,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """고가치 인사이트 조회"""
        conn = self._get_conn()
        cursor = conn.execute("""
            SELECT i.insight_id, i.insight_type, i.summary, i.key_points,
                   i.combined_score, i.domains, i.entities,
                   a.title, a.link, a.source_id
            FROM digested_insights i
            JOIN absorbed_raw a ON i.absorb_id = a.absorb_id
            WHERE i.combined_score >= ?
              AND i.learn_status = 'pending'
            ORDER BY i.combined_score DESC
            LIMIT ?
        """, (min_score, limit))
        insights = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return insights

    async def digest_batch(self, batch_size: int = 20) -> Dict[str, Any]:
        """
        배치 소화 (편의 메서드)

        Args:
            batch_size: 배치 크기 (기본 20)

        Returns:
            {
                "digested": int,
                "skipped": int,
                "errors": int,
                "high_value": int,
                "duration_sec": float
            }
        """
        result = await self.run_digest_cycle(max_items=batch_size)
        return {
            "digested": result.items_digested,
            "skipped": result.items_skipped,
            "errors": result.items_error,
            "high_value": result.high_value_count,
            "duration_sec": result.duration_sec
        }

    def get_stats(self) -> Dict[str, Any]:
        """소화 통계"""
        conn = self._get_conn()

        # 인사이트 통계
        insights = conn.execute("""
            SELECT COUNT(*) as total,
                   AVG(combined_score) as avg_score,
                   SUM(CASE WHEN combined_score >= 0.7 THEN 1 ELSE 0 END) as high_value,
                   SUM(CASE WHEN learn_status = 'pending' THEN 1 ELSE 0 END) as pending_learn
            FROM digested_insights
        """).fetchone()

        # 유형별 분포
        by_type = conn.execute("""
            SELECT insight_type, COUNT(*) as count
            FROM digested_insights
            GROUP BY insight_type
            ORDER BY count DESC
        """).fetchall()

        # 대기 아이템
        pending = conn.execute("""
            SELECT COUNT(*) as count FROM absorbed_raw
            WHERE digest_status = 'pending'
        """).fetchone()

        conn.close()

        return {
            "total_insights": insights["total"] or 0,
            "avg_score": round(insights["avg_score"] or 0, 3),
            "high_value": insights["high_value"] or 0,
            "pending_learn": insights["pending_learn"] or 0,
            "pending_digest": pending["count"] or 0,
            "by_type": {row["insight_type"]: row["count"] for row in by_type}
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

    digester = ExperienceDigester()

    # 대기 아이템 확인
    pending = digester.get_pending_items(limit=5)
    print(f"\n📝 Pending items: {len(pending)}")

    if not pending:
        print("   No items to digest. Run absorber first.")
        return

    for item in pending[:3]:
        print(f"   - {item['title'][:50]}...")

    # 소화 실행 (3개만 테스트)
    print("\n🧠 Running digest cycle (max 3 items for test)...")
    result = await digester.run_digest_cycle(max_items=3)

    print(f"\n📊 Digest Result:")
    print(f"   Processed: {result.items_processed}")
    print(f"   Digested: {result.items_digested}")
    print(f"   Skipped: {result.items_skipped}")
    print(f"   Errors: {result.items_error}")
    print(f"   High-value: {result.high_value_count}")
    print(f"   Duration: {result.duration_sec:.1f}s")

    # 고가치 인사이트
    high_value = digester.get_high_value_insights(min_score=0.6, limit=5)
    if high_value:
        print(f"\n🌟 High-value insights:")
        for ins in high_value:
            print(f"   [{ins['insight_type']}] {ins['summary'][:60]}... (score: {ins['combined_score']:.2f})")

    # 통계
    stats = digester.get_stats()
    print(f"\n📈 Stats:")
    print(f"   Total insights: {stats['total_insights']}")
    print(f"   Avg score: {stats['avg_score']}")
    print(f"   High-value: {stats['high_value']}")


if __name__ == "__main__":
    asyncio.run(main())
