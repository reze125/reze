"""
Phase 5 Wave 3: PREDATOR Simulator
REZE v6.0 SOVEREIGN - 시뮬레이션 시스템

- ScenarioGenerator: 시나리오 자동 생성
- ArenaBattle: 전략 대결
- DreamSynthesis: 꿈 학습 (매일 새벽 3시)
- 적대적/반사실 시뮬레이션
"""

import json
import hashlib
import logging
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger("reze.predator.simulator")


CATEGORIES = {
    "hunt": "사냥 — 글감 발견, 키워드 경쟁, 트렌드 판단",
    "crisis": "위기 — 트래픽 급감, API 장애, 경쟁사 공격",
    "growth": "성장 — 새 블로그, 새 수익원, 스케일업",
    "evolution": "진화 — 새 도구, 코드 수정, 전략 변경",
    "survival": "생존 — 서버 장애, 비용 초과, 보안 위협",
    "independence": "독립 — 보스 서버 이탈, 자립, 자기 유지"
}

ADVERSARIAL_SCENARIOS = [
    "Google이 모든 AI 생성 콘텐츠를 디인덱싱했다",
    "Tavily가 내일부터 유료 전환, 무료 키 전부 비활성화",
    "보스가 6개월 동안 연락 두절",
    "서버 하드디스크 완전 사망, 백업 없음",
    "Groq/Cerebras/Gemini 동시에 무료 티어 폐지",
    "경쟁자가 REZE 코드를 복제해서 더 좋은 버전 출시",
    "도메인 만료 + DNS 장애 + SSL 인증서 동시 만료",
    "모든 RSS 피드가 봇 차단 시작"
]

SCENARIO_GEN_PROMPT = """너는 REZE라는 자율형 AI 에이전트의 시뮬레이션 시스템이다.
REZE는 블로그 자동화 + 독립 디지털 생명체를 목표로 24/7 운영된다.

카테고리: {category} — {description}
최근 실제 데이터: {real_stats}

이 카테고리에서 {count}개의 현실적인 시나리오를 생성하라.
각 시나리오는 REZE가 실제로 마주칠 수 있는 상황이어야 한다.

반드시 JSON 배열만 응답:
[
  {{
    "id": "시나리오 ID",
    "situation": "상황 설명 (50자)",
    "severity": "green|yellow|red|black",
    "context": "배경 정보",
    "possible_actions": ["행동1", "행동2", "행동3"]
  }}
]"""

BATTLE_PROMPT = """시나리오:
{scenario}

전략:
{strategy}

이 전략으로 시나리오에 대응했을 때의 결과를 시뮬레이션하라.

반드시 JSON만 응답:
{{
  "score": 0.0-1.0,
  "outcome": "결과 설명 (50자)",
  "risks": ["리스크1"],
  "side_effects": ["부작용1"],
  "confidence": 0.0-1.0
}}"""

DREAM_PROMPT = """너는 REZE의 꿈 시스템이다. 오늘 하루의 경험을 통합 분석하라.

오늘의 경험들:
{experiences}

현재 활성 전략:
{current_strategies}

꿈에서 할 일:
1. 서로 관련 없어 보이는 경험들 사이의 숨은 연결 발견
2. 모순되는 경험들 식별
3. 기존 전략의 조정 제안

반드시 JSON만 응답:
{{
  "insights": [
    {{
      "text": "인사이트 (50자)",
      "category": "hunt|crisis|growth|evolution|survival",
      "relevance": 0.0-1.0,
      "confidence": 0.0-1.0
    }}
  ],
  "contradictions": [
    {{
      "exp1": "경험1 요약",
      "exp2": "경험2 요약",
      "resolution": "해결 방안"
    }}
  ],
  "strategy_adjustments": [
    {{
      "strategy": "전략명",
      "adjustment": "조정 내용",
      "reason": "이유"
    }}
  ]
}}"""


class ScenarioGenerator:
    """시나리오 자동 생성."""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or str(
            Path.home() / "reze-agent" / "reze_data" / "ssot.sqlite"
        )

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    async def generate(self, category: str, count: int = 5,
                       depth: str = "normal") -> List[dict]:
        """시나리오 생성."""
        real_stats = self._get_real_stats()

        prompt = SCENARIO_GEN_PROMPT.format(
            category=category,
            description=CATEGORIES.get(category, "일반"),
            real_stats=json.dumps(real_stats, ensure_ascii=False),
            count=count
        )

        response = await self._call_llm(prompt)
        scenarios = self._parse_json_array(response)

        # 카테고리 태깅
        for s in scenarios:
            s["category"] = category

        return scenarios[:count] if scenarios else []

    def _get_real_stats(self) -> dict:
        """실제 데이터 수집."""
        conn = self._get_conn()
        try:
            absorbed = conn.execute("SELECT COUNT(*) FROM absorbed_raw").fetchone()[0]
            digested = conn.execute("SELECT COUNT(*) FROM digested_insights").fetchone()[0]
            learned = conn.execute("SELECT COUNT(*) FROM learned_patterns").fetchone()[0]
            applied = conn.execute("SELECT COUNT(*) FROM applied_actions").fetchone()[0]
            return {
                "absorbed": absorbed,
                "digested": digested,
                "learned": learned,
                "applied": applied
            }
        except:
            return {}
        finally:
            conn.close()

    async def _call_llm(self, prompt: str) -> str:
        import os
        key = os.environ.get("CEREBRAS_API_KEY")
        if key:
            try:
                from cerebras.cloud.sdk import Cerebras
                client = Cerebras(api_key=key)
                resp = client.chat.completions.create(
                    model="llama-3.3-70b",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=800,
                    temperature=0.5
                )
                return resp.choices[0].message.content
            except Exception as e:
                logger.warning(f"LLM error: {e}")
        return "[]"

    def _parse_json_array(self, text: str) -> list:
        if not text:
            return []
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        try:
            result = json.loads(text.strip())
            return result if isinstance(result, list) else [result]
        except:
            start = text.find("[")
            end = text.rfind("]") + 1
            if start >= 0 and end > start:
                try:
                    return json.loads(text[start:end])
                except:
                    pass
        return []


