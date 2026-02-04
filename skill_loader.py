"""REZE v6.0 Skill Loader - YAML 스킬 로딩 전용 모듈."""
import yaml
from pathlib import Path
from typing import Optional, List
from dataclasses import dataclass, field

import logging
logger = logging.getLogger("REZE.skills")


@dataclass
class DynamicSkill:
    """YAML 기반 동적 스킬 정의."""
    name: str
    description: str
    intent_patterns: List[str] = field(default_factory=list)
    allowed_tools: List[str] = field(default_factory=list)
    system_prompt: str = ""
    examples: List[dict] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "DynamicSkill":
        """딕셔너리에서 DynamicSkill 생성."""
        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            intent_patterns=data.get("intent_patterns", []),
            allowed_tools=data.get("allowed_tools", []),
            system_prompt=data.get("system_prompt", ""),
            examples=data.get("examples", []),
        )

    def get_tool_set(self) -> set:
        """허용된 도구 집합 반환."""
        return set(self.allowed_tools)


class SkillLoader:
    """skills/dynamic/*.yaml 스킬 로딩 클래스."""

    # 기본 허용 도구 (YAML에서 지정하지 않으면 이 도구들만 허용)
    DEFAULT_TOOLS = ["web_search", "web_fetch", "file_read", "python_exec"]

    def __init__(self, skills_dir: Path):
        self.skills_dir = skills_dir
        self.cache: dict[str, DynamicSkill] = {}

    def load_all(self) -> dict[str, DynamicSkill]:
        """skills/dynamic/*.yaml 모두 로드."""
        self.cache.clear()

        if not self.skills_dir.exists():
            logger.warning(f"Dynamic skills directory not found: {self.skills_dir}")
            return self.cache

        for yaml_file in sorted(self.skills_dir.glob("*.yaml")):
            if yaml_file.name.startswith("_"):
                continue  # _template.yaml 등 스킵

            try:
                skill = self._load_yaml(yaml_file)
                if skill and skill.name:
                    self.cache[skill.name] = skill
                    logger.debug(f"Loaded YAML skill: {skill.name}")
            except Exception as e:
                logger.warning(f"Failed to load YAML skill {yaml_file}: {e}")

        if self.cache:
            logger.info(f"Loaded {len(self.cache)} YAML skills: {list(self.cache.keys())}")

        return self.cache

    def _load_yaml(self, yaml_path: Path) -> Optional[DynamicSkill]:
        """단일 YAML 파일 로드."""
        try:
            content = yaml_path.read_text(encoding="utf-8")
            data = yaml.safe_load(content)

            if not data or not isinstance(data, dict):
                return None

            # allowed_tools가 없으면 기본값 사용
            if not data.get("allowed_tools"):
                data["allowed_tools"] = self.DEFAULT_TOOLS.copy()

            return DynamicSkill.from_dict(data)
        except yaml.YAMLError as e:
            logger.warning(f"YAML parse error in {yaml_path}: {e}")
            return None

    def load_one(self, name: str) -> Optional[DynamicSkill]:
        """단일 스킬 로드 (캐시 우선)."""
        if name in self.cache:
            return self.cache[name]

        yaml_path = self.skills_dir / f"{name}.yaml"
        if not yaml_path.exists():
            return None

        skill = self._load_yaml(yaml_path)
        if skill:
            self.cache[skill.name] = skill
        return skill

    def reload(self) -> int:
        """전체 리로드."""
        return len(self.load_all())

    def get_skill(self, name: str) -> Optional[DynamicSkill]:
        """스킬 조회."""
        return self.cache.get(name)

    def list_skills(self) -> List[str]:
        """스킬 이름 목록."""
        return list(self.cache.keys())

    def get_summary(self) -> str:
        """스킬 요약 (LLM 프롬프트용)."""
        if not self.cache:
            return "(no YAML skills loaded)"

        lines = []
        for name, skill in self.cache.items():
            lines.append(f"- yaml/{name}: {skill.description}")
        return "\n".join(lines)
