"""REZE v5.0 — Universal Planner + Executor."""

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from typing import Any

logger = logging.getLogger("REZE.planner")


@dataclass
class PlanStep:
    id: int
    action: str
    tool: str
    input: Any
    expect: str = ""
    on_fail: str = ""
    result: str = ""
    status: str = "pending"


@dataclass
class ExecutionPlan:
    goal: str
    task_type: str = "other"
    steps: list = field(default_factory=list)
    verify: dict = field(default_factory=dict)
    status: str = "created"
    replans: int = 0

    @classmethod
    def from_json(cls, text):
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        data = json.loads(text.strip())
        steps = [
            PlanStep(
                id=s.get("id", i + 1),
                action=s.get("action", ""),
                tool=s.get("tool", "shell"),
                input=s.get("input", ""),
                expect=s.get("expect", ""),
                on_fail=s.get("on_fail", "")
            )
            for i, s in enumerate(data.get("steps", []))
        ]
        return cls(
            goal=data.get("goal", ""),
            task_type=data.get("task_type", "other"),
            steps=steps,
            verify=data.get("verify", {})
        )

    def to_json(self):
        return json.dumps(asdict(self), ensure_ascii=False, default=str)


class UniversalPlanner:
    """태스크 → 단계별 계획 생성 (LLM)."""

    MAX_REPLANS = 2

    def __init__(self, ssot, tools, call_llm_fn):
        self.ssot = ssot
        self.tools = tools
        self.llm = call_llm_fn

    async def plan(self, task, context=None):
        """태스크에 대한 실행 계획 생성."""
        services = self.ssot.get_all_services()
        svc_summary = json.dumps(
            [{"name": s["name"], "category": s["category"], "port": s.get("port")}
             for s in services[:20]],
            ensure_ascii=False
        )

        tool_catalog = self.tools.get_tool_catalog()

        similar = self.ssot.find_similar_plans(task, top_k=2)
        similar_text = json.dumps(similar, ensure_ascii=False)[:800] if similar else "없음"

        prompt = f"""## 태스크
{task}

## 서버 서비스
{svc_summary}

## 도구
{tool_catalog}

## 과거 유사 태스크
{similar_text}

## 지시
실행 계획을 세워라. JSON만 출력.
- 각 단계 = 하나의 도구 호출
- shell input = 명령어 문자열
- python input = 코드 문자열
- http input = URL 문자열 또는 {{"method":"GET","url":"..."}}
- code_edit input = {{"action":"read|edit|create","path":"...",...}}
- 이전 결과 참조: {{step_N_result}}
- 최대 10단계

{{"goal":"목표","task_type":"infra|analysis|development|content|monitoring|recovery|growth|other",
"steps":[{{"id":1,"action":"설명","tool":"도구","input":"입력","expect":"예상","on_fail":"대안"}}],
"verify":{{"tool":"도구","input":"검증입력"}}}}"""

        resp = await self.llm(prompt, role="planning")
        text = resp if isinstance(resp, str) else str(resp)

        try:
            plan = ExecutionPlan.from_json(text)
            logger.info(f"Plan: {plan.goal} ({len(plan.steps)} steps)")
            return plan
        except Exception as e:
            logger.error(f"Plan parse error: {e}")
            return ExecutionPlan(
                goal=task,
                steps=[PlanStep(id=1, action=task, tool="shell", input="echo 'plan generation failed'")]
            )

    async def replan(self, original, failed_step, error, completed):
        """실패 시 대안 계획 생성 (최대 2회)."""
        if original.replans >= self.MAX_REPLANS:
            return None

        prompt = f"""계획 실패. 재계획하라.
목표: {original.goal}
완료: {json.dumps([{"action": r["action"], "result": r["result"][:150]} for r in completed], ensure_ascii=False)}
실패: Step {failed_step.id} ({failed_step.action}): {error[:200]}

다른 접근법으로 JSON 계획 출력."""

        resp = await self.llm(prompt, role="planning")
        try:
            plan = ExecutionPlan.from_json(resp if isinstance(resp, str) else str(resp))
            plan.replans = original.replans + 1
            return plan
        except:
            return None


class TaskExecutor:
    """계획의 각 단계를 도구로 실행."""

    def __init__(self, ssot, tools, planner, call_llm_fn, feedback=None):
        self.ssot = ssot
        self.tools = tools
        self.planner = planner
        self.llm = call_llm_fn
        self.feedback = feedback  # v5.0 Phase 3

    async def execute(self, plan, task_id=None, source="planner"):
        """계획 실행."""
        plan_id = self.ssot.save_execution_plan(
            task_id or "unknown", plan.to_json(), len(plan.steps)
        )

        results = []
        step_results = {}

        for step in plan.steps:
            step.status = "running"
            t0 = time.time()

            try:
                tool_input = self._resolve(step.input, step_results)
                output = await self.tools.execute(step.tool, tool_input, source=source)
                dur = int((time.time() - t0) * 1000)

                is_err = output.startswith("ERROR") or output.startswith("BLOCKED")

                if is_err and step.on_fail:
                    output = await self.tools.execute(step.tool, step.on_fail, source=source)
                    is_err = output.startswith("ERROR") or output.startswith("BLOCKED")

                step.result = output[:2000]
                step.status = "failed" if is_err else "success"
                step_results[f"step_{step.id}_result"] = output[:1000]

                self.ssot.log_tool_execution(
                    task_id, step.tool,
                    str(tool_input)[:500], output[:500], not is_err, dur
                )

                results.append({
                    "step_id": step.id,
                    "action": step.action,
                    "tool": step.tool,
                    "result": output[:500],
                    "status": step.status,
                    "duration_ms": dur
                })

                if is_err:
                    new_plan = await self.planner.replan(plan, step, output, results)
                    if new_plan:
                        self.ssot.update_plan_progress(plan_id, len(results), "replanning")
                        return await self.execute(new_plan, task_id, source)
                    break

            except Exception as e:
                step.status = "failed"
                step.result = str(e)
                logger.error(f"Step {step.id} error: {e}")
                break

            done = sum(1 for r in results if r["status"] == "success")
            self.ssot.update_plan_progress(plan_id, done, "running")

        # 검증
        verify = None
        if plan.verify and plan.verify.get("tool"):
            try:
                verify = await self.tools.execute(
                    plan.verify["tool"],
                    self._resolve(plan.verify.get("input", ""), step_results),
                    source=source
                )
            except:
                pass

        ok = sum(1 for r in results if r["status"] == "success")
        status = "completed" if ok == len(plan.steps) else "partial" if ok > 0 else "failed"
        self.ssot.update_plan_progress(plan_id, ok, status)

        return {
            "goal": plan.goal,
            "task_type": plan.task_type,
            "status": status,
            "steps_total": len(plan.steps),
            "steps_success": ok,
            "results": results,
            "verify": verify,
            "replans": plan.replans
        }

    def _resolve(self, data, step_results):
        """이전 단계 결과를 주입 ({step_N_result})."""
        if isinstance(data, str):
            for k, v in step_results.items():
                data = data.replace("{" + k + "}", str(v)[:500])
            return data
        elif isinstance(data, dict):
            return {k: self._resolve(v, step_results) for k, v in data.items()}
        return data
