"""
Phase 5 Wave 2: PREDATOR Strategy Verifier
REZE v6.0 SOVEREIGN - Stage 5: 검증 (Verify)

적용한 전략의 결과를 추적하고 피드백 루프를 만든다.
"""

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger("reze.predator.verifier")


VERIFICATION_PROMPT = """너는 REZE의 검증 시스템이다.
적용된 전략의 효과를 판정하라.

전략: {description}
유형: {action_type}
대상: {target}
적용 후 {days}일 경과

판정:
1. verdict: "positive" | "neutral" | "negative"
   - 적용 후 개선되었으면 positive
   - 변화 없으면 neutral
   - 악화되었으면 negative
2. impact_score: -1.0 ~ 1.0 (0 = 변화없음)
3. explanation: 판정 이유 (50자 이내)
4. recommendation: "keep" | "rollback" | "modify" | "extend"

반드시 JSON만 응답:
{{"verdict": "...", "impact_score": 0.0, "explanation": "...", "recommendation": "..."}}"""


@dataclass
class VerifyResult:
    """검증 결과."""
    verified: int = 0
    positive: int = 0
    neutral: int = 0
    negative: int = 0
    rollbacks: int = 0
    duration_sec: float = 0.0
    details: List[dict] = field(default_factory=list)


