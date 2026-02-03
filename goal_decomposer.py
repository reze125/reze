"""
REZE v4.0 Goal Decomposer
- 전략적 목표 -> 중간 목표 -> 실행 태스크 계층 분해
- 주간 진행 리뷰
"""

import json
from typing import Optional

import logging
logger = logging.getLogger("REZE.goal_decomposer")


class GoalDecomposer:
    """상위 목표를 실행 가능한 태스크로 분해."""

    def __init__(self, call_llm_fn, ssot, skills_manager):
        """
        Args:
            call_llm_fn: LLM 호출 함수 (async, prompt + role 인자)
            ssot: SSOT 인스턴스
            skills_manager: SkillsManager 인스턴스
        """
        self.call_llm = call_llm_fn
        self.ssot = ssot
        self.skills_manager = skills_manager

    async def decompose(self, goal: str, context: dict = None) -> dict:
        """
        상위 목표 -> 중간 목표 -> 실행 태스크로 분해.

        Args:
            goal: 상위 목표 (예: "월 MRR $10K 달성")
            context: 추가 컨텍스트

        Returns:
            분해된 목표 구조
        """
        logger.info(f"Decomposing goal: {goal[:50]}")

        # 1. 현재 상황 파악
        current_state = self._gather_current_state()

        # 2. 사용 가능한 역량 파악
        available_skills = list(self.skills_manager.catalog.keys())
        dynamic_skills = list(self.skills_manager.dynamic_catalog.keys())

        # 3. 목표 분해 (LLM)
        decomposition = await self.call_llm(
            f"""너는 1인 개발자 사업의 전략 컨설턴트다.

## 상위 목표
{goal}

## 현재 상황
{json.dumps(current_state, indent=2, ensure_ascii=False)}

## 사용 가능한 역량
메타스킬: {available_skills}
동적 스킬: {dynamic_skills}

## 분해 규칙
1. 중간 목표는 3-5개. 각각 독립적으로 측정 가능
2. 실행 태스크는 중간 목표당 2-4개. REZE가 실제 수행 가능
3. 각 태스크에 우선순위(P1/P2/P3)와 예상 기간 명시
4. 비현실적 목표는 솔직히 지적하고 현실적 대안 제시
5. 각 태스크에 성공 지표(KPI) 명시

JSON 응답:
{{
    "goal": "원래 목표",
    "feasibility": "high/medium/low",
    "feasibility_note": "현실성 평가",
    "sub_goals": [
        {{
            "name": "중간 목표명",
            "metric": "측정 지표",
            "tasks": [
                {{
                    "name": "태스크명",
                    "description": "구체적 행동",
                    "skill_required": "사용할 스킬",
                    "priority": "P1/P2/P3",
                    "estimated_days": 3,
                    "kpi": "성공 지표"
                }}
            ]
        }}
    ],
    "quick_wins": ["즉시 실행 가능한 빠른 성과"]
}}""",
            role="analysis"
        )

        try:
            # JSON 파싱
            text = decomposition
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            parsed = json.loads(text.strip())
        except Exception as e:
            logger.error(f"Goal decomposition parsing failed: {e}")
            return {"error": f"Goal decomposition parsing failed: {e}"}

        # 4. SSOT에 저장
        try:
            self.ssot.conn.execute("""
                INSERT INTO goal_tree (goal, decomposition, feasibility)
                VALUES (?, ?, ?)
            """, [goal, json.dumps(parsed, ensure_ascii=False), parsed.get('feasibility', 'medium')])
            goal_id = self.ssot.conn.execute("SELECT last_insert_rowid()").fetchone()[0]

            # 5. 개별 태스크 저장
            for sub_goal in parsed.get('sub_goals', []):
                for task in sub_goal.get('tasks', []):
                    self.ssot.conn.execute("""
                        INSERT INTO goal_tasks
                        (goal_id, sub_goal, task_name, description, skill_required,
                         priority, kpi)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, [goal_id, sub_goal['name'], task['name'],
                          task.get('description', ''), task.get('skill_required', ''),
                          task.get('priority', 'P2'), task.get('kpi', '')])

            self.ssot.conn.commit()
            parsed['goal_id'] = goal_id
            logger.info(f"Goal decomposed and saved: goal_id={goal_id}")

        except Exception as e:
            logger.error(f"Goal save failed: {e}")

        return parsed

    async def weekly_review(self) -> str:
        """주간 목표 진행 리뷰."""
        db = self.ssot._get_db()

        active_goals = db.execute("""
            SELECT id, goal, progress_pct FROM goal_tree
            WHERE status = 'active'
        """).fetchall()

        if not active_goals:
            return "활성 목표 없음"

        report_parts = []
        for goal_id, goal_text, progress in active_goals:
            tasks = db.execute("""
                SELECT task_name, status, actual_result
                FROM goal_tasks WHERE goal_id = ?
            """, [goal_id]).fetchall()

            completed = sum(1 for t in tasks if t[1] == 'completed')
            total = len(tasks)

            # 진행률 업데이트
            new_progress = (completed / total * 100) if total > 0 else 0
            db.execute("""
                UPDATE goal_tree SET progress_pct = ?, last_reviewed = datetime('now')
                WHERE id = ?
            """, [new_progress, goal_id])

            task_list = "\n".join(
                f"  {'[완료]' if t[1]=='completed' else '[대기]'} {t[0]}"
                for t in tasks[:5]
            )
            report_parts.append(
                f"**{goal_text[:50]}** ({completed}/{total} 완료, {new_progress:.0f}%)\n{task_list}"
            )

        db.commit()
        return "\n\n".join(report_parts)

    async def update_task_status(self, goal_id: int, task_name: str,
                                  status: str, actual_result: str = None) -> bool:
        """태스크 상태 업데이트."""
        try:
            self.ssot.conn.execute("""
                UPDATE goal_tasks SET status = ?, actual_result = ?,
                completed_at = CASE WHEN ? = 'completed' THEN datetime('now') ELSE NULL END
                WHERE goal_id = ? AND task_name = ?
            """, [status, actual_result, status, goal_id, task_name])
            self.ssot.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Task status update failed: {e}")
            return False

    def _gather_current_state(self) -> dict:
        """현재 운영 상태 수집."""
        try:
            services = self.ssot.get_known_services()

            # 최근 성과
            db = self.ssot._get_db()
            recent_scores = db.execute("""
                SELECT task_pattern, AVG(score) as avg_score FROM plan_cache_v4
                WHERE created_at > datetime('now', '-7 days')
                GROUP BY task_pattern
                LIMIT 10
            """).fetchall()

            # 서비스 분류
            blog_count = len([s for s in services if 'blog' in s.lower() or 'lab' in s.lower()])
            saas_count = len([s for s in services if 'pilot' in s.lower() or 'hub' in s.lower()])

            return {
                "active_services": services[:10],
                "recent_performance": {r[0]: round(r[1], 2) for r in recent_scores},
                "blog_count": blog_count,
                "saas_count": saas_count,
                "total_services": len(services),
            }
        except Exception as e:
            logger.warning(f"State gathering failed: {e}")
            return {"note": f"State gathering failed: {e}"}

    async def get_next_priority_task(self) -> Optional[dict]:
        """다음 우선순위 태스크 반환 (P1 > P2 > P3, pending 상태)."""
        db = self.ssot._get_db()

        task = db.execute("""
            SELECT gt.id, gt.goal_id, g.goal, gt.task_name, gt.description,
                   gt.skill_required, gt.priority, gt.kpi
            FROM goal_tasks gt
            JOIN goal_tree g ON gt.goal_id = g.id
            WHERE gt.status = 'pending' AND g.status = 'active'
            ORDER BY
                CASE gt.priority WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 ELSE 3 END,
                gt.created_at
            LIMIT 1
        """).fetchone()

        if not task:
            return None

        return {
            "task_id": task[0],
            "goal_id": task[1],
            "goal": task[2],
            "task_name": task[3],
            "description": task[4],
            "skill_required": task[5],
            "priority": task[6],
            "kpi": task[7],
        }
