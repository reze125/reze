"""
Curiosity-Driven Exploration — REZE v6.0 SOVEREIGN
호기심 기반 탐색

미탐색 영역을 자동으로 식별하고,
새로운 사냥터와 전략을 시도합니다.

가동 조건: hunt_log >= 50
"""

import json
import logging
from datetime import datetime
from collections import defaultdict
from typing import Optional, List, Dict, Any

logger = logging.getLogger("reze.evolve.curiosity")


class CuriosityEngine:
    """
    호기심 기반 탐색 엔진.
    미탐색 영역 식별 → 탐색 제안 → 실행 추적.
    """

    # 기본 전략 목록
    DEFAULT_STRATEGIES = [
        "trend_snipe",      # 트렌드 스나이핑
        "gap_fill",         # 콘텐츠 갭 채우기
        "comparison",       # 비교 콘텐츠
        "deep_guide",       # 심층 가이드
        "news_jack",        # 뉴스 잭킹
        "tool_review",      # 도구 리뷰
        "listicle",         # 리스트형 글
    ]

    def __init__(self, ssot, llm_router=None, tavily_client=None):
        """
        Args:
            ssot: SSOT 인스턴스
            llm_router: LLM 라우터
            tavily_client: Tavily 검색 클라이언트
        """
        self.ssot = ssot
        self.conn = ssot.conn if hasattr(ssot, 'conn') else ssot
        self.llm = llm_router
        self.tavily = tavily_client

    async def is_active(self) -> bool:
        """활성화 조건 확인: hunt_log >= 50 또는 hunt_memory >= 50"""
        try:
            row = self.conn.execute(
                "SELECT COUNT(*) FROM hunt_log"
            ).fetchone()
            if row[0] >= 50:
                return True
        except:
            pass

        try:
            row = self.conn.execute(
                "SELECT COUNT(*) FROM hunt_memory"
            ).fetchone()
            return row[0] >= 50
        except:
            return False

    async def build_exploration_map(self) -> Dict[str, Dict]:
        """
        탐색 지도 구축.
        niche::strategy 조합별 시도 현황 분석.
        """
        try:
            # hunt_log 우선 사용
            rows = self.conn.execute("""
                SELECT niche, strategy, COUNT(*) as attempts,
                       AVG(quality_score) as avg_quality,
                       MAX(created_at) as last_attempt,
                       SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) as wins
                FROM hunt_log
                GROUP BY niche, strategy
            """).fetchall()

            if not rows:
                # hunt_memory 폴백
                rows = self.conn.execute("""
                    SELECT 'default' as niche, strategy,
                           COUNT(*) as attempts,
                           AVG(score) as avg_quality,
                           MAX(created_at) as last_attempt,
                           SUM(success) as wins
                    FROM hunt_memory
                    GROUP BY strategy
                """).fetchall()

        except:
            return {}

        exploration_map = {}

        for row in rows:
            niche = row[0] or "default"
            strategy = row[1] or "unknown"
            key = f"{niche}::{strategy}"

            attempts = row[2] or 0
            avg_quality = row[3] or 0
            last_attempt = row[4]
            wins = row[5] or 0

            exploration_map[key] = {
                "niche": niche,
                "strategy": strategy,
                "attempts": attempts,
                "avg_quality": round(avg_quality, 1) if avg_quality else 0,
                "success_rate": round(wins / attempts, 2) if attempts > 0 else 0,
                "freshness": self._days_since(last_attempt),
                "last_attempt": last_attempt
            }

        return exploration_map

    def _days_since(self, iso_date: str) -> int:
        """날짜로부터 경과 일수"""
        if not iso_date:
            return 999

        try:
            dt = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
            dt = dt.replace(tzinfo=None)
            return (datetime.utcnow() - dt).days
        except:
            return 999

    async def compute_curiosity_scores(self) -> List[Dict]:
        """
        호기심 점수 계산.
        미탐색/저성능/오래된 영역에 높은 점수.
        """
        exploration_map = await self.build_exploration_map()
        niches = await self._get_niches()
        strategies = self.DEFAULT_STRATEGIES

        scores = []

        for niche in niches:
            for strategy in strategies:
                key = f"{niche}::{strategy}"
                data = exploration_map.get(key)

                if data is None:
                    # 한 번도 시도 안 함 → 높은 호기심 (epistemic)
                    scores.append({
                        "niche": niche,
                        "strategy": strategy,
                        "curiosity_type": "epistemic",
                        "score": 0.85,
                        "reason": "Never tried this combination"
                    })

                elif data["attempts"] < 5:
                    # 시도 횟수 부족 → 불확실성 높음
                    uncertainty = 1.0 - (data["attempts"] / 5.0)
                    quality_bonus = data["avg_quality"] / 10.0 if data["avg_quality"] else 0
                    score = 0.4 * uncertainty + 0.3 * quality_bonus

                    scores.append({
                        "niche": niche,
                        "strategy": strategy,
                        "curiosity_type": "epistemic",
                        "score": round(score, 3),
                        "reason": f"Only {data['attempts']} attempts, need more data"
                    })

                elif data["success_rate"] < 0.3 and data["attempts"] >= 10:
                    # 저성능 → 개선 가능성 (competence)
                    scores.append({
                        "niche": niche,
                        "strategy": strategy,
                        "curiosity_type": "competence",
                        "score": 0.35,
                        "reason": f"Low success rate ({data['success_rate']:.0%}), room for improvement"
                    })

                elif data["freshness"] > 30:
                    # 오래 안 시도함 → 신선함 (novelty)
                    novelty_score = min(data["freshness"] / 60, 1.0) * 0.5

                    scores.append({
                        "niche": niche,
                        "strategy": strategy,
                        "curiosity_type": "novelty",
                        "score": round(novelty_score, 3),
                        "reason": f"Not tried in {data['freshness']} days"
                    })

        # 점수 내림차순 정렬
        scores.sort(key=lambda x: x["score"], reverse=True)

        return scores

    async def _get_niches(self) -> List[str]:
        """활성 niche 목록 가져오기"""
        # blog_config에서 가져오기
        try:
            rows = self.conn.execute(
                "SELECT DISTINCT niche FROM blog_config WHERE active = 1"
            ).fetchall()
            if rows:
                return [r[0] for r in rows]
        except:
            pass

        # hunt_log에서 추출
        try:
            rows = self.conn.execute(
                "SELECT DISTINCT niche FROM hunt_log WHERE niche IS NOT NULL"
            ).fetchall()
            if rows:
                return [r[0] for r in rows if r[0]]
        except:
            pass

        # 기본값
        return ["ai_tools", "nocode", "productivity"]

    async def suggest_exploration(self, max_suggestions: int = 3) -> List[Dict]:
        """
        탐색 제안 생성.

        Args:
            max_suggestions: 최대 제안 수

        Returns:
            탐색 제안 리스트
        """
        scores = await self.compute_curiosity_scores()
        suggestions = []

        for candidate in scores[:max_suggestions]:
            # 탐색 계획 생성
            plan = await self._generate_exploration_plan(candidate)

            if plan:
                suggestion = {**candidate, "plan": plan}
                suggestions.append(suggestion)

                # DB에 저장
                try:
                    self.conn.execute("""
                        INSERT INTO curiosity_suggestions
                        (niche, strategy, curiosity_type, score, reason,
                         plan, status, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, 'suggested', ?)
                    """, (
                        candidate["niche"],
                        candidate["strategy"],
                        candidate["curiosity_type"],
                        candidate["score"],
                        candidate["reason"],
                        json.dumps(plan),
                        datetime.utcnow().isoformat()
                    ))
                    self.conn.commit()
                except Exception as e:
                    logger.error("Failed to save suggestion: %s", e)

        return suggestions

    async def _generate_exploration_plan(self, candidate: Dict) -> Optional[Dict]:
        """탐색 계획 생성"""
        if not self.llm:
            # LLM 없으면 기본 계획
            return {
                "target_keyword": f"{candidate['niche']} {candidate['strategy']}",
                "approach": candidate["strategy"],
                "success_criteria": "Quality score >= 7",
                "estimated_effort": "medium",
                "expected_learning": candidate["reason"]
            }

        prompt = f"""Create an exploration plan for:
Niche: {candidate['niche']}
Strategy: {candidate['strategy']}
Curiosity Type: {candidate['curiosity_type']}
Reason: {candidate['reason']}

Respond in JSON:
{{
  "target_keyword": "specific keyword to target",
  "approach": "detailed approach",
  "success_criteria": "how to measure success",
  "estimated_effort": "low/medium/high",
  "expected_learning": "what we expect to learn"
}}"""

        try:
            response = await self.llm.call(
                "cerebras",
                [{"role": "user", "content": prompt}],
                max_tokens=500
            )

            text = response.text if hasattr(response, 'text') else str(response)
            return json.loads(self._extract_json(text))

        except:
            return None

    def _extract_json(self, text: str) -> str:
        """텍스트에서 JSON 추출"""
        if "```json" in text:
            return text.split("```json")[1].split("```")[0].strip()

        start = text.find("{")
        end = text.rfind("}") + 1

        if start >= 0 and end > start:
            return text[start:end]

        return "{}"

    def mark_suggestion_tried(
        self,
        niche: str,
        strategy: str,
        result: str = None
    ):
        """제안 시도 표시"""
        try:
            self.conn.execute("""
                UPDATE curiosity_suggestions
                SET status = 'tried', tried_at = ?, result = ?
                WHERE niche = ? AND strategy = ? AND status = 'suggested'
            """, (
                datetime.utcnow().isoformat(),
                result,
                niche, strategy
            ))
            self.conn.commit()
        except Exception as e:
            logger.error("Failed to mark suggestion: %s", e)

    def get_recent_suggestions(self, limit: int = 20) -> List[Dict]:
        """최근 제안 목록"""
        try:
            rows = self.conn.execute("""
                SELECT niche, strategy, curiosity_type, score,
                       reason, status, created_at, tried_at, result
                FROM curiosity_suggestions
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,)).fetchall()

            return [
                {
                    "niche": r[0],
                    "strategy": r[1],
                    "curiosity_type": r[2],
                    "score": r[3],
                    "reason": r[4],
                    "status": r[5],
                    "created_at": r[6],
                    "tried_at": r[7],
                    "result": r[8]
                }
                for r in rows
            ]
        except:
            return []

    async def get_exploration_stats(self) -> Dict:
        """탐색 통계"""
        exploration_map = await self.build_exploration_map()

        total_combinations = len(exploration_map)
        explored = sum(1 for d in exploration_map.values() if d["attempts"] >= 5)
        high_performing = sum(
            1 for d in exploration_map.values()
            if d["success_rate"] >= 0.5 and d["attempts"] >= 5
        )

        return {
            "total_combinations": total_combinations,
            "well_explored": explored,
            "high_performing": high_performing,
            "exploration_coverage": round(explored / max(total_combinations, 1), 2),
            "map": exploration_map
        }
