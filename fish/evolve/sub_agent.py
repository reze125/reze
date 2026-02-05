"""
Dynamic Sub-Agent Spawning — REZE v6.0 SOVEREIGN
태스크 분할 실행

복잡한 태스크를 서브에이전트(researcher/writer/critic/optimizer/analyst)로
분할하여 병렬 또는 순차 실행합니다.

가동 조건: 즉시 (항상 활성)
"""

import asyncio
import json
import uuid
import logging
from datetime import datetime
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any

logger = logging.getLogger("reze.evolve.sub_agent")


class AgentType(Enum):
    """서브에이전트 유형"""
    RESEARCHER = "researcher"   # 조사/검색
    WRITER = "writer"           # 콘텐츠 작성
    CRITIC = "critic"           # 비평/검토
    OPTIMIZER = "optimizer"     # 최적화
    ANALYST = "analyst"         # 분석


class ExecutionMode(Enum):
    """실행 모드"""
    PARALLEL = "parallel"           # 병렬 실행
    SEQUENTIAL = "sequential"       # 순차 실행
    FAN_OUT_FAN_IN = "fan_out_fan_in"  # 분산 후 취합


@dataclass
class SubTask:
    """서브태스크"""
    task_id: str
    agent_type: AgentType
    instruction: str
    context: Dict = field(default_factory=dict)
    depends_on: List[str] = field(default_factory=list)
    timeout_sec: int = 120
    result: Optional[Dict] = None
    status: str = "pending"  # pending, running, completed, failed


