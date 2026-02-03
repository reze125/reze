"""
REZE v5.0 — Feedback Engine
원칙: 모르면 모른다. 실측만 저장.
"""

import json
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("REZE.feedback")


class FeedbackEngine:

    def __init__(self, ssot, tools):
        self.ssot = ssot
        self.tools = tools

    def register(self, task_id: str, task_type: str, result: dict,
                 metadata: dict = None):
        """태스크 완료 직후: 실측 즉시 점수 + 지연 체크 등록."""
        meta = metadata or {}

        # 즉시 점수 — 실측값 직빵
        score = self._measure_immediate(result)

        # plan_cache 점수 업데이트 (실측 직빵, EMA 아님)
        if meta.get("task_spec") and score is not None:
            self.ssot.update_plan_score(meta["task_spec"], score)

        # 지연 체크 등록
        checks = self._determine_checks(task_type, result, meta)
        for check in checks:
            self.ssot.enqueue_feedback(
                task_id=task_id, task_type=task_type,
                phase=check["phase"],
                check_after=(datetime.now() + check["delay"]).isoformat(),
                check_method=check["method"],
                check_input=json.dumps(check["input"], ensure_ascii=False),
                metadata=meta
            )

        logger.info(f"Feedback: {task_id} score={score}, {len(checks)} delayed checks")
        return score

    async def process_due(self) -> list:
        """큐에서 due된 체크 실행."""
        due = self.ssot.get_due_feedback()
        results = []

        for fb in due:
            try:
                score = await self._execute_check(fb)
                self.ssot.complete_feedback(fb["id"], score)

                # plan_cache도 업데이트
                meta = json.loads(fb.get("metadata", "{}"))
                if meta.get("task_spec") and score is not None:
                    self.ssot.update_plan_score(meta["task_spec"], score)

                results.append({
                    "id": fb["id"], "task_id": fb["task_id"],
                    "phase": fb["phase"], "score": score
                })
            except Exception as e:
                logger.error(f"Feedback check {fb['id']} failed: {e}")
                # 측정 불가 = 점수 안 매김 (NULL 유지가 맞지만 complete는 해야 함)
                self.ssot.complete_feedback(fb["id"], None)

        return results

    def _measure_immediate(self, result: dict) -> float | None:
        """즉시 실측: 결과에서 직접 측정."""

        # Planner 결과 (steps 있음)
        if "steps_total" in result:
            total = result["steps_total"]
            success = result["steps_success"]
            if total == 0:
                return 0.0
            return success / total  # 그냥 성공률. 가중치 없음.

        # ReAct 결과
        status = result.get("status", "")
        if status == "success":
            return 1.0
        elif status == "partial":
            return 0.5
        elif status == "failed":
            return 0.0

        return None  # 측정 불가

    def _determine_checks(self, task_type, result, meta) -> list:
        """태스크 유형별 지연 체크 결정."""
        checks = []

        if task_type in ("recovery", "infra"):
            health_check = meta.get("health_check", "")
            if health_check:
                checks.append({
                    "phase": "1h", "delay": timedelta(hours=1),
                    "method": "health_check",
                    "input": {"command": health_check, "service": meta.get("service_name", "")}
                })
                checks.append({
                    "phase": "24h", "delay": timedelta(hours=24),
                    "method": "health_check",
                    "input": {"command": health_check, "service": meta.get("service_name", "")}
                })

        elif task_type in ("content", "development"):
            url = meta.get("url", "")
            if url:
                checks.append({
                    "phase": "1h", "delay": timedelta(hours=1),
                    "method": "url_check",
                    "input": {"url": url}
                })

        elif task_type == "monitoring":
            svc = meta.get("service_name", "")
            if svc:
                checks.append({
                    "phase": "6h", "delay": timedelta(hours=6),
                    "method": "stability_check",
                    "input": {"service": svc}
                })

        # 아무것도 해당 안 되면 체크 없음
        # "모르면 모른다" — 억지로 generic_check 안 함

        return checks

    async def _execute_check(self, fb) -> float | None:
        """실제 체크 실행."""
        method = fb.get("check_method", "")
        inp = json.loads(fb.get("check_input", "{}"))

        if method == "health_check":
            cmd = inp.get("command", "")
            if not cmd:
                return None  # 체크 방법 없음 = 측정 불가
            result = await self.tools.execute("shell", cmd, "feedback")
            if "error" in result.lower() or "stopped" in result.lower() or "not found" in result.lower():
                return 0.0
            return 1.0

        elif method == "url_check":
            url = inp.get("url", "")
            if not url:
                return None
            result = await self.tools.execute("http", url, "feedback")
            return 1.0 if "200" in str(result) else 0.0

        elif method == "stability_check":
            svc = inp.get("service", "")
            if not svc:
                return None
            result = await self.tools.execute(
                "shell",
                f"pm2 describe {svc} 2>/dev/null | grep -c 'restart' || docker logs {svc} --tail 50 2>/dev/null | grep -ci 'error'",
                "feedback"
            )
            try:
                errors = int(result.strip().split("\n")[0])
                if errors == 0:
                    return 1.0
                elif errors < 5:
                    return 0.5
                else:
                    return 0.0
            except:
                return None

        return None  # 알 수 없는 method = 측정 불가

    def summary(self, days=30) -> dict:
        """학습 요약."""
        return {
            "period_days": days,
            "stats": self.ssot.get_feedback_stats(days)
        }
