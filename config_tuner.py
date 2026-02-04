"""
REZE v5.0 Phase 4 — ConfigTuner
Phase 3의 실측 데이터를 분석하여 config.py 값을 자율적으로 조정.

학술 근거:
- DGM 패턴: 변경 → 경험적 검증 → 개선시 보관, 악화시 폐기
- Supervised Autonomy: SAFE=자동, RISKY/DANGEROUS=보스 승인
"""

import json
import logging
from datetime import datetime, timedelta

import config

logger = logging.getLogger("reze.config_tuner")

# ── 위험도 분류 규칙 ──
# SAFE: 타이밍/간격 조정 (서비스 영향 없음)
# RISKY: 동시성/재시도 변경 (서비스에 간접 영향)
# DANGEROUS: 새 도구/워크플로우 추가 (시스템 구조 변경)
RISK_MAP = {
    "DISCOVERY_INTERVAL_MINUTES": "SAFE",
    "FEEDBACK_CHECK_INTERVAL_HOURS": "SAFE",
    "JUDGMENT_INTERVAL_HOURS": "SAFE",
    "TASK_PROCESSOR_INTERVAL_MINUTES": "SAFE",
    "WORKER_MAX_CONCURRENT": "RISKY",
    "PLANNER_MAX_REPLANS": "RISKY",
    "PLANNER_MAX_STEPS": "RISKY",
}


class ConfigTuner:
    def __init__(self, ssot, llm_fn):
        """
        ssot: SSOT 인스턴스
        llm_fn: async callable, LLM 호출 함수 (str → str)
        """
        self.ssot = ssot
        self.llm_fn = llm_fn

    # ── 1. OBSERVE: 데이터 수집 ──

    def observe(self, days: int = 7) -> dict:
        """최근 N일간의 운영 데이터를 수집하여 분석 가능한 형태로 반환."""
        since = (datetime.now() - timedelta(days=days)).isoformat()

        # feedback_queue에서 태스크 성공률/실패율
        feedback_stats = self.ssot.conn.execute("""
            SELECT task_type, status, COUNT(*)
            FROM feedback_queue WHERE created_at >= ?
            GROUP BY task_type, status
        """, (since,)).fetchall()

        # tool_log에서 도구별 실행시간/성공률
        tool_stats = self.ssot.conn.execute("""
            SELECT tool AS tool_name,
                   COUNT(*) as calls,
                   AVG(duration_ms) as avg_ms,
                   SUM(CASE WHEN success=1 THEN 1 ELSE 0 END) as successes
            FROM tool_log WHERE created_at >= ?
            GROUP BY tool
        """, (since,)).fetchall()

        # plan_cache_v4에서 플랜 성공률 분포
        plan_stats = self.ssot.conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN score IS NULL THEN 1 ELSE 0 END) as unverified,
                SUM(CASE WHEN score >= 0.8 THEN 1 ELSE 0 END) as good,
                SUM(CASE WHEN score >= 0.5 AND score < 0.8 THEN 1 ELSE 0 END) as mediocre,
                SUM(CASE WHEN score < 0.5 AND score IS NOT NULL THEN 1 ELSE 0 END) as bad
            FROM plan_cache_v4
        """).fetchone()

        # 현재 config 값들
        current_config = {}
        for key in RISK_MAP:
            current_config[key] = getattr(config, key, "NOT_FOUND")

        # config 변경 이력 (효과 추적용)
        change_history = self.ssot.get_config_change_history(limit=10)

        return {
            "period_days": days,
            "feedback_stats": [{"type": r[0], "status": r[1], "count": r[2]} for r in feedback_stats],
            "tool_stats": [{"tool": r[0], "calls": r[1], "avg_ms": r[2], "successes": r[3]} for r in tool_stats],
            "plan_stats": {
                "total": plan_stats[0], "unverified": plan_stats[1],
                "good": plan_stats[2], "mediocre": plan_stats[3], "bad": plan_stats[4]
            } if plan_stats else {},
            "current_config": current_config,
            "recent_changes": change_history
        }

    # ── 2. ANALYZE: LLM 기반 분석 + 제안 ──

    async def analyze(self, observation: dict) -> list[dict]:
        """운영 데이터를 LLM에게 분석시키고 config 조정 제안을 받는다."""
        prompt = f"""You are REZE's ConfigTuner. Analyze the operational data and suggest config changes.

