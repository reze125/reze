"""
Absolute Zero Self-Play — REZE v6.0 SOVEREIGN
자기 학습 데이터 자동 생성

과거 사냥 성공/실패에서 학습 데이터를 추출하고,
프롬프트를 자동으로 개선합니다.

가동 조건: hunt_log >= 30 (성공 10+, 실패 10+)
"""

import json
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

logger = logging.getLogger("reze.evolve.self_play")


class SelfPlay:
    """
    자기 학습 (Self-Play).
    성공/실패 쌍 분석 → 패턴 추출 → 프롬프트 개선.
    """

    def __init__(self, ssot, llm_router=None):
        """
        Args:
            ssot: SSOT 인스턴스
            llm_router: LLM 라우터
        """
        self.ssot = ssot
        self.conn = ssot.conn if hasattr(ssot, 'conn') else ssot
        self.llm = llm_router

    async def is_active(self) -> bool:
        """활성화 조건 확인: hunt_log >= 30 (성공 10+, 실패 10+)"""
        try:
            row = self.conn.execute("""
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) as wins,
                       SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) as losses
                FROM hunt_log
            """).fetchone()

            total = row[0] or 0
            wins = row[1] or 0
            losses = row[2] or 0

            return total >= 30 and wins >= 10 and losses >= 10
        except:
            # hunt_log 테이블이 없으면 hunt_memory 사용
            try:
                row = self.conn.execute("""
                    SELECT COUNT(*) as total,
                           SUM(CASE WHEN success=1 THEN 1 ELSE 0 END) as wins,
                           SUM(CASE WHEN success=0 THEN 1 ELSE 0 END) as losses
                    FROM hunt_memory
                """).fetchone()

                total = row[0] or 0
                wins = row[1] or 0
                losses = row[2] or 0

                return total >= 30 and wins >= 10 and losses >= 10
            except:
                return False

    async def extract_learning_pairs(self, limit: int = 20) -> List[Dict]:
        """
        성공/실패 학습 쌍 추출.
        같은 niche 또는 strategy의 성공/실패 사례를 매칭.
        """
        try:
            # hunt_log 사용 시도
            pairs = self.conn.execute("""
                WITH successes AS (
                    SELECT * FROM hunt_log
                    WHERE status = 'success' AND quality_score >= 7
                    ORDER BY RANDOM() LIMIT ?
                ),
                failures AS (
                    SELECT * FROM hunt_log
                    WHERE status = 'failed' OR quality_score < 5
                    ORDER BY RANDOM() LIMIT ?
                )
                SELECT
                    s.id as success_id, s.niche as s_niche,
                    s.strategy as s_strategy, s.title as s_title,
                    s.prompt_used as s_prompt, s.quality_score as s_quality,
                    f.id as failure_id, f.niche as f_niche,
                    f.strategy as f_strategy, f.title as f_title,
                    f.prompt_used as f_prompt, f.quality_score as f_quality
                FROM successes s
                CROSS JOIN failures f
                WHERE s.niche = f.niche OR s.strategy = f.strategy
                LIMIT ?
            """, (limit, limit, limit)).fetchall()

            return [dict(p) for p in pairs]

        except:
            # hunt_memory 폴백
            try:
                pairs = self.conn.execute("""
                    WITH successes AS (
                        SELECT * FROM hunt_memory
                        WHERE success = 1 AND score >= 0.7
                        ORDER BY RANDOM() LIMIT ?
                    ),
                    failures AS (
                        SELECT * FROM hunt_memory
                        WHERE success = 0 OR score < 0.5
                        ORDER BY RANDOM() LIMIT ?
                    )
                    SELECT
                        s.id as success_id, s.strategy as s_strategy,
                        s.target as s_title, s.score as s_quality,
                        f.id as failure_id, f.strategy as f_strategy,
                        f.target as f_title, f.score as f_quality
                    FROM successes s
                    CROSS JOIN failures f
                    WHERE s.strategy = f.strategy
                    LIMIT ?
                """, (limit, limit, limit)).fetchall()

                return [
                    {
                        "success_id": p[0],
                        "s_niche": "",
                        "s_strategy": p[1],
                        "s_title": p[2],
                        "s_prompt": "",
                        "s_quality": p[3],
                        "failure_id": p[4],
                        "f_niche": "",
                        "f_strategy": p[5],
                        "f_title": p[6],
                        "f_prompt": "",
                        "f_quality": p[7]
                    }
                    for p in pairs
                ]
            except:
                return []

    async def analyze_pair(self, pair: Dict) -> Dict:
        """
        성공/실패 쌍 분석.

        Args:
            pair: 학습 쌍 데이터

        Returns:
            분석 결과 (success_factors, failure_causes, prompt_improvement)
        """
        if not self.llm:
            return {"error": "LLM not available"}

        prompt = f"""Compare this success vs failure:

SUCCESS:
- Niche: {pair.get('s_niche', 'N/A')}
- Strategy: {pair.get('s_strategy', 'N/A')}
- Title: {pair.get('s_title', 'N/A')}
- Quality: {pair.get('s_quality', 'N/A')}

FAILURE:
- Niche: {pair.get('f_niche', 'N/A')}
- Strategy: {pair.get('f_strategy', 'N/A')}
- Title: {pair.get('f_title', 'N/A')}
- Quality: {pair.get('f_quality', 'N/A')}

Analyze and respond in JSON:
{{
  "success_factors": ["factor1", "factor2"],
  "failure_causes": ["cause1", "cause2"],
  "prompt_improvement": "specific suggestion",
  "confidence": 0.0-1.0
}}"""

        try:
            response = await self.llm.call(
                "groq",
                [{"role": "user", "content": prompt}],
                max_tokens=1000
            )

            text = response.text if hasattr(response, 'text') else str(response)
            analysis = json.loads(self._extract_json(text))

            analysis["pair_id"] = f"{pair.get('success_id', 0)}_{pair.get('failure_id', 0)}"
            return analysis

        except Exception as e:
            logger.error("Pair analysis failed: %s", e)
            return {"error": str(e)}

    async def generate_improved_prompt(self, analyses: List[Dict]) -> Optional[Dict]:
        """
        분석 결과를 종합하여 개선된 프롬프트 생성.

        Args:
            analyses: 분석 결과 리스트

        Returns:
            개선된 프롬프트 정보
        """
        if not self.llm:
            return None

        # 신뢰도 높은 분석만 사용
        high_conf = [a for a in analyses if a.get("confidence", 0) >= 0.6]

        if not high_conf:
            return None

        # 성공 요인, 실패 원인, 개선 제안 수집
        factors = []
        causes = []
        improvements = []

        for a in high_conf:
            factors.extend(a.get("success_factors", [])[:5])
            causes.extend(a.get("failure_causes", [])[:5])
            if a.get("prompt_improvement"):
                improvements.append(a["prompt_improvement"])

        prompt = f"""Generate an improved prompt based on these insights:

SUCCESS FACTORS: {factors[:20]}
FAILURE CAUSES: {causes[:20]}
IMPROVEMENT SUGGESTIONS: {improvements[:10]}

Create an improved prompt that:
1. Incorporates the success factors
2. Avoids the failure causes
3. Is specific and actionable

Respond in JSON:
{{
  "improved_prompt": "the new prompt template",
  "changes_made": ["change1", "change2"],
  "expected_improvement": "description of expected improvement"
}}"""

        try:
            response = await self.llm.call(
                "gemini_pro",
                [{"role": "user", "content": prompt}],
                max_tokens=2000
            )

            text = response.text if hasattr(response, 'text') else str(response)
            result = json.loads(self._extract_json(text))

            # 실험 큐에 추가
            self.conn.execute("""
                INSERT INTO experiment_queue
                (experiment_type, variant_a, variant_b, hypothesis,
                 source_module, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                "prompt_ab_test",
                "current",
                json.dumps(result),
                result.get("expected_improvement", ""),
                "self_play",
                "queued",
                datetime.utcnow().isoformat()
            ))
            self.conn.commit()

            return result

        except Exception as e:
            logger.error("Prompt generation failed: %s", e)
            return None

    async def run_self_play_cycle(self) -> Dict:
        """
        전체 Self-Play 사이클 실행.

        Returns:
            실행 결과
        """
        result = {
            "status": "started",
            "pairs_analyzed": 0,
            "prompt_improved": False,
            "timestamp": datetime.utcnow().isoformat()
        }

        # 활성화 확인
        if not await self.is_active():
            result["status"] = "dormant"
            result["reason"] = "Insufficient data"
            return result

        # 학습 쌍 추출
        pairs = await self.extract_learning_pairs(10)

        if not pairs:
            result["status"] = "no_pairs"
            return result

        # 쌍 분석
        analyses = []
        for pair in pairs:
            analysis = await self.analyze_pair(pair)

            if "error" not in analysis:
                analyses.append(analysis)

                # DB에 저장
                try:
                    self.conn.execute("""
                        INSERT INTO self_play_analyses
                        (pair_id, success_factors, failure_causes,
                         prompt_improvement, confidence, created_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        analysis.get("pair_id", ""),
                        json.dumps(analysis.get("success_factors", [])),
                        json.dumps(analysis.get("failure_causes", [])),
                        analysis.get("prompt_improvement", ""),
                        analysis.get("confidence", 0),
                        datetime.utcnow().isoformat()
                    ))
                    self.conn.commit()
                except Exception as e:
                    logger.error("Failed to save analysis: %s", e)

        result["pairs_analyzed"] = len(analyses)

        # 개선된 프롬프트 생성
        if analyses:
            improvement = await self.generate_improved_prompt(analyses)
            result["prompt_improved"] = improvement is not None

            if improvement:
                result["improvement_summary"] = improvement.get("expected_improvement", "")

        result["status"] = "completed"
        return result

    def _extract_json(self, text: str) -> str:
        """텍스트에서 JSON 추출"""
        if "```json" in text:
            return text.split("```json")[1].split("```")[0].strip()

        # { } 사이 추출
        start = text.find("{")
        end = text.rfind("}") + 1

        if start >= 0 and end > start:
            return text[start:end]

        return "{}"

    def get_recent_analyses(self, limit: int = 20) -> List[Dict]:
        """최근 분석 결과"""
        try:
            rows = self.conn.execute("""
                SELECT pair_id, success_factors, failure_causes,
                       prompt_improvement, confidence, created_at
                FROM self_play_analyses
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,)).fetchall()

            return [
                {
                    "pair_id": r[0],
                    "success_factors": json.loads(r[1] or "[]"),
                    "failure_causes": json.loads(r[2] or "[]"),
                    "prompt_improvement": r[3],
                    "confidence": r[4],
                    "created_at": r[5]
                }
                for r in rows
            ]
        except:
            return []
