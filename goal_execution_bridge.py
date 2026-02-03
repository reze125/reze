"""
REZE v4.0 ULTIMATE Goal Execution Bridge
- 상위 목표 → 중간 목표 → 실행 태스크 분해
- 태스크를 task_queue에 자동 등록
- TMS(Thought Management System) 기반
"""

import json
from datetime import datetime, timedelta
from typing import Optional, Callable

import logging
logger = logging.getLogger("REZE.goal_bridge")


class GoalExecutionBridge:
    """
    상위 목표 → 중간 목표 → 실행 태스크로 재귀 분해 후,
    실행 가능한 태스크를 autonomous_loop의 큐에 자동 등록.
    """

    def __init__(self, call_llm_fn: Callable, ssot, discord_notify: Callable = None):
        """
        Args:
            call_llm_fn: LLM 호출 함수
            ssot: SSOT 인스턴스
            discord_notify: Discord 알림 함수
        """
        self.call_llm = call_llm_fn
        self.ssot = ssot
        self.discord_notify = discord_notify

    async def decompose_and_queue(self, goal: str, deadline: str = None) -> dict:
        """
        목표를 분해하고 태스크 큐에 등록.

        Args:
            goal: 상위 목표 (예: "월수익 $5K")
            deadline: 목표 기한 (예: "2026-06-30")

        Returns:
            분해 결과 + 등록된 태스크 수
        """
        logger.info(f"Decomposing goal: {goal}")

        # Step 1: LLM으로 목표 분해
        tree = await self._decompose_goal(goal, deadline)

        if "error" in tree:
            return tree

        # Step 2: goal_tree에 저장
        goal_id = await self._save_goal_tree(goal, tree)
        tree["goal_id"] = goal_id

        # Step 3: 실행 가능한 태스크를 task_queue에 등록
        queued_count = 0
        for sub_goal in tree.get("sub_goals", []):
            for task in sub_goal.get("tasks", []):
                await self._register_task(
                    task,
                    parent_goal=goal,
                    sub_goal=sub_goal["name"],
                    goal_id=goal_id
                )
                queued_count += 1

        tree["queued_tasks"] = queued_count

        # Step 4: 알림
        if self.discord_notify:
            await self.discord_notify(
                f"🎯 목표 분해 완료: {goal[:50]}\n"
                f"중간 목표: {len(tree.get('sub_goals', []))}개\n"
                f"태스크 큐 등록: {queued_count}개"
            )

        logger.info(f"Goal decomposed: {queued_count} tasks queued")
        return tree

    async def _decompose_goal(self, goal: str, deadline: str = None) -> dict:
        """LLM으로 목표 분해."""
        # 현재 서비스 상황 수집
        current_state = await self._gather_current_state()

        prompt = f"""너는 1인 개발자 사업의 전략 컨설턴트다.

## 상위 목표
{goal}

## 기한
{deadline or "미정 (3개월 내 권장)"}

## 현재 상황
{json.dumps(current_state, indent=2, ensure_ascii=False)}

## 분해 규칙
1. 중간 목표는 3-5개. 각각 독립적으로 측정 가능
2. 실행 태스크는 중간 목표당 2-4개. REZE가 실제 수행 가능
3. 각 태스크에:
   - action: 구체적 액션 (publish_articles, seo_audit, funnel_optimize 등)
   - target: 대상 서비스명
   - frequency: once / daily / weekly / hourly
   - priority: 0-100 (높을수록 먼저)
4. 비현실적 목표는 솔직히 지적하고 현실적 대안 제시
5. 각 태스크에 성공 지표(KPI) 명시

JSON 응답:
{{
    "goal": "원래 목표",
    "feasibility": "high/medium/low",
    "feasibility_note": "현실성 평가",
    "deadline": "YYYY-MM-DD",
    "sub_goals": [
        {{
            "name": "중간 목표명",
            "metric": "측정 지표",
            "target_value": "목표 수치",
            "tasks": [
                {{
                    "action": "액션명",
                    "target": "대상 서비스",
                    "description": "구체적 행동",
                    "frequency": "once/daily/weekly",
                    "priority": 70,
                    "kpi": "성공 지표",
                    "estimated_days": 3
                }}
            ]
        }}
    ],
    "quick_wins": ["즉시 실행 가능한 빠른 성과"]
}}"""

        response = await self.call_llm(prompt, role="analysis")

        try:
            text = response
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            return json.loads(text.strip())
        except Exception as e:
            logger.error(f"Goal decomposition parsing failed: {e}")
            return {"error": f"Parsing failed: {e}"}

    async def _gather_current_state(self) -> dict:
        """현재 운영 상태 수집."""
        try:
            # 서비스 목록
            services = self.ssot.get_known_services()

            # 최근 수익
            revenue = self.ssot.get_latest_revenue()

            # 최근 SaaS 상태
            saas_health = self.ssot.get_latest_saas_health()

            # 최근 성과
            recent_plans = self.ssot.find_cached_plan_v4("", threshold=0.0)

            return {
                "active_services": services[:10],
                "latest_revenue": revenue if revenue else {},
                "saas_health": [dict(s) for s in saas_health[:5]] if saas_health else [],
                "recent_successes": recent_plans.get("task_pattern") if recent_plans else None
            }
        except Exception as e:
            logger.warning(f"State gathering failed: {e}")
            return {"note": f"State gathering failed: {e}"}

    async def _save_goal_tree(self, goal: str, tree: dict) -> int:
        """goal_tree에 저장."""
        try:
            self.ssot.conn.execute("""
                INSERT INTO goal_tree (goal, decomposition, feasibility, status)
                VALUES (?, ?, ?, 'active')
            """, [goal, json.dumps(tree, ensure_ascii=False),
                  tree.get('feasibility', 'medium')])
            self.ssot.conn.commit()
            row = self.ssot.conn.execute("SELECT last_insert_rowid()").fetchone()
            return row[0]
        except Exception as e:
            logger.error(f"Goal tree save failed: {e}")
            return 0

    async def _register_task(self, task: dict, parent_goal: str,
                             sub_goal: str, goal_id: int):
        """task_queue에 태스크 등록."""
        # 다음 실행 시간 계산
        next_run = self._calculate_next_run(task)

        self.ssot.enqueue_task(
            task_type="goal_task",
            target_service=task.get("target", "*"),
            action=task.get("action", "execute"),
            parameters={
                "description": task.get("description", ""),
                "kpi": task.get("kpi", ""),
                "estimated_days": task.get("estimated_days", 1),
                "goal_id": goal_id,
                "sub_goal": sub_goal
            },
            parent_goal=parent_goal,
            sub_goal=sub_goal,
            priority=task.get("priority", 50),
            frequency=task.get("frequency", "once"),
            next_run=next_run
        )

    def _calculate_next_run(self, task: dict) -> str:
        """다음 실행 시간 계산."""
        frequency = task.get("frequency", "once")
        now = datetime.now()

        if frequency == "once":
            return now.isoformat()
        elif frequency == "daily":
            return (now + timedelta(days=1)).replace(hour=9, minute=0).isoformat()
        elif frequency == "weekly":
            return (now + timedelta(days=7)).replace(hour=9, minute=0).isoformat()
        elif frequency == "hourly":
            return (now + timedelta(hours=1)).isoformat()
        else:
            return now.isoformat()

    async def progress_check(self):
        """매일: 목표 대비 진행률 체크."""
        goals = self.ssot.conn.execute("""
            SELECT id, goal, decomposition, progress_pct
            FROM goal_tree WHERE status = 'active'
        """).fetchall()

        if not goals:
            return {"message": "활성 목표 없음"}

        results = []
        for goal_row in goals:
            goal_id = goal_row[0]
            goal_text = goal_row[1]
            current_progress = goal_row[3] or 0

            # 완료된 태스크 수 계산
            stats = self.ssot.conn.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) as done
                FROM task_queue WHERE parent_goal = ?
            """, [goal_text]).fetchone()

            total = stats[0] or 0
            done = stats[1] or 0
            new_progress = (done / total * 100) if total > 0 else 0

            # 진행률 업데이트
            self.ssot.conn.execute("""
                UPDATE goal_tree SET progress_pct = ?, last_reviewed = datetime('now')
                WHERE id = ?
            """, [new_progress, goal_id])

            # 지연 감지
            expected_progress = await self._calculate_expected_progress(goal_row)
            is_delayed = new_progress < expected_progress - 10

            if is_delayed:
                # 지연됨 → 관련 태스크 우선순위 올리기
                await self._boost_priority(goal_id)

            results.append({
                "goal_id": goal_id,
                "goal": goal_text[:50],
                "progress": new_progress,
                "expected": expected_progress,
                "delayed": is_delayed,
                "tasks_done": done,
                "tasks_total": total
            })

        self.ssot.conn.commit()

        # 지연된 목표 알림
        delayed_goals = [r for r in results if r["delayed"]]
        if delayed_goals and self.discord_notify:
            await self.discord_notify(
                f"⚠️ 지연된 목표 {len(delayed_goals)}개\n" +
                "\n".join(f"- {g['goal']}: {g['progress']:.0f}% (예상 {g['expected']:.0f}%)"
                         for g in delayed_goals)
            )

        return results

    async def _calculate_expected_progress(self, goal_row) -> float:
        """목표의 예상 진행률 계산 (기한 기준)."""
        try:
            decomposition = json.loads(goal_row[2])
            deadline = decomposition.get("deadline")
            if not deadline:
                return 50.0  # 기본값

            deadline_date = datetime.fromisoformat(deadline)
            created_at = self.ssot.conn.execute(
                "SELECT created_at FROM goal_tree WHERE id = ?",
                [goal_row[0]]
            ).fetchone()[0]
            start_date = datetime.fromisoformat(created_at.replace(' ', 'T'))

            total_days = (deadline_date - start_date).days
            elapsed_days = (datetime.now() - start_date).days

            if total_days <= 0:
                return 100.0

            return min(100.0, (elapsed_days / total_days) * 100)
        except:
            return 50.0

    async def _boost_priority(self, goal_id: int):
        """지연된 목표의 태스크 우선순위 상향."""
        self.ssot.conn.execute("""
            UPDATE task_queue
            SET priority = MIN(priority + 20, 100)
            WHERE parent_goal IN (
                SELECT goal FROM goal_tree WHERE id = ?
            ) AND status = 'pending'
        """, [goal_id])
        self.ssot.conn.commit()
        logger.info(f"Priority boosted for goal_id={goal_id}")

    async def weekly_redecompose(self):
        """주간: 상황 변화 반영하여 목표 재분해."""
        goals = self.ssot.conn.execute("""
            SELECT id, goal, progress_pct FROM goal_tree
            WHERE status = 'active' AND progress_pct < 90
        """).fetchall()

        redecomposed = []
        for goal_row in goals:
            goal_id, goal_text, progress = goal_row

            # 완료되지 않은 태스크들
            pending = self.ssot.conn.execute("""
                SELECT action, target_service FROM task_queue
                WHERE parent_goal = ? AND status = 'pending'
            """, [goal_text]).fetchall()

            if len(pending) < 3:
                # 태스크가 거의 완료됨 → 추가 분해
                logger.info(f"Redecomposing goal: {goal_text[:30]}")

                # 나머지 목표에 대해 추가 태스크 생성
                new_tree = await self._decompose_goal(
                    f"{goal_text} (진행률 {progress:.0f}% - 추가 태스크 필요)",
                    deadline=None
                )

                # 새 태스크만 등록
                for sub_goal in new_tree.get("sub_goals", []):
                    for task in sub_goal.get("tasks", []):
                        # 이미 있는 태스크인지 확인
                        existing = self.ssot.conn.execute("""
                            SELECT id FROM task_queue
                            WHERE parent_goal = ? AND action = ? AND target_service = ?
                        """, [goal_text, task.get("action"), task.get("target")]).fetchone()

                        if not existing:
                            await self._register_task(
                                task, goal_text, sub_goal["name"], goal_id
                            )

                redecomposed.append(goal_text[:30])

        if redecomposed and self.discord_notify:
            await self.discord_notify(
                f"🔄 주간 목표 재분해: {len(redecomposed)}개\n" +
                "\n".join(f"- {g}" for g in redecomposed)
            )

        return {"redecomposed": redecomposed}

    async def complete_task(self, task_id: int, result: str = None) -> bool:
        """태스크 완료 처리."""
        self.ssot.update_task_queue_status(task_id, "done", result)
        return True

    async def get_next_task(self) -> Optional[dict]:
        """다음 우선순위 태스크 반환."""
        tasks = self.ssot.get_pending_tasks_queue(limit=1)
        return tasks[0] if tasks else None
