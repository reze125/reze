"""
REZE v4.0 Dynamic Skill Creator
- 미지 도메인 감지 -> 인터넷 조사 -> SKILL.md + config YAML 자동 생성
- SSOT 등록
"""

import os
import json
from pathlib import Path
from typing import Optional

import logging
logger = logging.getLogger("REZE.skill_creator")


class DynamicSkillCreator:
    """새 도메인에 대한 스킬 자동 생성."""

    def __init__(self, call_llm_fn, ssot, skills_dir: str = None):
        """
        Args:
            call_llm_fn: LLM 호출 함수 (async, prompt + role 인자)
            ssot: SSOT 인스턴스
            skills_dir: 동적 스킬 저장 디렉토리
        """
        self.call_llm = call_llm_fn
        self.ssot = ssot
        self.skills_dir = Path(skills_dir) if skills_dir else Path.home() / "reze-agent" / "skills" / "dynamic"
        self.skills_dir.mkdir(parents=True, exist_ok=True)

    async def create_skill(self, domain: str, context: str,
                           trigger: str = "boss_command") -> dict:
        """
        새 도메인에 대한 스킬 자동 생성.

        Args:
            domain: 도메인명 (예: "reddit", "supabase", "minio")
            context: 태스크 컨텍스트 (왜 필요한지)
            trigger: 생성 트리거 (boss_command / unknown_service / no_skill_match)

        Returns:
            {"success": bool, "skill_path": str, "operations": list}
        """
        skill_name = f"{domain}-ops"
        skill_dir = self.skills_dir / skill_name

        # 이미 존재하면 스킵
        if skill_dir.exists():
            return {"success": True, "skill_path": str(skill_dir), "note": "already exists"}

        logger.info(f"Creating dynamic skill: {skill_name}")

        # 1. LLM으로 스킬 스펙 생성
        skill_spec = await self.call_llm(
            f"""너는 REZE 에이전트의 스킬 생성기다.
새 도메인 '{domain}'에 대한 운영 스킬을 생성하시오.

## 컨텍스트
{context}

## 생성 규칙
1. SKILL.md: YAML frontmatter(name, description, triggers, health_checks) + 핵심 워크플로우
2. config YAML: 도메인별 설정 (API URL, 인증 방법, 모니터링 대상 등)
3. 핵심 작업 목록: 이 도메인에서 수행 가능한 구체적 작업 5-10개

JSON 응답:
{{
    "skill_md": "전체 SKILL.md 텍스트",
    "config_yaml": "전체 config YAML 텍스트",
    "config_name": "config 파일명 (확장자 제외)",
    "operations": ["작업1", "작업2", ...],
    "triggers": ["트리거1", "트리거2", ...],
    "health_check_command": "헬스체크 셸 명령어"
}}""",
            role="writing"
        )

        try:
            # JSON 파싱
            text = skill_spec
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            spec = json.loads(text.strip())
        except Exception as e:
            logger.error(f"LLM output parsing failed: {e}")
            return {"success": False, "error": f"LLM output parsing failed: {e}"}

        # 2. 파일 생성
        try:
            skill_dir.mkdir(parents=True, exist_ok=True)
            configs_dir = skill_dir / "configs"
            configs_dir.mkdir(exist_ok=True)

            # SKILL.md
            skill_md_content = spec.get('skill_md', '')
            if not skill_md_content:
                skill_md_content = self._generate_default_skill_md(domain, spec)
            (skill_dir / "SKILL.md").write_text(skill_md_content)

            # config YAML
            config_name = spec.get('config_name', domain)
            config_yaml_content = spec.get('config_yaml', '')
            if config_yaml_content:
                (configs_dir / f"{config_name}.yaml").write_text(config_yaml_content)

            # 3. SSOT 등록
            self.ssot.conn.execute("""
                INSERT OR IGNORE INTO generated_skills
                (domain, type, skill_path, operations, creation_trigger)
                VALUES (?, ?, ?, ?, ?)
            """, [domain, "dynamic", str(skill_dir),
                  json.dumps(spec.get('operations', [])), trigger])
            self.ssot.conn.commit()

            logger.info(f"Dynamic skill created: {skill_name}")

            return {
                "success": True,
                "skill_path": str(skill_dir),
                "operations": spec.get('operations', [])
            }

        except Exception as e:
            logger.error(f"Skill creation failed: {e}")
            return {"success": False, "error": str(e)}

    def _generate_default_skill_md(self, domain: str, spec: dict) -> str:
        """기본 SKILL.md 생성."""
        triggers = spec.get('triggers', [domain])
        operations = spec.get('operations', ['status', 'health'])
        health_check = spec.get('health_check_command', 'echo "OK"')

        return f"""---
name: {domain}-ops
description: "{domain} 운영 자동화 스킬"
type: dynamic
triggers:
{chr(10).join(f'  - {t}' for t in triggers)}
health_checks:
  - name: {domain}_status
    command: "{health_check}"
    expect: "OK"
fix_actions: []
---

# {domain.title()}-Ops Dynamic Skill

{domain} 도메인 운영 자동화.

## 핵심 작업
{chr(10).join(f'- {op}' for op in operations)}

## 사용 방법
태스크에 '{domain}' 또는 관련 키워드가 포함되면 이 스킬이 매칭됩니다.
"""

    async def suggest_skill_for_unknown_domain(self, task: str) -> Optional[str]:
        """
        스킬 매칭 실패 시 새 스킬 생성 제안.

        Args:
            task: 매칭 실패한 태스크

        Returns:
            제안된 도메인명 또는 None
        """
        result = await self.call_llm(
            f"""태스크: {task}

이 태스크에 맞는 스킬이 없다.
새로 만들어야 할 스킬의 도메인 이름을 하나만 제안하라.
(예: reddit, supabase, minio, slack, telegram 등)

도메인 이름만 답하라. 없으면 'none'.""",
            role="classification"
        )

        domain = result.strip().lower()
        if domain and domain != 'none' and len(domain) < 30:
            return domain
        return None
