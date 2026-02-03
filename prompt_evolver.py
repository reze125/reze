"""
REZE v4.0 ULTIMATE Prompt Evolver
- 프롬프트 자기 최적화
- EvoPrompt + OpenAI Self-Evolving 패턴
- A/B 테스트 기반 점진적 개선
"""

import json
import random
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import logging
logger = logging.getLogger("REZE.prompt_evolver")


class PromptEvolver:
    """
    프롬프트 자기 최적화.
    - 성과 낮은 영역 식별
    - 변이 생성 (EvoPrompt)
    - A/B 테스트
    - 보스 피드백 반영
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
        self.skills_dir = Path(__file__).parent / "skills"

    async def evolve_weekly(self) -> dict:
        """매주 실행: 프롬프트 진화."""
        logger.info("Starting weekly prompt evolution...")

        # 1) 이번 주 성과 데이터 수집
        week_results = await self._gather_week_results()

        # 2) 성과 낮은 영역 식별
        weak_areas = [r for r in week_results if r.get("avg_score", 10) < 7.0]

        evolved_count = 0
        evolution_results = []

        # 3) 해당 영역 프롬프트 변이 생성
        for area in weak_areas[:3]:  # 최대 3개 영역
            skill_name = area.get("skill", "unknown")
            failures = area.get("failures", [])

            # 현재 프롬프트 가져오기
            current_prompt = await self._get_current_prompt(skill_name)
            if not current_prompt:
                continue

            # 변이 생성 (EvoPrompt)
            variants = await self._generate_variants(current_prompt, failures)

            if variants:
                # A/B 테스트 등록
                test_id = self.ssot.register_ab_test(
                    skill_name=skill_name,
                    variant_a=current_prompt,
                    variant_b=variants[0]
                )

                evolution_results.append({
                    "skill": skill_name,
                    "test_id": test_id,
                    "reason": f"avg_score={area.get('avg_score', 0):.1f}"
                })
                evolved_count += 1

        # 4) 보스 피드백 반영
        await self._apply_boss_feedback()

        # 5) 완료된 A/B 테스트 정리
        completed_tests = await self._finalize_ab_tests()

        result = {
            "weak_areas_found": len(weak_areas),
            "evolved": evolved_count,
            "evolution_results": evolution_results,
            "completed_tests": completed_tests
        }

        # 리포트
        if self.discord_notify and (evolved_count > 0 or completed_tests):
            await self.discord_notify(
                f"🧬 프롬프트 진화 완료\n"
                f"약점 영역: {len(weak_areas)}개\n"
                f"새 A/B 테스트: {evolved_count}개\n"
                f"완료된 테스트: {len(completed_tests)}개"
            )

        logger.info(f"Prompt evolution completed: {evolved_count} evolved")
        return result

    async def _gather_week_results(self) -> list:
        """이번 주 성과 데이터 수집."""
        # plan_cache_v4에서 스킬별 성과 집계
        rows = self.ssot.conn.execute("""
            SELECT
                skills_used,
                AVG(score) as avg_score,
                COUNT(*) as count
            FROM plan_cache_v4
            WHERE created_at > datetime('now', '-7 days')
            GROUP BY skills_used
        """).fetchall()

        results = []
        for row in rows:
            skills = row[0]
            avg_score = row[1] or 0
            count = row[2]

            # 실패 사례 수집
            failures = []
            if avg_score < 7.0:
                failure_rows = self.ssot.conn.execute("""
                    SELECT task_pattern, procedure FROM plan_cache_v4
                    WHERE skills_used = ? AND score < 7.0
                    AND created_at > datetime('now', '-7 days')
                    LIMIT 3
                """, [skills]).fetchall()
                failures = [{"pattern": f[0], "procedure": f[1][:200]} for f in failure_rows]

            results.append({
                "skill": skills,
                "avg_score": avg_score,
                "count": count,
                "failures": failures
            })

        return results

    async def _get_current_prompt(self, skill_name: str) -> Optional[str]:
        """스킬의 현재 프롬프트 가져오기."""
        # SKILL.md에서 프롬프트 추출
        skill_path = self.skills_dir / skill_name / "SKILL.md"
        if skill_path.exists():
            content = skill_path.read_text()
            return content

        # dynamic_skills에서 찾기
        skill_info = self.ssot.get_skill_status(skill_name)
        if skill_info and skill_info.get("skill_path"):
            path = Path(skill_info["skill_path"]) / "SKILL.md"
            if path.exists():
                return path.read_text()

        return None

    async def _generate_variants(self, current_prompt: str, failures: list) -> list:
        """EvoPrompt: 프롬프트 변이 생성."""
        prompt = f"""[EvoPrompt: 프롬프트 진화]

## 현재 프롬프트
```
{current_prompt[:2000]}
```

## 최근 실패 사례
{json.dumps(failures, indent=2, ensure_ascii=False)[:1000]}

## 진화 요청
현재 프롬프트를 개선하여 실패 사례를 방지할 수 있는 변이를 2개 생성하세요.

변이 전략:
1. 더 명확한 지시 추가
2. 예외 케이스 처리 추가
3. 출력 형식 명확화
4. 제약 조건 강화