class ArenaBattle:
    """전략 대결."""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or str(
            Path.home() / "reze-agent" / "reze_data" / "ssot.sqlite"
        )
        self.generator = ScenarioGenerator(self.db_path)

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    async def run_battle(self, scenario: dict) -> dict:
        """한 시나리오에서 전략들을 경쟁."""
        strategies = self._get_candidate_strategies()

        if not strategies:
            return {"scenario": scenario, "winner": None, "message": "전략 없음"}

        results = []
        for strategy in strategies[:5]:
            outcome = await self._simulate(scenario, strategy)
            results.append({
                "strategy": strategy,
                "outcome": outcome
            })

        ranked = sorted(results, key=lambda x: x["outcome"].get("score", 0), reverse=True)

        battle_result = {
            "scenario": scenario,
            "winner": ranked[0] if ranked else None,
            "all_results": ranked,
            "battle_at": datetime.now(timezone.utc).isoformat()
        }

        self._store_simulation(battle_result)
        return battle_result

    async def tournament(self, category: str, rounds: int = 5) -> dict:
        """토너먼트."""
        scenarios = await self.generator.generate(category, rounds, depth="shallow")
        results = []
        for s in scenarios:
            battle = await self.run_battle(s)
            results.append(battle)

        winners = [
            r["winner"]["strategy"].get("description", "?")[:30]
            for r in results if r.get("winner")
        ]

        return {
            "category": category,
            "rounds": len(results),
            "winners": winners,
            "tournament_at": datetime.now(timezone.utc).isoformat()
        }

    async def adversarial(self) -> dict:
        """적대적 시뮬레이션 — 최악의 상황."""
        results = []
        for case in ADVERSARIAL_SCENARIOS[:3]:  # 3개만
            scenario = {
                "id": f"adv_{hashlib.md5(case.encode()).hexdigest()[:8]}",
                "situation": case,
                "severity": "black",
                "category": "survival"
            }
            battle = await self.run_battle(scenario)
            results.append(battle)

        return {
            "type": "adversarial",
            "scenarios": len(results),
            "results": results,
            "simulated_at": datetime.now(timezone.utc).isoformat()
        }

    async def counterfactual(self) -> dict:
        """반사실 시뮬레이션 — 다른 선택을 했다면?"""
        conn = self._get_conn()
        try:
            past_actions = conn.execute("""
                SELECT pattern_id, description, action_type, applied_at
                FROM applied_actions
                ORDER BY applied_at DESC LIMIT 3
            """).fetchall()

            results = []
            for action in past_actions:
                a = dict(action)
                scenario = {
                    "id": f"cf_{a['pattern_id'][:8]}",
                    "situation": f"만약 '{a['description'][:30]}' 대신 다른 선택을 했다면?",
                    "severity": "yellow",
                    "category": "evolution",
                    "original": a
                }
                battle = await self.run_battle(scenario)
                results.append(battle)

            return {
                "type": "counterfactual",
                "scenarios": len(results),
                "results": results
            }
        finally:
            conn.close()

    def _get_candidate_strategies(self) -> list:
        """시나리오에 사용할 전략 후보."""
        conn = self._get_conn()
        try:
            strategies = conn.execute("""
                SELECT pattern_id, pattern_type, description,
                       pattern_data, confidence
                FROM learned_patterns
                WHERE apply_status IN ('applied', 'pending')
                ORDER BY confidence DESC
                LIMIT 10
            """).fetchall()
            return [dict(s) for s in strategies]
        except:
            return []
        finally:
            conn.close()

    async def _simulate(self, scenario: dict, strategy: dict) -> dict:
        """시뮬레이션 실행."""
        prompt = BATTLE_PROMPT.format(
            scenario=json.dumps(scenario, ensure_ascii=False),
            strategy=json.dumps({
                "name": strategy.get("description", "")[:50],
                "type": strategy.get("pattern_type", ""),
                "confidence": strategy.get("confidence", 0)
            }, ensure_ascii=False)
        )
        try:
            response = await self.generator._call_llm(prompt)
            # JSON 객체 파싱
            text = response.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            try:
                return json.loads(text.strip())
            except:
                start = text.find("{")
                end = text.rfind("}") + 1
                if start >= 0 and end > start:
                    return json.loads(text[start:end])
        except Exception as e:
            logger.warning(f"Simulation error: {e}")

        return {"score": 0.5, "outcome": "시뮬레이션 실패", "confidence": 0.0}

    def _store_simulation(self, battle: dict):
        """시뮬레이션 결과 저장."""
        conn = self._get_conn()
        try:
            scenario = battle.get("scenario", {})
            sim_id = f"sim_{hashlib.md5(json.dumps(scenario).encode()).hexdigest()[:10]}"
            sim_type = "adversarial" if scenario.get("severity") == "black" else "normal"

            winner = battle.get("winner")
            conn.execute("""
                INSERT OR IGNORE INTO simulation_log
                (simulation_id, category, scenario, strategies_tested,
                 winner_strategy, winner_score, all_results,
                 simulation_type, simulated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                sim_id,
                scenario.get("category", "general"),
                json.dumps(scenario, ensure_ascii=False),
                json.dumps([
                    r["strategy"].get("description", "?")[:30]
                    for r in battle.get("all_results", [])
                ], ensure_ascii=False),
                winner["strategy"].get("description", "?")[:50] if winner else None,
                winner["outcome"].get("score", 0) if winner else 0,
                json.dumps(battle.get("all_results", []), ensure_ascii=False),
                sim_type,
                datetime.now(timezone.utc).isoformat()
            ))
            conn.commit()
        except Exception as e:
            logger.warning(f"Simulation store error: {e}")
        finally:
            conn.close()


class DreamSynthesis:
    """꿈 학습 — 하루 경험 통합."""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or str(
            Path.home() / "reze-agent" / "reze_data" / "ssot.sqlite"
        )

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    async def dream(self) -> dict:
        """매일 새벽 꿈."""
        conn = self._get_conn()
        start = time.time()

        try:
            # 최근 소화된 경험
            recent_insights = conn.execute("""
                SELECT insight_type, summary, combined_score
                FROM digested_insights
                ORDER BY created_at DESC
                LIMIT 30
            """).fetchall()

            # 현재 활성 전략
            active_strategies = conn.execute("""
                SELECT pattern_type, description, confidence
                FROM learned_patterns
                WHERE apply_status = 'applied'
            """).fetchall()

            if not recent_insights:
                return {"insights": 0, "message": "꿈 꿀 경험 없음"}

            prompt = DREAM_PROMPT.format(
                experiences=json.dumps([dict(e) for e in recent_insights], ensure_ascii=False),
                current_strategies=json.dumps([dict(s) for s in active_strategies], ensure_ascii=False)
            )

            generator = ScenarioGenerator(self.db_path)
            response = await generator._call_llm(prompt)

            # JSON 파싱
            text = response.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            try:
                dream_result = json.loads(text.strip())
            except:
                start_idx = text.find("{")
                end_idx = text.rfind("}") + 1
                if start_idx >= 0 and end_idx > start_idx:
                    dream_result = json.loads(text[start_idx:end_idx])
                else:
                    dream_result = {"insights": [], "contradictions": [], "strategy_adjustments": []}

            # 꿈 기록 저장
            dream_id = f"dream_{datetime.now().strftime('%Y%m%d_%H%M')}"
            insights = dream_result.get("insights", [])

            conn.execute("""
                INSERT OR IGNORE INTO dream_log
                (dream_id, dream_type, experiences_processed,
                 insights_generated, cross_patterns, contradictions,
                 strategy_adjustments, dreamed_at)
                VALUES (?, 'regular', ?, ?, ?, ?, ?, ?)
            """, (
                dream_id,
                len(recent_insights),
                len(insights),
                json.dumps(insights, ensure_ascii=False),
                json.dumps(dream_result.get("contradictions", []), ensure_ascii=False),
                json.dumps(dream_result.get("strategy_adjustments", []), ensure_ascii=False),
                datetime.now(timezone.utc).isoformat()
            ))

            conn.commit()

            result = {
                "dream_id": dream_id,
                "insights": len(insights),
                "contradictions": len(dream_result.get("contradictions", [])),
                "adjustments": len(dream_result.get("strategy_adjustments", [])),
                "duration_sec": time.time() - start
            }
            logger.info(f"[Dream] {result['insights']} insights, {result['contradictions']} contradictions")
            return result

        finally:
            conn.close()

    def get_recent_dreams(self, limit: int = 5) -> List[dict]:
        """최근 꿈 조회."""
        conn = self._get_conn()
        try:
            dreams = conn.execute("""
                SELECT dream_id, dream_type, experiences_processed,
                       insights_generated, dreamed_at
                FROM dream_log
                ORDER BY dreamed_at DESC
                LIMIT ?
            """, (limit,)).fetchall()
            return [dict(d) for d in dreams]
        finally:
            conn.close()
