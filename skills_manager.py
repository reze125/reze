"""REZE Skills Manager — SKILL.md 기반 도메인 지식 로딩"""
import re
import yaml
from pathlib import Path
from typing import Optional

import config

import logging
logger = logging.getLogger("REZE.skills")


class SkillsManager:
    """skills/ 디렉토리에서 SKILL.md를 스캔하고, 태스크에 매칭되는 스킬을 찾는다."""

    def __init__(self, skills_dir: Optional[Path] = None):
        self.skills_dir = skills_dir or config.SKILLS_DIR
        self.catalog: dict[str, dict] = {}  # name → {description, triggers, path}
        self.scan()

    def scan(self) -> int:
        """skills/ 디렉토리 전체 스캔. YAML frontmatter 파싱."""
        self.catalog.clear()
        count = 0

        if not self.skills_dir.exists():
            logger.warning(f"Skills directory not found: {self.skills_dir}")
            return 0

        for skill_dir in sorted(self.skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                continue
            try:
                meta = self._parse_frontmatter(skill_file)
                if meta and "name" in meta:
                    self.catalog[meta["name"]] = {
                        "description": meta.get("description", ""),
                        "triggers": meta.get("triggers", []),
                        "path": str(skill_file),
                    }
                    count += 1
            except Exception as e:
                logger.warning(f"Failed to parse {skill_file}: {e}")

        logger.info(f"Loaded {count} skills: {list(self.catalog.keys())}")
        return count

    # 한글 조사 패턴 (trigger 뒤에 붙을 수 있는 조사들)
    KOREAN_PARTICLES = r'(?:에|을|를|이|가|는|은|의|와|과|로|으로|도|만|부터|까지|에서)?'

    def find_relevant(self, task: str) -> list[str]:
        """태스크 텍스트에서 trigger 키워드 매칭. word boundary + 한글 조사 처리."""
        matched = []
        for name, info in self.catalog.items():
            for trigger in info.get("triggers", []):
                trigger_str = str(trigger)
                # 영문: \b word boundary
                if re.search(r'(?i)\b' + re.escape(trigger_str) + r'\b', task):
                    matched.append(name)
                    break
                # 한글: 조사 포함 매칭 (블로그에, 서버를, 매출이 등)
                elif re.search(
                    r'(?i)(?:^|[\s,."\'!?:;()])' + re.escape(trigger_str) + self.KOREAN_PARTICLES + r'(?:[\s,."\'!?:;()]|$)',
                    task
                ):
                    matched.append(name)
                    break
        return matched

    def load_skill(self, name: str) -> Optional[str]:
        """스킬 전체 내용 로딩 (SKILL.md 전문 반환)."""
        if name not in self.catalog:
            return None
        try:
            with open(self.catalog[name]["path"], encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            logger.error(f"Failed to load skill {name}: {e}")
            return None

    def get_catalog_summary(self) -> str:
        """LLM 시스템 프롬프트에 넣을 스킬 목록 요약."""
        if not self.catalog:
            return "(no skills loaded)"
        lines = []
        for name, info in self.catalog.items():
            lines.append(f"- {name}: {info['description']}")
        return "\n".join(lines)

    def _parse_frontmatter(self, path: Path) -> Optional[dict]:
        """YAML frontmatter (--- ... ---) 파싱."""
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            return None
        end = text.find("---", 3)
        if end == -1:
            return None
        try:
            return yaml.safe_load(text[3:end])
        except yaml.YAMLError as e:
            logger.warning(f"YAML parse error in {path}: {e}")
            return None
