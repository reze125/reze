"""
REZE v5.0 Phase 4 — PlanMemory
실행 경험을 계층적으로 저장하고 재사용하는 시스템.

MUSE 패턴:
  strategic_memory: 높은 추상화 교훈 (예: "DB 마이그레이션은 백업 먼저")
  procedural_memory: 검증된 절차 (예: "nginx restart: test → reload → check")
  tool_memory: 도구 효과성 (예: "shell_pipe가 PM2 작업에 최적")
"""

import json
import logging

logger = logging.getLogger("reze.plan_memory")


class PlanMemory:
    def __init__(self, ssot, llm_fn):
        """
        ssot: SSOT 인스턴스
        llm_fn: async callable, LLM 호출 함수 (str → str)
        """
        self.ssot = ssot
        self.llm_fn = llm_fn

    # ── 경험 추출 (Reflect) ──

    async def extract_from_execution(self, task_spec: str, plan: str,
                                       result: dict, score: float | None) -> list[dict]:
        """실행 결과에서 3종 경험을 추출.

        Args:
            task_spec: 원래 태스크 설명
            plan: 실행한 플랜 (JSON or text)
            result: 실행 결과 dict (status, steps, output 등)
            score: feedback_engine이 측정한 점수 (None이면 미측정)

        Returns:
            저장된 메모리 리스트 [{"type": ..., "content": ..., "id": ...}]
        """
        # 실패한 태스크에서도 교훈 추출 (오히려 더 가치 있음)
        outcome = "SUCCESS" if score and score >= 0.8 else "PARTIAL" if score and score >= 0.5 else "FAILURE" if score is not None else "UNKNOWN"

        prompt = f"""You are REZE's memory system. Extract reusable lessons from this task execution.

TASK: {task_spec}
PLAN: {str(plan)[:1000]}
RESULT STATUS: {outcome}
SCORE: {score}
RESULT DETAIL: {json.dumps(result, default=str)[:1000]}

Extract up to 3 memories. For each, classify as:
- "strategic": High-level lesson applicable across many tasks (e.g. "Always backup before migration")
- "procedural": Specific step sequence that worked/failed (e.g. "For nginx: test config → reload → verify")
- "tool": Which tool was effective/ineffective (e.g. "shell_pipe better than http_auth for PM2 tasks")

RULES:
- Only extract if genuinely reusable. Skip trivial observations.
- For FAILURE/PARTIAL: focus on WHAT WENT WRONG and HOW TO AVOID
- For SUCCESS: focus on WHAT WORKED and WHY
- Include relevant keywords in "tags" for future search

Respond ONLY in JSON array:
[
  {{"type": "strategic|procedural|tool", "content": "...", "tags": "keyword1,keyword2"}}
]

If nothing worth remembering, respond: []"""

        try:
            response = await self.llm_fn(prompt)
            cleaned = response.strip() if isinstance(response, str) else str(response).strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
            memories = json.loads(cleaned)
            if not isinstance(memories, list):
                return []
        except (json.JSONDecodeError, Exception) as e:
            logger.error(f"PlanMemory extract failed: {e}")
            return []

        # DB에 저장
        stored = []
        for m in memories:
            mem_type = m.get("type", "")
            content = m.get("content", "")
            tags = m.get("tags", "")

            if mem_type not in ("strategic", "procedural", "tool") or not content:
                continue

            mem_id = self.ssot.store_memory(
                memory_type=mem_type,
                content=content,
                source_task=task_spec[:200],
                relevance_tags=tags
            )
            stored.append({"type": mem_type, "content": content, "id": mem_id})
            logger.info(f"Memory stored #{mem_id} [{mem_type}]: {content[:80]}...")

        return stored

    # ── 경험 검색 + Planner 컨텍스트 생성 (Exploit) ──

    def recall_for_task(self, task_spec: str) -> str:
        """태스크에 관련된 과거 경험을 검색하여 Planner 컨텍스트 문자열로 반환.

        Returns:
            Planner 프롬프트에 주입할 "PAST EXPERIENCE" 블록.
            경험이 없으면 빈 문자열.
        """
        # 태스크에서 키워드 추출 (단순 분할)
        keywords = [w for w in task_spec.split() if len(w) > 2][:5]

        all_memories = []
        for kw in keywords:
            for mem_type in ("strategic", "procedural", "tool"):
                results = self.ssot.search_memory(mem_type, kw, limit=3)
                for r in results:
                    # 중복 제거
                    if r["id"] not in [m["id"] for m in all_memories]:
                        r["memory_type"] = mem_type
                        all_memories.append(r)

        if not all_memories:
            return ""

        # use_count 갱신
        for m in all_memories:
            self.ssot.touch_memory(m["id"])

        # Planner 컨텍스트 포맷
        sections = {"strategic": [], "procedural": [], "tool": []}
        for m in all_memories:
            sections[m["memory_type"]].append(m["content"])

        context_parts = ["\n## PAST EXPERIENCE (from previous tasks)"]

        if sections["strategic"]:
            context_parts.append("### Strategic Lessons:")
            for s in sections["strategic"][:3]:
                context_parts.append(f"- {s}")

        if sections["procedural"]:
            context_parts.append("### Known Procedures:")
            for p in sections["procedural"][:3]:
                context_parts.append(f"- {p}")

        if sections["tool"]:
            context_parts.append("### Tool Notes:")
            for t in sections["tool"][:3]:
                context_parts.append(f"- {t}")

        return "\n".join(context_parts)

    # ── 메모리 정리 ──

    def cleanup_stale(self, unused_days: int = 30) -> int:
        """일정 기간 사용되지 않은 메모리 삭제."""
        deleted = self.ssot.conn.execute("""
            DELETE FROM plan_memory
            WHERE use_count = 0
            AND created_at < datetime('now', ? || ' days')
        """, (f"-{unused_days}",))
        self.ssot.conn.commit()
        count = deleted.rowcount
        if count:
            logger.info(f"Cleaned up {count} stale memories (unused for {unused_days}+ days)")
        return count
