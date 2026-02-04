"""Voyager - 성공 패턴 기반 스킬 자동 생성 엔진.

성공한 태스크 실행 패턴을 분석하여 재사용 가능한 스킬로 저장.
유사 태스크 발생 시 기존 스킬을 활용하여 효율성 증대.
"""
import logging
import json
import re
import uuid
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger("REZE.voyager")


@dataclass
class VoyagerSkill:
    """Voyager가 생성한 스킬."""
    skill_id: str
    name: str
    description: str
    task_pattern: str
    intent_patterns: List[str]
    allowed_tools: List[str]
    tool_sequence: List[Dict[str, Any]]
    system_prompt: str = ""
    examples: List[Dict[str, str]] = field(default_factory=list)
    confidence: float = 0.5
    use_count: int = 0
    success_count: int = 0


class VoyagerEngine:
    """성공 패턴 → 재사용 스킬 자동 생성."""

    # 스킬 생성 최소 조건
    MIN_TOOLS_FOR_SKILL = 2      # 최소 2개 도구 사용
    MIN_STEPS_FOR_SKILL = 3      # 최소 3단계 실행

    def __init__(self, ssot, router=None):
        """
        Args:
            ssot: SSOT 인스턴스
            router: LLM 라우터 (선택)
        """
        self.ssot = ssot
        self.router = router

    async def extract_skill(
        self,
        task_id: str,
        task: str,
        tool_history: List[Dict[str, Any]],
        final_answer: str,
        success: bool = True
    ) -> Optional[VoyagerSkill]:
        """
        성공한 태스크에서 스킬 추출.

        Args:
            task_id: 태스크 ID
            task: 원본 태스크
            tool_history: 도구 실행 이력 [{tool, input, output, success}]
            final_answer: 최종 답변
            success: 성공 여부

        Returns:
            VoyagerSkill 또는 None (추출 불가 시)
        """
        if not success:
            return None

        # 최소 조건 검증
        successful_tools = [t for t in tool_history if t.get("success", True)]
        if len(successful_tools) < self.MIN_TOOLS_FOR_SKILL:
            logger.debug(f"[Voyager] Too few tools ({len(successful_tools)}) for skill extraction")
            return None

        # 유사 스킬 중복 체크
        existing = self.find_similar_skill(task)
        if existing and existing.confidence > 0.7:
            # 기존 스킬 강화
            self._reinforce_skill(existing.skill_id, task_id)
            logger.debug(f"[Voyager] Reinforced existing skill: {existing.name}")
            return None

        # 스킬 생성
        skill = await self._generate_skill(task, tool_history, final_answer)
        if skill:
            self._save_skill(skill, task_id)
            logger.info(f"[Voyager] Created skill: {skill.name} (tools: {skill.allowed_tools})")

        return skill

    async def _generate_skill(
        self,
        task: str,
        tool_history: List[Dict],
        final_answer: str
    ) -> Optional[VoyagerSkill]:
        """스킬 정의 생성."""
        # 도구 시퀀스 추출
        tools_used = []
        tool_sequence = []
        for t in tool_history:
            if t.get("success", True):
                tool_name = t.get("tool", "")
                if tool_name and tool_name not in tools_used:
                    tools_used.append(tool_name)
                tool_sequence.append({
                    "tool": tool_name,
                    "input_pattern": self._extract_pattern(t.get("input", "")),
                    "output_hint": str(t.get("output", ""))[:100]
                })

        if not tools_used:
            return None

        # 스킬명 & 설명 생성
        if self.router:
            meta = await self._generate_meta(task, tools_used, final_answer)
        else:
            meta = self._fallback_meta(task, tools_used)

        # intent_patterns 생성
        intent_patterns = self._extract_intent_patterns(task)

        skill_id = f"voy_{uuid.uuid4().hex[:8]}"

        return VoyagerSkill(
            skill_id=skill_id,
            name=meta["name"],
            description=meta["description"],
            task_pattern=task,
            intent_patterns=intent_patterns,
            allowed_tools=tools_used,
            tool_sequence=tool_sequence,
            system_prompt=meta.get("system_prompt", ""),
            examples=[{"task": task, "approach": meta.get("approach", "")}],
            confidence=0.5
        )

    def _extract_pattern(self, input_text: str) -> str:
        """입력에서 재사용 가능한 패턴 추출."""
        pattern = str(input_text)
        # URL, 숫자 등 구체적인 값을 플레이스홀더로
        pattern = re.sub(r'https?://[^\s]+', '{URL}', pattern)
        pattern = re.sub(r'\d{4}-\d{2}-\d{2}', '{DATE}', pattern)
        pattern = re.sub(r'\b\d+\b', '{NUM}', pattern)
        pattern = re.sub(r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}', '{UUID}', pattern)
        return pattern[:200]

    def _extract_intent_patterns(self, task: str) -> List[str]:
        """태스크에서 intent 패턴 추출."""
        patterns = []

        # 핵심 동사 추출
        verbs = ["분석", "조사", "검색", "작성", "생성", "수정", "확인", "비교",
                 "찾아", "알아", "만들", "업데이트", "삭제", "추가", "정리"]
        for verb in verbs:
            if verb in task:
                patterns.append(verb)

        # 명사구 추출 (간단한 휴리스틱)
        # 불용어 제외
        stopwords = {"해주세요", "해줘", "부탁", "좀", "것", "거", "수", "등", "및"}
        words = task.split()
        for word in words:
            if len(word) >= 2 and word not in stopwords:
                patterns.append(word)
                if len(patterns) >= 5:
                    break

        return patterns[:5] if patterns else [task[:20]]

    async def _generate_meta(
        self, task: str, tools: List[str], answer: str
    ) -> Dict[str, str]:
        """LLM으로 스킬 메타데이터 생성."""
        prompt = f"""다음 성공한 태스크를 재사용 가능한 스킬로 정의하세요.

## 원본 태스크
{task}

## 사용된 도구
{', '.join(tools)}

## 결과 요약
{answer[:500]}

## 응답 (JSON만 출력, 다른 텍스트 없이)
{{
  "name": "스킬 영문 이름 (kebab-case, 예: market-research)",
  "description": "스킬 설명 (한글, 1줄)",
  "system_prompt": "이 스킬의 시스템 프롬프트 (한글, 2-3문장)",
  "approach": "접근 방식 요약 (도구 사용 순서)"
}}"""

        try:
            response = await self.router.call(
                "voyager",
                [{"role": "user", "content": prompt}],
                temperature=0.3
            )
            text = response.text if hasattr(response, 'text') else str(response)

            # JSON 추출
            match = re.search(r'\{[^{}]+\}', text, re.DOTALL)
            if match:
                return json.loads(match.group())
        except Exception as e:
            logger.warning(f"[Voyager] Meta generation failed: {e}")

        return self._fallback_meta(task, tools)

    def _fallback_meta(self, task: str, tools: List[str]) -> Dict[str, str]:
        """LLM 실패 시 기본 메타데이터."""
        # 태스크에서 키워드 추출
        keywords = [w for w in task.split() if len(w) >= 2][:3]
        name = "-".join(keywords).lower().replace(" ", "-")[:30]
        # 특수문자 제거
        name = re.sub(r'[^a-z0-9-]', '', name) or "auto-skill"

        return {
            "name": name,
            "description": f"자동 생성 스킬: {task[:50]}",
            "system_prompt": f"이 태스크를 수행하기 위해 다음 도구를 사용합니다: {', '.join(tools)}",
            "approach": " → ".join(tools)
        }

    def find_similar_skill(self, task: str, threshold: float = 0.3) -> Optional[VoyagerSkill]:
        """유사 스킬 검색."""
        # 키워드 기반 검색
        words = task.lower().split()[:5]
        for word in words:
            if len(word) < 3:
                continue

            row = self.ssot.conn.execute("""
                SELECT * FROM voyager_skills
                WHERE status = 'active'
                AND (task_pattern LIKE ? OR intent_patterns LIKE ?)
                ORDER BY confidence DESC, use_count DESC
                LIMIT 1
            """, (f"%{word}%", f"%{word}%")).fetchone()

            if row:
                return self._row_to_skill(row)

        return None

    def get_skill(self, skill_id: str) -> Optional[VoyagerSkill]:
        """스킬 조회."""
        row = self.ssot.conn.execute(
            "SELECT * FROM voyager_skills WHERE skill_id = ?",
            (skill_id,)
        ).fetchone()
        return self._row_to_skill(row) if row else None

    def get_skill_by_name(self, name: str) -> Optional[VoyagerSkill]:
        """스킬 이름으로 조회."""
        row = self.ssot.conn.execute(
            "SELECT * FROM voyager_skills WHERE name = ? AND status = 'active'",
            (name,)
        ).fetchone()
        return self._row_to_skill(row) if row else None

    def list_skills(self, limit: int = 20) -> List[VoyagerSkill]:
        """활성 스킬 목록."""
        rows = self.ssot.conn.execute("""
            SELECT * FROM voyager_skills
            WHERE status = 'active'
            ORDER BY use_count DESC, confidence DESC
            LIMIT ?
        """, (limit,)).fetchall()
        return [self._row_to_skill(r) for r in rows]

    def _row_to_skill(self, row) -> VoyagerSkill:
        """DB row → VoyagerSkill."""
        d = dict(row)
        return VoyagerSkill(
            skill_id=d["skill_id"],
            name=d["name"],
            description=d["description"],
            task_pattern=d["task_pattern"],
            intent_patterns=json.loads(d["intent_patterns"]),
            allowed_tools=json.loads(d["allowed_tools"]),
            tool_sequence=json.loads(d["tool_sequence"]),
            system_prompt=d.get("system_prompt") or "",
            examples=json.loads(d.get("examples") or "[]"),
            confidence=d.get("confidence", 0.5),
            use_count=d.get("use_count", 0),
            success_count=d.get("success_count", 0)
        )

    def _save_skill(self, skill: VoyagerSkill, source_task_id: str):
        """스킬 저장."""
        self.ssot.conn.execute("""
            INSERT INTO voyager_skills
            (skill_id, name, description, task_pattern, intent_patterns,
             allowed_tools, tool_sequence, system_prompt, examples,
             source_task_id, confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            skill.skill_id,
            skill.name,
            skill.description,
            skill.task_pattern,
            json.dumps(skill.intent_patterns, ensure_ascii=False),
            json.dumps(skill.allowed_tools, ensure_ascii=False),
            json.dumps(skill.tool_sequence, ensure_ascii=False),
            skill.system_prompt,
            json.dumps(skill.examples, ensure_ascii=False),
            source_task_id,
            skill.confidence
        ))
        self.ssot.conn.commit()

    def _reinforce_skill(self, skill_id: str, task_id: str):
        """기존 스킬 강화 (유사 태스크 성공 시)."""
        self.ssot.conn.execute("""
            UPDATE voyager_skills
            SET use_count = use_count + 1,
                success_count = success_count + 1,
                confidence = MIN(1.0, confidence + 0.05),
                updated_at = datetime('now')
            WHERE skill_id = ?
        """, (skill_id,))
        self.ssot.conn.commit()

    def record_use(self, skill_id: str, success: bool):
        """스킬 사용 기록."""
        if success:
            self.ssot.conn.execute("""
                UPDATE voyager_skills
                SET use_count = use_count + 1,
                    success_count = success_count + 1,
                    confidence = MIN(1.0, confidence + 0.03),
                    updated_at = datetime('now')
                WHERE skill_id = ?
            """, (skill_id,))
        else:
            self.ssot.conn.execute("""
                UPDATE voyager_skills
                SET use_count = use_count + 1,
                    confidence = MAX(0.1, confidence - 0.05),
                    updated_at = datetime('now')
                WHERE skill_id = ?
            """, (skill_id,))
        self.ssot.conn.commit()

    def deprecate_skill(self, skill_id: str):
        """스킬 비활성화."""
        self.ssot.conn.execute("""
            UPDATE voyager_skills
            SET status = 'deprecated', updated_at = datetime('now')
            WHERE skill_id = ?
        """, (skill_id,))
        self.ssot.conn.commit()
        logger.info(f"[Voyager] Deprecated skill: {skill_id}")

    def to_yaml(self, skill: VoyagerSkill) -> str:
        """스킬을 YAML 형식으로 변환."""
        import yaml
        data = {
            "name": skill.name,
            "description": skill.description,
            "intent_patterns": skill.intent_patterns,
            "allowed_tools": skill.allowed_tools,
            "system_prompt": skill.system_prompt,
            "examples": skill.examples
        }
        return yaml.dump(data, allow_unicode=True, default_flow_style=False)

    def get_stats(self) -> Dict[str, Any]:
        """Voyager 통계."""
        row = self.ssot.conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) as active,
                SUM(use_count) as total_uses,
                SUM(success_count) as total_successes,
                AVG(confidence) as avg_confidence
            FROM voyager_skills
        """).fetchone()

        return {
            "total_skills": row["total"] or 0,
            "active_skills": row["active"] or 0,
            "total_uses": row["total_uses"] or 0,
            "total_successes": row["total_successes"] or 0,
            "avg_confidence": round(row["avg_confidence"] or 0, 2)
        }