CURRENT CONFIG:
{json.dumps(observation['current_config'], indent=2)}

FEEDBACK STATS (last {observation['period_days']} days):
{json.dumps(observation['feedback_stats'], indent=2)}

TOOL STATS:
{json.dumps(observation['tool_stats'], indent=2)}

PLAN CACHE STATS:
{json.dumps(observation['plan_stats'], indent=2)}

RECENT CONFIG CHANGES:
{json.dumps(observation['recent_changes'][:5], indent=2, default=str)}

RULES:
- Only suggest changes if data clearly supports them
- If data is insufficient (< 10 data points for a metric), say "insufficient data"
- Each suggestion must include: config_key, current_value, proposed_value, reason
- Reason must reference specific numbers from the data
- Do NOT suggest changes just for the sake of changing

Respond ONLY in JSON array format:
[
  {{"config_key": "KEY", "current_value": "X", "proposed_value": "Y", "reason": "Because data shows..."}},
  ...
]

If no changes needed, respond: []"""

        try:
            response = await self.llm_fn(prompt)
            # JSON 파싱 (```json 등 제거)
            cleaned = response.strip() if isinstance(response, str) else str(response).strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
            suggestions = json.loads(cleaned)
            if not isinstance(suggestions, list):
                return []
            return suggestions
        except (json.JSONDecodeError, Exception) as e:
            logger.error(f"ConfigTuner analyze failed: {e}")
            return []

    # ── 3. CLASSIFY + PROPOSE ──

    def classify_and_propose(self, suggestions: list[dict]) -> list[int]:
        """제안을 위험도별로 분류하고 DB에 기록. change_id 리스트 반환."""
        change_ids = []
        for s in suggestions:
            key = s.get("config_key", "")
            if key not in RISK_MAP:
                logger.warning(f"Unknown config key: {key}, skipping")
                continue

            risk = RISK_MAP[key]
            old_val = str(s.get("current_value", ""))
            new_val = str(s.get("proposed_value", ""))
            reason = s.get("reason", "No reason provided")

            # 값이 같으면 스킵
            if old_val == new_val:
                continue

            change_id = self.ssot.propose_config_change(
                config_key=key, old_value=old_val, new_value=new_val,
                reason=reason, risk_level=risk
            )
            change_ids.append(change_id)
            logger.info(f"Config proposal #{change_id}: {key} {old_val}→{new_val} [{risk}]")

        return change_ids

    # ── 4. APPLY: config.py 런타임 업데이트 ──

    def apply_change(self, change_id: int) -> bool:
        """승인된 변경을 config 모듈에 런타임 적용.

        주의: config.py 파일 자체를 수정하지 않음.
        setattr(config, key, value)로 런타임 값만 변경.
        데몬 재시작 시 config.py 원본 값으로 복원됨.
        영구 적용은 Phase 5 Discord 워크플로우에서 보스가 직접 수행.
        """
        row = self.ssot.conn.execute("""
            SELECT config_key, new_value, status
            FROM config_change_log WHERE id = ?
        """, (change_id,)).fetchone()

        if not row:
            return False

        key, new_val, status = row
        if status not in ('applied', 'approved'):
            logger.warning(f"Change #{change_id} status={status}, cannot apply")
            return False

        # 현재 값 기록 (before_metric)
        current = getattr(config, key, None)
        if current is None:
            logger.error(f"Config key {key} not found in config module")
            return False

        # 타입 변환
        try:
            typed_val = type(current)(new_val)
        except (ValueError, TypeError):
            logger.error(f"Cannot convert {new_val} to {type(current).__name__}")
            return False

        # 런타임 적용
        setattr(config, key, typed_val)
        logger.info(f"Config applied: {key} = {typed_val} (was {current})")

        # before_metric 기록
        self.ssot.update_config_metrics(change_id, str(current), "")

        return True

    # ── 5. MEASURE: before/after 비교 ──

    async def measure_effect(self, change_id: int, wait_hours: int = 24) -> dict | None:
        """변경 적용 후 효과를 측정. wait_hours 후에 호출해야 의미 있음.

        이 메서드는 다음 config_tuner_job 실행 시
        이전 사이클에서 적용된 변경의 효과를 확인.
        """
        row = self.ssot.conn.execute("""
            SELECT config_key, old_value, new_value, applied_at, before_metric
            FROM config_change_log
            WHERE id = ? AND status IN ('applied', 'approved')
        """, (change_id,)).fetchone()

        if not row:
            return None

        key, old_val, new_val, applied_at, before_metric = row

        # 적용 후 충분한 시간이 지났는지 확인
        if applied_at:
            applied_time = datetime.fromisoformat(applied_at)
            if datetime.now() - applied_time < timedelta(hours=wait_hours):
                return {"status": "too_early", "wait_until": (applied_time + timedelta(hours=wait_hours)).isoformat()}

        # 현재 메트릭 수집 (변경 후)
        current_observation = self.observe(days=1)
        after_metric = json.dumps({
            "feedback_summary": len(current_observation['feedback_stats']),
            "tool_calls": sum(s['calls'] for s in current_observation['tool_stats']),
        })

        self.ssot.update_config_metrics(change_id, before_metric or "", after_metric)

        return {
            "change_id": change_id,
            "key": key,
            "old": old_val,
            "new": new_val,
            "before": before_metric,
            "after": after_metric
        }

    # ── 6. ROLLBACK: 악화 시 복원 ──

    def rollback(self, change_id: int) -> bool:
        """변경을 롤백하고 config를 원래 값으로 복원."""
        result = self.ssot.rollback_config_change(change_id)
        if not result:
            return False

        key = result["config_key"]
        old_val = result["old_value"]
        current_type = type(getattr(config, key, ""))

        try:
            typed_val = current_type(old_val)
            setattr(config, key, typed_val)
            logger.info(f"Config rolled back: {key} = {typed_val}")
            return True
        except (ValueError, TypeError) as e:
            logger.error(f"Rollback type conversion failed: {e}")
            return False

    # ── 메인 실행 루프 ──

    async def run_cycle(self) -> dict:
        """ConfigTuner 1사이클 실행. 주 1회 호출."""
        logger.info("=== ConfigTuner cycle start ===")

        # 1. 데이터 수집
        observation = self.observe(days=7)
        total_data = sum(s.get('count', 0) for s in observation['feedback_stats'])

        if total_data < 10:
            logger.info(f"Insufficient data ({total_data} records). Skipping analysis.")
            return {"status": "skipped", "reason": "insufficient_data", "data_points": total_data}

        # 2. LLM 분석
        suggestions = await self.analyze(observation)
        if not suggestions:
            logger.info("No config changes suggested.")
            return {"status": "no_changes", "data_points": total_data}

        # 3. 분류 + 제안 등록
        change_ids = self.classify_and_propose(suggestions)

        # 4. SAFE 변경은 즉시 적용
        applied = []
        pending = []
        for cid in change_ids:
            row = self.ssot.conn.execute(
                "SELECT risk_level, status FROM config_change_log WHERE id = ?", (cid,)
            ).fetchone()
            if row and row[1] == 'applied':  # SAFE → 이미 status='applied'
                self.apply_change(cid)
                applied.append(cid)
            else:
                pending.append(cid)

        result = {
            "status": "completed",
            "data_points": total_data,
            "suggestions": len(suggestions),
            "applied_safe": applied,
            "pending_approval": pending
        }

        if pending:
            logger.info(f"⚠️ {len(pending)} config changes need boss approval!")
            # Phase 5에서 Discord 알림 추가 예정

        logger.info(f"=== ConfigTuner cycle done: {result} ===")
        return result
