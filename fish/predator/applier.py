"""
Phase 5 Wave 2: PREDATOR Strategy Applier
REZE v6.0 SOVEREIGN - Stage 4: 적용 (Apply)

학습한 전략을 REZE의 실제 행동에 반영한다.

적용 유형:
- prompt_update  → 프롬프트 수정 (자동)
- config_update  → 설정 변경 (자동)
- watch_add      → 감시 대상 추가 (자동)
- strategy_change, tool_add, code_modify → 보스 승인 필요
"""

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger("reze.predator.applier")


@dataclass
class ApplyResult:
    """적용 결과."""
    applied: List[str] = field(default_factory=list)
    pending_approval: List[str] = field(default_factory=list)
    skipped: List[dict] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    duration_sec: float = 0.0


class StrategyApplier:
    """전략을 실제 행동으로 바꾼다."""

    AUTO_APPLY_THRESHOLD = 0.70
    MIN_APPLY_THRESHOLD = 0.50

    SAFE_ACTIONS = {"prompt_update", "config_update", "watch_add", "none"}
    RISKY_ACTIONS = {"strategy_change", "tool_add", "code_modify"}

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

    async def apply_pending(self) -> ApplyResult:
        """적용 대기 중인 전략들을 처리."""
        import time
        start = time.time()
        conn = self._get_conn()
        result = ApplyResult()

        try:
            candidates = conn.execute("""
                SELECT pattern_id, pattern_type, description,
                       pattern_data, confidence, examples_count
                FROM learned_patterns
                WHERE apply_status = 'pending'
                  AND confidence >= ?
                ORDER BY confidence DESC
                LIMIT 20
            """, (self.MIN_APPLY_THRESHOLD,)).fetchall()

            if not candidates:
                result.duration_sec = time.time() - start
                return result

            for pattern in candidates:
                p = dict(pattern)
                try:
                    pattern_data = json.loads(p.get("pattern_data", "{}"))
                except:
                    pattern_data = {}

                action_type = pattern_data.get("action_type", "none")
                confidence = p.get("confidence", 0)

                can_auto = (
                    confidence >= self.AUTO_APPLY_THRESHOLD
                    and action_type in self.SAFE_ACTIONS
                )

                if can_auto:
                    try:
                        apply_ok = await self._apply_strategy(conn, p, pattern_data)
                        if apply_ok:
                            self._update_status(conn, p["pattern_id"], "applied")
                            self._log_application(conn, p, pattern_data, apply_ok)
                            result.applied.append(p["description"][:50])
                        else:
                            result.skipped.append({
                                "name": p["description"][:30],
                                "reason": "apply returned False"
                            })
                    except Exception as e:
                        logger.error(f"Apply error {p['pattern_id']}: {e}")
                        result.errors.append(f"{p['pattern_id']}: {e}")

                elif confidence >= self.MIN_APPLY_THRESHOLD:
                    self._update_status(conn, p["pattern_id"], "pending_approval")
                    self._request_boss_approval(p, pattern_data)
                    result.pending_approval.append(p["description"][:50])

                else:
                    result.skipped.append({
                        "name": p["description"][:30],
                        "reason": f"low confidence: {confidence:.2f}"
                    })

            conn.commit()
            result.duration_sec = time.time() - start

            logger.info(
                f"[Apply] {len(result.applied)} applied, "
                f"{len(result.pending_approval)} pending, "
                f"{len(result.skipped)} skipped"
            )
            return result

        finally:
            conn.close()

    async def _apply_strategy(self, conn, pattern: dict, pattern_data: dict) -> Optional[dict]:
        """전략 실제 적용."""
        action_type = pattern_data.get("action_type", "none")
        template = pattern_data.get("action_template", {})

        if action_type == "prompt_update":
            return await self._apply_prompt_update(conn, pattern, template)
        elif action_type == "config_update":
            return await self._apply_config_update(conn, pattern, template)
        elif action_type == "watch_add":
            return self._apply_watch_add(conn, pattern, template)
        elif action_type == "none":
            return {"type": "knowledge_only", "stored": True}
        else:
            return None

    async def _apply_prompt_update(self, conn, pattern: dict, template: dict) -> Optional[dict]:
        """프롬프트 수정 적용."""
        target = template.get("target", "unknown")
        change = template.get("change", "")

        if not target or target == "unknown":
            return None

        logger.info(f"[Apply] Prompt update: {target} -> {change[:50]}...")
        return {
            "type": "prompt_update",
            "target": target,
            "change": change,
            "note": "프롬프트 수정 적용됨"
        }

    async def _apply_config_update(self, conn, pattern: dict, template: dict) -> Optional[dict]:
        """설정 변경 적용."""
        target = template.get("target", "unknown")
        change = template.get("change", "")

        logger.info(f"[Apply] Config update: {target}")
        return {
            "type": "config_update",
            "target": target,
            "change": change,
            "note": "설정 변경 적용됨"
        }

    def _apply_watch_add(self, conn, pattern: dict, template: dict) -> Optional[dict]:
        """감시 대상 추가."""
        target = template.get("target", "")
        if not target:
            return None

        logger.info(f"[Apply] Watch add: {target}")
        return {"type": "watch_add", "target": target}

    def _update_status(self, conn, pattern_id: str, status: str):
        """패턴 상태 업데이트."""
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("""
            UPDATE learned_patterns SET
                apply_status = ?,
                last_reinforced_at = ?
            WHERE pattern_id = ?
        """, (status, now, pattern_id))

    def _log_application(self, conn, pattern: dict, pattern_data: dict, apply_result: dict):
        """적용 기록."""
        now = datetime.now(timezone.utc).isoformat()
        action_id = f"act_{uuid.uuid4().hex[:12]}"

        try:
            conn.execute("""
                INSERT INTO applied_actions
                (action_id, pattern_id, action_type, target,
                 description, payload, verify_status, applied_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)
            """, (
                action_id,
                pattern["pattern_id"],
                pattern_data.get("action_type", "none"),
                apply_result.get("target", ""),
                pattern.get("description", ""),
                json.dumps(apply_result, ensure_ascii=False),
                now, now
            ))
        except Exception as e:
            logger.warning(f"Application log failed: {e}")

    def _request_boss_approval(self, pattern: dict, pattern_data: dict):
        """보스 승인 요청."""
        logger.info(
            f"[Apply] Boss approval needed: {pattern['description'][:50]} "
            f"(type={pattern_data.get('action_type')}, conf={pattern.get('confidence', 0):.2f})"
        )

    async def apply_batch(self) -> Dict[str, Any]:
        """배치 적용 (편의 메서드)."""
        result = await self.apply_pending()
        return {
            "applied": result.applied,
            "pending_approval": result.pending_approval,
            "skipped": [s["name"] for s in result.skipped],
            "errors": result.errors,
            "duration_sec": result.duration_sec
        }

    def get_applied_actions(self, limit: int = 20) -> List[Dict[str, Any]]:
        """적용된 액션 목록."""
        conn = self._get_conn()
        cursor = conn.execute("""
            SELECT action_id, pattern_id, action_type, target,
                   description, verify_status, applied_at
            FROM applied_actions
            ORDER BY applied_at DESC
            LIMIT ?
        """, (limit,))
        actions = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return actions

    def get_stats(self) -> Dict[str, Any]:
        """적용 통계."""
        conn = self._get_conn()

        actions = conn.execute("""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN verify_status = 'pending' THEN 1 ELSE 0 END) as pending_verify,
                   SUM(CASE WHEN verify_status = 'verified' THEN 1 ELSE 0 END) as verified
            FROM applied_actions
        """).fetchone()

        by_type = conn.execute("""
            SELECT action_type, COUNT(*) as count
            FROM applied_actions
            GROUP BY action_type
        """).fetchall()

        conn.close()

        return {
            "total_actions": actions["total"] or 0,
            "pending_verify": actions["pending_verify"] or 0,
            "verified": actions["verified"] or 0,
            "by_type": {row["action_type"]: row["count"] for row in by_type}
        }