class SubAgentSpawner:
    """
    서브에이전트 생성 및 관리.
    태스크 분해 → 에이전트 실행 → 결과 취합.
    """

    # 에이전트 유형별 LLM 프로바이더
    AGENT_PROVIDERS = {
        AgentType.RESEARCHER: "cerebras",
        AgentType.WRITER: "gemini_pro",
        AgentType.CRITIC: "groq",
        AgentType.OPTIMIZER: "cerebras",
        AgentType.ANALYST: "groq",
    }

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
        """항상 활성"""
        return True

    async def decompose_task(
        self,
        task_description: str,
        context: Dict = None
    ) -> tuple:
        """
        태스크를 서브태스크로 분해.

        Args:
            task_description: 태스크 설명
            context: 추가 컨텍스트

        Returns:
            (plan_id, execution_mode, subtasks)
        """
        if not self.llm:
            # LLM 없으면 단일 태스크로
            plan_id = f"plan_{uuid.uuid4().hex[:8]}"
            subtask = SubTask(
                task_id=f"{plan_id}_t0",
                agent_type=AgentType.ANALYST,
                instruction=task_description,
                context=context or {}
            )
            return plan_id, ExecutionMode.SEQUENTIAL, [subtask]

        prompt = f"""Decompose this task into sub-agents:

Task: {task_description}
Context: {json.dumps(context or {})}

Available agents:
- researcher: Web search and information gathering
- writer: Content creation and writing
- critic: Review and critique
- optimizer: Optimization and improvement
- analyst: Data analysis

Respond in JSON:
{{
  "execution_mode": "parallel|sequential|fan_out_fan_in",
  "subtasks": [
    {{
      "agent_type": "researcher|writer|critic|optimizer|analyst",
      "instruction": "specific task for this agent",
      "depends_on": [0, 1],  // indices of tasks this depends on
      "timeout_sec": 120
    }}
  ]
}}"""

        try:
            response = await self.llm.call(
                "cerebras",
                [{"role": "user", "content": prompt}],
                max_tokens=2000
            )

            text = response.text if hasattr(response, 'text') else str(response)
            data = json.loads(self._extract_json(text))

            plan_id = f"plan_{uuid.uuid4().hex[:8]}"
            mode = ExecutionMode(data.get("execution_mode", "sequential"))

            subtasks = []
            for i, st in enumerate(data.get("subtasks", [])):
                subtasks.append(SubTask(
                    task_id=f"{plan_id}_t{i}",
                    agent_type=AgentType(st["agent_type"]),
                    instruction=st["instruction"],
                    depends_on=[f"{plan_id}_t{d}" for d in st.get("depends_on", [])],
                    timeout_sec=st.get("timeout_sec", 120)
                ))

            # DB에 플랜 기록
            self.conn.execute("""
                INSERT INTO task_plans
                (plan_id, parent_task, mode, subtask_count, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (
                plan_id,
                task_description[:200],
                mode.value,
                len(subtasks),
                datetime.utcnow().isoformat()
            ))
            self.conn.commit()

            return plan_id, mode, subtasks

        except Exception as e:
            logger.error("Task decomposition failed: %s", e)
            # 폴백: 단일 분석 태스크
            plan_id = f"plan_{uuid.uuid4().hex[:8]}"
            return plan_id, ExecutionMode.SEQUENTIAL, [
                SubTask(
                    task_id=f"{plan_id}_t0",
                    agent_type=AgentType.ANALYST,
                    instruction=task_description,
                    context=context or {}
                )
            ]

    async def execute_plan(
        self,
        plan_id: str,
        mode: ExecutionMode,
        subtasks: List[SubTask]
    ) -> Dict[str, Dict]:
        """
        플랜 실행.

        Args:
            plan_id: 플랜 ID
            mode: 실행 모드
            subtasks: 서브태스크 리스트

        Returns:
            {task_id: result} 딕셔너리
        """
        results = {}

        if mode == ExecutionMode.PARALLEL:
            # 모든 태스크 병렬 실행
            await asyncio.gather(
                *[self._execute_subtask(st, results) for st in subtasks],
                return_exceptions=True
            )

        elif mode == ExecutionMode.SEQUENTIAL:
            # 순차 실행
            for st in subtasks:
                await self._execute_subtask(st, results)

        else:  # FAN_OUT_FAN_IN
            # 독립 태스크 먼저 병렬
            independent = [st for st in subtasks if not st.depends_on]
            dependent = [st for st in subtasks if st.depends_on]

            await asyncio.gather(
                *[self._execute_subtask(st, results) for st in independent],
                return_exceptions=True
            )

            # 의존 태스크는 순차
            for st in dependent:
                # upstream 결과 주입
                st.context["upstream"] = {
                    dep: results.get(dep, {})
                    for dep in st.depends_on
                }
                await self._execute_subtask(st, results)

        # DB 업데이트
        completed = sum(1 for r in results.values() if r.get("status") == "completed")
        failed = sum(1 for r in results.values() if r.get("status") == "failed")

        try:
            self.conn.execute("""
                UPDATE task_plans
                SET completed_count = ?, failed_count = ?, finished_at = ?
                WHERE plan_id = ?
            """, (completed, failed, datetime.utcnow().isoformat(), plan_id))
            self.conn.commit()
        except:
            pass

        return results

    async def _execute_subtask(
        self,
        subtask: SubTask,
        results: Dict
    ):
        """단일 서브태스크 실행"""
        subtask.status = "running"

        try:
            # 에이전트 유형별 처리
            if subtask.agent_type == AgentType.RESEARCHER and self.tavily:
                # Tavily 검색 + 요약
                result = await self._execute_researcher(subtask)
            else:
                # LLM 기반 실행
                result = await self._execute_llm_agent(subtask)

            subtask.result = result
            subtask.status = "completed"
            results[subtask.task_id] = {**result, "status": "completed"}

        except Exception as e:
            error_result = {"error": str(e), "status": "failed"}
            subtask.result = error_result
            subtask.status = "failed"
            results[subtask.task_id] = error_result

    async def _execute_researcher(self, subtask: SubTask) -> Dict:
        """Researcher 에이전트 실행"""
        # Tavily 검색
        search_results = await self.tavily.search(
            query=subtask.instruction,
            max_results=5
        )

        # 결과 요약
        summaries = [
            r.get("content", "")[:500]
            for r in search_results.get("results", [])
        ]

        if not self.llm:
            return {"research": summaries, "sources": search_results.get("results", [])}

        # LLM으로 요약
        summary_prompt = (
            f"Summarize these search results for: {subtask.instruction}\n\n"
            f"Results:\n{'---'.join(summaries)}\n\n"
            f"Provide a concise summary."
        )

        response = await self.llm.call(
            "cerebras",
            [{"role": "user", "content": summary_prompt}],
            max_tokens=1000
        )

        summary = response.text if hasattr(response, 'text') else str(response)

        return {
            "research": summary.strip(),
            "sources": [r.get("url") for r in search_results.get("results", [])]
        }

    async def _execute_llm_agent(self, subtask: SubTask) -> Dict:
        """LLM 기반 에이전트 실행"""
        if not self.llm:
            return {"output": f"[No LLM] Task: {subtask.instruction}"}

        provider = self.AGENT_PROVIDERS.get(subtask.agent_type, "cerebras")

        prompt = f"""You are a {subtask.agent_type.value} agent.

Task: {subtask.instruction}

Context: {json.dumps(subtask.context)}

Provide your output:"""

        try:
            response = await asyncio.wait_for(
                self.llm.call(
                    provider,
                    [{"role": "user", "content": prompt}],
                    max_tokens=2000
                ),
                timeout=subtask.timeout_sec
            )

            output = response.text if hasattr(response, 'text') else str(response)
            return {"output": output.strip()}

        except asyncio.TimeoutError:
            return {"error": "Timeout", "partial": True}

    def _extract_json(self, text: str) -> str:
        """텍스트에서 JSON 추출"""
        if "```json" in text:
            return text.split("```json")[1].split("```")[0].strip()

        start = text.find("{")
        end = text.rfind("}") + 1

        if start >= 0 and end > start:
            return text[start:end]

        return "{}"

    async def run_task(
        self,
        task_description: str,
        context: Dict = None
    ) -> Dict:
        """
        전체 플로우 실행: 분해 → 실행 → 결과 취합.

        Args:
            task_description: 태스크 설명
            context: 추가 컨텍스트

        Returns:
            실행 결과
        """
        # 1. 분해
        plan_id, mode, subtasks = await self.decompose_task(task_description, context)

        logger.info(
            "SubAgent: Plan %s created with %d subtasks (%s)",
            plan_id, len(subtasks), mode.value
        )

        # 2. 실행
        results = await self.execute_plan(plan_id, mode, subtasks)

        # 3. 결과 취합
        return {
            "plan_id": plan_id,
            "mode": mode.value,
            "subtask_count": len(subtasks),
            "results": results,
            "success": all(r.get("status") == "completed" for r in results.values())
        }

    def get_recent_plans(self, limit: int = 20) -> List[Dict]:
        """최근 플랜 목록"""
        try:
            rows = self.conn.execute("""
                SELECT plan_id, parent_task, mode, subtask_count,
                       completed_count, failed_count, created_at, finished_at
                FROM task_plans
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,)).fetchall()

            return [
                {
                    "plan_id": r[0],
                    "task": r[1],
                    "mode": r[2],
                    "subtasks": r[3],
                    "completed": r[4],
                    "failed": r[5],
                    "created_at": r[6],
                    "finished_at": r[7]
                }
                for r in rows
            ]
        except:
            return []
