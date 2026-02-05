"""
Experience-Driven Lifelong Learning — REZE v6.0 SOVEREIGN
장기 기억 시스템

모든 경험을 구조화된 장기 기억으로 축적하고,
유사 상황에서 자동으로 참조하여 학습합니다.

가동 조건: experience_memory >= 30건
"""

import json
import re
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

logger = logging.getLogger("reze.evolve.lifelong")


class LifelongLearning:
    """
    평생 학습 시스템.
    경험 기록 → 교훈 추출 → 유사 상황 회상 → 조언 제공.
    """

    # 불용어 (검색에서 제외)
    STOP_WORDS = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "in", "on", "at", "to", "for", "of", "with", "and", "or",
        "not", "this", "that", "it", "from", "by", "as", "but"
    }

    def __init__(self, ssot, llm_router=None):
        """
        Args:
            ssot: SSOT 인스턴스
            llm_router: LLM 라우터 (교훈 추출용)
        """
        self.ssot = ssot
        self.conn = ssot.conn if hasattr(ssot, 'conn') else ssot
        self.llm = llm_router

    async def is_active(self) -> bool:
        """활성화 조건 확인: experience_memory >= 30"""
        try:
            row = self.conn.execute(
                "SELECT COUNT(*) as cnt FROM experience_memory"
            ).fetchone()
            return row[0] >= 30
        except:
            return False

    async def record_experience(
        self,
        exp_type: str,
        summary: str,
        details: dict,
        lesson: str = None,
        tags: List[str] = None
    ) -> str:
        """
        경험 기록.

        Args:
            exp_type: 경험 유형 (hunt, error, success, evolution, etc.)
            summary: 경험 요약
            details: 상세 정보 (dict)
            lesson: 교훈 (없으면 LLM으로 추출 시도)
            tags: 태그 리스트

        Returns:
            experience_id
        """
        eid = f"exp_{exp_type}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"

        # 교훈 추출 (LLM 사용 가능 시)
        if not lesson and self.llm:
            try:
                lesson = await self._extract_lesson(exp_type, summary, details)
            except:
                lesson = ""

        # 검색용 텍스트 생성
        search_text = self._build_search_text(exp_type, summary, tags or [], lesson)

        try:
            self.conn.execute("""
                INSERT INTO experience_memory
                (experience_id, exp_type, summary, details, lesson,
                 tags, search_text, usefulness_score, access_count,
                 archived, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0.5, 0, 0, ?)
            """, (
                eid, exp_type, summary,
                json.dumps(details, default=str),
                lesson or "",
                json.dumps(tags or []),
                search_text,
                datetime.utcnow().isoformat()
            ))
            self.conn.commit()

            logger.debug("Lifelong: recorded %s [%s]", eid, exp_type)
        except Exception as e:
            logger.error("Failed to record experience: %s", e)

        return eid

    async def _extract_lesson(
        self,
        exp_type: str,
        summary: str,
        details: dict
    ) -> str:
        """LLM으로 교훈 추출"""
        if not self.llm:
            return ""

        prompt = (
            f"Extract one concise lesson from this experience:\n"
            f"Type: {exp_type}\n"
            f"Summary: {summary}\n"
            f"Details: {json.dumps(details)[:500]}\n"
            f"Respond with only the lesson (one sentence)."
        )

        try:
            response = await self.llm.call(
                "cerebras",
                [{"role": "user", "content": prompt}],
                max_tokens=100
            )
            lesson = response.text if hasattr(response, 'text') else str(response)
            return lesson.strip()[:200]
        except:
            return ""

    def _build_search_text(
        self,
        exp_type: str,
        summary: str,
        tags: List[str],
        lesson: str
    ) -> str:
        """검색용 텍스트 생성"""
        parts = [exp_type, summary]
        parts.extend(tags)
        if lesson:
            parts.append(lesson)
        return " ".join(parts)

    def _extract_keywords(self, text: str, max_keywords: int = 15) -> List[str]:
        """텍스트에서 키워드 추출"""
        # 소문자 변환 + 단어 추출
        words = re.findall(r'\b[a-z_]{3,}\b', text.lower())
        # 불용어 제거 + 중복 제거
        keywords = [w for w in words if w not in self.STOP_WORDS]
        # 빈도순 정렬
        from collections import Counter
        freq = Counter(keywords)
        return [w for w, _ in freq.most_common(max_keywords)]

    async def recall(
        self,
        situation: str,
        context: dict = None,
        max_results: int = 5
    ) -> List[Dict]:
        """
        유사 경험 회상.

        Args:
            situation: 현재 상황 설명
            context: 추가 컨텍스트
            max_results: 최대 결과 수

        Returns:
            관련 경험 리스트
        """
        keywords = self._extract_keywords(situation)

        if not keywords:
            return []

        # SQLite LIKE 검색 (FTS 없이도 동작)
        # 최대 3개 키워드로 검색
        kw_clauses = " OR ".join(["search_text LIKE ?" for _ in keywords[:3]])
        kw_params = [f"%{k}%" for k in keywords[:3]]

        try:
            rows = self.conn.execute(f"""
                SELECT experience_id, exp_type, summary, lesson,
                       usefulness_score, created_at,
                       1.0 / (1.0 + julianday('now') - julianday(created_at)) as recency
                FROM experience_memory
                WHERE archived = 0 AND ({kw_clauses})
                ORDER BY (recency * 0.3 + usefulness_score * 0.7) DESC
                LIMIT ?
            """, (*kw_params, max_results)).fetchall()

            results = []
            for r in rows:
                # 접근 횟수 증가
                self.conn.execute(
                    "UPDATE experience_memory SET access_count = access_count + 1 "
                    "WHERE experience_id = ?",
                    (r[0],)
                )

                results.append({
                    "experience_id": r[0],
                    "type": r[1],
                    "summary": r[2],
                    "lesson": r[3],
                    "usefulness": r[4],
                    "relevance": round(r[6] * 0.3 + r[4] * 0.7, 3)
                })

            self.conn.commit()
            return results

        except Exception as e:
            logger.error("Failed to recall: %s", e)
            return []

    def rate_usefulness(self, experience_id: str, useful: bool) -> bool:
        """
        경험 유용성 평가.

        Args:
            experience_id: 경험 ID
            useful: 유용했는지 여부

        Returns:
            성공 여부
        """
        delta = 0.1 if useful else -0.1

        try:
            self.conn.execute("""
                UPDATE experience_memory
                SET usefulness_score = MIN(1.0, MAX(0.0, usefulness_score + ?))
                WHERE experience_id = ?
            """, (delta, experience_id))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error("Failed to rate usefulness: %s", e)
            return False

    async def consolidate(self) -> Dict:
        """
        기억 통합.
        - 오래되고 안 쓰이는 기억 아카이브
        - 메타 교훈 추출
        """
        result = {
            "archived_count": 0,
            "meta_lessons_created": 0,
            "timestamp": datetime.utcnow().isoformat()
        }

        # 1. 오래되고 안 쓰이는 기억 아카이브
        try:
            cursor = self.conn.execute("""
                UPDATE experience_memory
                SET archived = 1
                WHERE access_count = 0
                  AND usefulness_score < 0.3
                  AND created_at < datetime('now', '-90 days')
            """)
            result["archived_count"] = cursor.rowcount
            self.conn.commit()
        except Exception as e:
            logger.error("Archive failed: %s", e)

        # 2. 유형별 메타 교훈 추출
        if not self.llm:
            return result

        try:
            types = self.conn.execute("""
                SELECT exp_type, COUNT(*) as cnt
                FROM experience_memory
                WHERE archived = 0
                GROUP BY exp_type
                HAVING cnt >= 10
            """).fetchall()

            for exp_type, count in types:
                # 해당 유형의 상위 교훈들 수집
                lessons = self.conn.execute("""
                    SELECT lesson FROM experience_memory
                    WHERE exp_type = ? AND archived = 0 AND lesson != ''
                    ORDER BY usefulness_score DESC
                    LIMIT 20
                """, (exp_type,)).fetchall()

                if len(lessons) >= 10:
                    # 메타 교훈 생성
                    meta_lesson = await self._synthesize_meta_lesson(
                        exp_type,
                        [l[0] for l in lessons]
                    )

                    if meta_lesson:
                        await self.record_experience(
                            exp_type="meta_lesson",
                            summary=f"Meta-lesson from {exp_type} ({count} experiences)",
                            details={
                                "source_type": exp_type,
                                "source_count": count
                            },
                            lesson=meta_lesson,
                            tags=["meta", exp_type]
                        )
                        result["meta_lessons_created"] += 1

        except Exception as e:
            logger.error("Meta-lesson extraction failed: %s", e)

        return result

    async def _synthesize_meta_lesson(
        self,
        exp_type: str,
        lessons: List[str]
    ) -> Optional[str]:
        """여러 교훈을 종합하여 메타 교훈 생성"""
        if not self.llm:
            return None

        prompt = (
            f"Synthesize these {len(lessons)} lessons about '{exp_type}' "
            f"into one meta-lesson:\n"
            f"{json.dumps(lessons)}\n"
            f"Respond with only the synthesized lesson (1-2 sentences)."
        )

        try:
            response = await self.llm.call(
                "groq",
                [{"role": "user", "content": prompt}],
                max_tokens=200
            )
            meta = response.text if hasattr(response, 'text') else str(response)
            return meta.strip()[:300]
        except:
            return None

    async def get_advice(
        self,
        situation: str,
        context: dict = None
    ) -> str:
        """
        상황에 대한 조언 생성.

        Args:
            situation: 현재 상황
            context: 추가 컨텍스트

        Returns:
            조언 문자열
        """
        # 관련 경험 회상
        memories = await self.recall(situation, context, max_results=5)

        if not memories:
            return ""

        lessons = [m["lesson"] for m in memories if m.get("lesson")]

        if not lessons:
            return ""

        if not self.llm:
            # LLM 없으면 가장 관련성 높은 교훈 반환
            return lessons[0] if lessons else ""

        # LLM으로 조언 생성
        prompt = (
            f"Based on these past lessons:\n"
            f"{json.dumps(lessons)}\n\n"
            f"Give specific advice for this situation:\n"
            f"{situation}\n\n"
            f"Respond with 2-3 actionable sentences."
        )

        try:
            response = await self.llm.call(
                "cerebras",
                [{"role": "user", "content": prompt}],
                max_tokens=200
            )
            advice = response.text if hasattr(response, 'text') else str(response)
            return advice.strip()
        except:
            return lessons[0] if lessons else ""

    def get_stats(self) -> Dict:
        """경험 메모리 통계"""
        try:
            total = self.conn.execute(
                "SELECT COUNT(*) FROM experience_memory WHERE archived = 0"
            ).fetchone()[0]

            by_type = self.conn.execute("""
                SELECT exp_type, COUNT(*), AVG(usefulness_score)
                FROM experience_memory
                WHERE archived = 0
                GROUP BY exp_type
            """).fetchall()

            most_useful = self.conn.execute("""
                SELECT experience_id, exp_type, lesson, usefulness_score
                FROM experience_memory
                WHERE archived = 0 AND lesson != ''
                ORDER BY usefulness_score DESC
                LIMIT 5
            """).fetchall()

            return {
                "total_experiences": total,
                "by_type": {
                    r[0]: {"count": r[1], "avg_usefulness": round(r[2] or 0, 3)}
                    for r in by_type
                },
                "top_lessons": [
                    {"type": r[1], "lesson": r[2], "score": r[3]}
                    for r in most_useful
                ]
            }
        except:
            return {"error": "Failed to get stats"}