JSON 형식:
{{
    "variant_1": "개선된 프롬프트 전문",
    "variant_1_changes": ["변경사항1", "변경사항2"],
    "variant_2": "다른 접근법의 프롬프트",
    "variant_2_changes": ["변경사항1"]
}}"""

        try:
            response = await self.call_llm(prompt, role="writing")
            text = response
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            result = json.loads(text.strip())

            variants = []
            if result.get("variant_1"):
                variants.append(result["variant_1"])
            if result.get("variant_2"):
                variants.append(result["variant_2"])

            return variants
        except Exception as e:
            logger.error(f"Variant generation failed: {e}")
            return []

    async def _apply_boss_feedback(self):
        """보스 피드백 반영하여 품질 기준 조정."""
        # 최근 보스 피드백에서 LLM vs 보스 점수 차이 분석
        feedbacks = self.ssot.conn.execute("""
            SELECT result_type, llm_score, boss_score
            FROM boss_feedback
            WHERE boss_score IS NOT NULL
            AND created_at > datetime('now', '-7 days')
        """).fetchall()

        if not feedbacks:
            return

        # 유형별 보정 필요 여부 분석
        by_type = {}
        for fb in feedbacks:
            result_type = fb[0]
            diff = fb[2] - fb[1]  # boss - llm

            if result_type not in by_type:
                by_type[result_type] = []
            by_type[result_type].append(diff)

        # 큰 차이가 있는 유형 식별
        adjustments = []
        for result_type, diffs in by_type.items():
            avg_diff = sum(diffs) / len(diffs)
            if abs(avg_diff) > 1.0:
                adjustments.append({
                    "type": result_type,
                    "avg_diff": avg_diff,
                    "action": "tighten" if avg_diff < -1.0 else "loosen"
                })

        # 조정 로그
        for adj in adjustments:
            logger.info(f"Quality criteria adjustment: {adj['type']} -> {adj['action']} (diff={adj['avg_diff']:.1f})")

    async def _finalize_ab_tests(self) -> list:
        """완료된 A/B 테스트 정리."""
        # 충분한 데이터가 모인 테스트 찾기
        running_tests = self.ssot.get_running_ab_tests()

        completed = []
        for test in running_tests:
            a_count = test.get("variant_a_count", 0)
            b_count = test.get("variant_b_count", 0)

            # 각 변이가 최소 10회 이상 테스트되면 완료
            if a_count >= 10 and b_count >= 10:
                self.ssot.complete_ab_test(test["id"])

                # 승자 결정
                a_score = test.get("variant_a_score", 0)
                b_score = test.get("variant_b_score", 0)
                winner = "a" if a_score >= b_score else "b"

                # 승자 프롬프트를 실제 SKILL.md에 적용
                if winner == "b":
                    # 새 변이가 승리 -> 적용
                    await self._apply_winning_variant(test)

                completed.append({
                    "skill": test.get("skill_name"),
                    "winner": winner,
                    "a_score": a_score,
                    "b_score": b_score
                })

                logger.info(f"A/B test completed: {test.get('skill_name')} -> winner={winner}")

        return completed

    async def _apply_winning_variant(self, test: dict):
        """승리한 변이를 실제 SKILL.md에 적용."""
        skill_name = test.get("skill_name", "")
        new_prompt = test.get("variant_b", "")

        if not skill_name or not new_prompt:
            return

        skill_path = self.skills_dir / skill_name / "SKILL.md"
        if skill_path.exists():
            # 백업
            backup_path = skill_path.with_suffix(".md.bak")
            skill_path.rename(backup_path)

            # 새 프롬프트 적용
            skill_path.write_text(new_prompt)
            logger.info(f"Applied winning variant to {skill_name}")

    async def suggest_prompt_improvement(self, skill_name: str, feedback: str) -> dict:
        """특정 스킬에 대한 즉시 개선 제안."""
        current_prompt = await self._get_current_prompt(skill_name)
        if not current_prompt:
            return {"error": f"Skill not found: {skill_name}"}

        prompt = f"""[프롬프트 개선 제안]

## 스킬: {skill_name}

## 현재 프롬프트
```
{current_prompt[:1500]}
```

## 피드백
{feedback}

## 개선 요청
피드백을 반영하여 프롬프트를 개선하세요.

JSON 형식:
{{
    "improved_prompt": "개선된 프롬프트",
    "changes": ["변경사항1", "변경사항2"],
    "expected_improvement": "예상 개선 효과"
}}"""

        try:
            response = await self.call_llm(prompt, role="writing")
            text = response
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            return json.loads(text.strip())
        except Exception as e:
            return {"error": str(e)}


# === A/B 테스트 셀렉터 ===

class ABTestSelector:
    """A/B 테스트 중 어떤 변이를 사용할지 선택."""

    def __init__(self, ssot):
        self.ssot = ssot

    def select_variant(self, skill_name: str) -> tuple:
        """
        스킬에 대해 사용할 변이 선택.
        Returns: (variant_content, variant_id, test_id)
        """
        # 실행 중인 A/B 테스트 확인
        test = self.ssot.conn.execute("""
            SELECT id, variant_a, variant_b, variant_a_count, variant_b_count
            FROM ab_tests
            WHERE skill_name = ? AND status = 'running'
            LIMIT 1
        """, [skill_name]).fetchone()

        if not test:
            return (None, None, None)

        test_id, variant_a, variant_b, a_count, b_count = test

        # Epsilon-greedy: 20% 탐색, 80% 활용
        if random.random() < 0.2:
            # 탐색: 덜 테스트된 쪽
            if a_count <= b_count:
                return (variant_a, "a", test_id)
            else:
                return (variant_b, "b", test_id)
        else:
            # 활용: 랜덤 (동등한 기회)
            if random.random() < 0.5:
                return (variant_a, "a", test_id)
            else:
                return (variant_b, "b", test_id)

    def record_result(self, test_id: int, variant: str, score: float):
        """테스트 결과 기록."""
        self.ssot.update_ab_test_score(test_id, variant, score)


# === 편의 함수 ===

async def run_weekly_evolution(call_llm_fn, ssot, discord_notify=None):
    """주간 프롬프트 진화 실행."""
    evolver = PromptEvolver(
        call_llm_fn=call_llm_fn,
        ssot=ssot,
        discord_notify=discord_notify
    )
    return await evolver.evolve_weekly()