class StrategyVerifier:
    """적용된 전략의 효과를 검증."""

    CHECKPOINTS = {
        "1day": 1,
        "3day": 3,
        "7day": 7,
        "30day": 30
    }

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

    async def verify_all(self) -> VerifyResult:
        """적용된 전략들의 체크포인트 검증."""
        import time
        start = time.time()
        conn = self._get_conn()
        result = VerifyResult()

        try:
            # applied_actions에서 검증 대기 중인 액션 조회
            applied = conn.execute("""
                SELECT a.action_id, a.pattern_id, a.action_type,
                       a.target, a.description, a.applied_at, a.payload
                FROM applied_actions a
                WHERE a.verify_status = 'pending'
            """).fetchall()

            if not applied:
                result.duration_sec = time.time() - start
                return result

            now = datetime.now(timezone.utc)

            for action in applied:
                a = dict(action)
                try:
                    applied_at_str = a.get("applied_at", "")
                    if applied_at_str:
                        if applied_at_str.endswith("Z"):
                            applied_at_str = applied_at_str[:-1] + "+00:00"
                        elif "+" not in applied_at_str and "-" not in applied_at_str[-6:]:
                            applied_at_str += "+00:00"
                        applied_at = datetime.fromisoformat(applied_at_str)
                    else:
                        continue
                except Exception as e:
                    logger.warning(f"Date parse error: {e}")
                    continue

                days_since = (now - applied_at).days

                for cp_name, cp_days in self.CHECKPOINTS.items():
                    if days_since >= cp_days:
                        already = conn.execute("""
                            SELECT 1 FROM verified_results
                            WHERE action_id = ? AND metrics LIKE ?
                        """, (a["action_id"], f'%"checkpoint":"{cp_name}"%')).fetchone()

                        if not already:
                            v = await self._verify_checkpoint(conn, a, cp_name, days_since)
                            if v:
                                result.verified += 1
                                if v["verdict"] == "positive":
                                    result.positive += 1
                                elif v["verdict"] == "negative":
                                    result.negative += 1
                                    if v.get("recommendation") == "rollback":
                                        await self._handle_rollback(conn, a, v)
                                        result.rollbacks += 1
                                else:
                                    result.neutral += 1
                                result.details.append(v)

            conn.commit()
            result.duration_sec = time.time() - start

            logger.info(
                f"[Verify] {result.verified} checked: "
                f"+{result.positive} ={result.neutral} -{result.negative}"
            )
            return result

        finally:
            conn.close()

    async def _verify_checkpoint(self, conn, action: dict,
                                  checkpoint: str, days: int) -> Optional[dict]:
        """특정 체크포인트 검증."""
        prompt = VERIFICATION_PROMPT.format(
            description=action.get("description", "unknown")[:100],
            action_type=action.get("action_type", "none"),
            target=action.get("target", "unknown"),
            days=days
        )

        try:
            response = await self._call_llm(prompt)
            judgment = self._parse_json(response)

            if not judgment:
                return None

            verdict = judgment.get("verdict", "neutral")
            impact = float(judgment.get("impact_score", 0.0))
            explanation = judgment.get("explanation", "")
            recommendation = judgment.get("recommendation", "keep")

            # verified_results에 저장
            now = datetime.now(timezone.utc).isoformat()
            verify_id = f"ver_{uuid.uuid4().hex[:12]}"

            conn.execute("""
                INSERT INTO verified_results
                (verify_id, action_id, pattern_id, success, metrics,
                 feedback, verified_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                verify_id,
                action["action_id"],
                action["pattern_id"],
                1 if verdict == "positive" else 0,
                json.dumps({
                    "checkpoint": checkpoint,
                    "days_since": days,
                    "verdict": verdict,
                    "impact_score": impact,
                    "recommendation": recommendation
                }),
                explanation,
                now, now
            ))

            # 검증 완료된 action 상태 업데이트
            if checkpoint == "7day" or verdict in ["positive", "negative"]:
                conn.execute("""
                    UPDATE applied_actions
                    SET verify_status = 'verified'
                    WHERE action_id = ?
                """, (action["action_id"],))

            return {
                "action_id": action["action_id"],
                "description": action.get("description", "")[:50],
                "checkpoint": checkpoint,
                "verdict": verdict,
                "impact": impact,
                "explanation": explanation,
                "recommendation": recommendation
            }

        except Exception as e:
            logger.warning(f"Verify failed {action['action_id']}: {e}")
            return None

    async def _handle_rollback(self, conn, action: dict, judgment: dict):
        """부정적 결과 → 롤백."""
        logger.warning(
            f"[Verify] Rollback needed: {action['description'][:50]} "
            f"(impact={judgment.get('impact', 0):.2f})"
        )
        conn.execute("""
            UPDATE learned_patterns SET
                apply_status = 'rolled_back',
                last_reinforced_at = ?
            WHERE pattern_id = ?
        """, (datetime.now(timezone.utc).isoformat(), action["pattern_id"]))

    async def _call_llm(self, prompt: str) -> str:
        """LLM 호출."""
        if self.llm_router:
            try:
                result = await self.llm_router.call("verify", prompt, temperature=0.2)
                return result.get("content", "")
            except Exception as e:
                logger.warning(f"Router error: {e}")

        import os
        cerebras_key = os.environ.get("CEREBRAS_API_KEY")
        if cerebras_key:
            try:
                from cerebras.cloud.sdk import Cerebras
                client = Cerebras(api_key=cerebras_key)
                resp = client.chat.completions.create(
                    model="llama-3.3-70b",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=300,
                    temperature=0.2
                )
                return resp.choices[0].message.content
            except Exception as e:
                logger.warning(f"Cerebras error: {e}")

        raise RuntimeError("No LLM available")

    def _parse_json(self, text: str) -> Optional[dict]:
        if not text:
            return None
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        try:
            return json.loads(text.strip())
        except:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    return json.loads(text[start:end])
                except:
                    pass
        return None

    async def verify_batch(self) -> Dict[str, Any]:
        """배치 검증 (편의 메서드)."""
        result = await self.verify_all()
        return {
            "verified": result.verified,
            "positive": result.positive,
            "neutral": result.neutral,
            "negative": result.negative,
            "rollbacks": result.rollbacks,
            "details": result.details,
            "duration_sec": result.duration_sec
        }

    def get_verification_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """검증 이력."""
        conn = self._get_conn()
        cursor = conn.execute("""
            SELECT verify_id, action_id, pattern_id, success,
                   metrics, feedback, verified_at
            FROM verified_results
            ORDER BY verified_at DESC
            LIMIT ?
        """, (limit,))
        results = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return results

    def get_stats(self) -> Dict[str, Any]:
        """검증 통계."""
        conn = self._get_conn()

        stats = conn.execute("""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as positive,
                   SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as negative
            FROM verified_results
        """).fetchone()

        conn.close()

        return {
            "total_verified": stats["total"] or 0,
            "positive": stats["positive"] or 0,
            "negative": stats["negative"] or 0,
            "success_rate": round(
                (stats["positive"] or 0) / max(stats["total"] or 1, 1) * 100, 1
            )
        }
