"""
REZE v6.0 Skills Manager
- 8개 메타스킬 + YAML configs 로딩
- 동적 스킬 (skills/dynamic/SKILL.md) 로딩
- v6.0 신규: YAML 동적 스킬 (skills/dynamic/*.yaml) + SkillClassifier
- 기존 _legacy/ 스킬은 무시
"""

import os
import re
import yaml
from pathlib import Path
from typing import Optional, Callable, Awaitable

import config
from skill_loader import SkillLoader, DynamicSkill
from skill_classifier import SkillClassifier

import logging
logger = logging.getLogger("REZE.skills")


class SkillsManager:
    """skills/ 디렉토리에서 메타스킬 + 동적 스킬을 스캔."""

    # 한글 조사 패턴
    KOREAN_PARTICLES = r'(?:에|을|를|이|가|는|은|의|와|과|로|으로|도|만|부터|까지|에서)?'

    def __init__(self, skills_dir: Optional[Path] = None):
        self.skills_dir = skills_dir or config.SKILLS_DIR
        self.catalog: dict[str, dict] = {}         # 메타스킬
        self.dynamic_catalog: dict[str, dict] = {} # 동적 생성 스킬 (SKILL.md 기반)

        # v6.0 신규: YAML 동적 스킬 시스템
        self.loader = SkillLoader(self.skills_dir / "dynamic")
        self.classifier = SkillClassifier()
        self.yaml_skills: dict[str, DynamicSkill] = {}

        self._load_meta_skills()
        self._load_dynamic_skills()
        self._load_yaml_skills()  # v6.0 신규

    def _load_meta_skills(self):
        """8개 메타스킬 + configs 로드"""
        if not self.skills_dir.exists():
            logger.warning(f"Skills directory not found: {self.skills_dir}")
            return

        for skill_dir in sorted(self.skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            # _legacy, dynamic, configs 제외
            if skill_dir.name.startswith('_') or skill_dir.name == 'dynamic':
                continue

            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue

            try:
                skill = self._parse_skill(skill_md)
                if skill and skill.get('name'):
                    skill['configs'] = self._load_configs(skill_dir)
                    skill['path'] = str(skill_md)
                    self.catalog[skill_dir.name] = skill
            except Exception as e:
                logger.warning(f"Failed to parse {skill_md}: {e}")

        logger.info(f"Loaded {len(self.catalog)} meta-skills: {list(self.catalog.keys())}")

    def _load_dynamic_skills(self):
        """skills/dynamic/ 에서 동적 스킬 로드"""
        dynamic_dir = self.skills_dir / "dynamic"
        if not dynamic_dir.exists():
            return

        for skill_dir in sorted(dynamic_dir.iterdir()):
            if not skill_dir.is_dir():
                continue

            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue

            try:
                skill = self._parse_skill(skill_md)
                if skill and skill.get('name'):
                    skill['configs'] = self._load_configs(skill_dir)
                    skill['path'] = str(skill_md)
                    if (skill_dir / "functions.py").exists():
                        skill['functions_path'] = str(skill_dir / "functions.py")
                    self.dynamic_catalog[skill_dir.name] = skill
            except Exception as e:
                logger.warning(f"Failed to parse dynamic skill {skill_md}: {e}")

        if self.dynamic_catalog:
            logger.info(f"Loaded {len(self.dynamic_catalog)} dynamic skills: {list(self.dynamic_catalog.keys())}")

    def _load_yaml_skills(self):
        """v6.0: YAML 동적 스킬 로드 (skills/dynamic/*.yaml)"""
        self.yaml_skills = self.loader.load_all()
        if self.yaml_skills:
            logger.info(f"Loaded {len(self.yaml_skills)} YAML skills: {list(self.yaml_skills.keys())}")

    def _parse_skill(self, skill_md_path: Path) -> Optional[dict]:
        """SKILL.md 파일에서 YAML frontmatter + content 파싱"""
        text = skill_md_path.read_text(encoding='utf-8')

        # YAML frontmatter 파싱
        meta = {}
        content = text
        if text.startswith("---"):
            end = text.find("---", 3)
            if end != -1:
                try:
                    meta = yaml.safe_load(text[3:end]) or {}
                except yaml.YAMLError as e:
                    logger.warning(f"YAML parse error in {skill_md_path}: {e}")
                    meta = {}
                content = text[end+3:].strip()

        meta['content'] = content
        return meta

    def _load_configs(self, skill_path: Path) -> dict:
        """configs/ 디렉토리에서 YAML 설정 로드"""
        configs = {}
        config_dir = skill_path / "configs"
        if not config_dir.exists():
            return configs

        for f in sorted(config_dir.iterdir()):
            if f.suffix == '.yaml' and not f.name.startswith('_'):
                name = f.stem
                try:
                    configs[name] = yaml.safe_load(f.read_text(encoding='utf-8'))
                except (yaml.YAMLError, IOError) as e:
                    logger.warning(f"Failed to load config {f}: {e}")

        return configs

    def scan(self) -> int:
        """스킬 카탈로그 새로고침"""
        self.catalog = {}
        self.dynamic_catalog = {}
        self.yaml_skills = {}
        self.classifier.clear_cache()  # v6.0: 패턴 캐시 초기화
        self._load_meta_skills()
        self._load_dynamic_skills()
        self._load_yaml_skills()  # v6.0 신규
        return len(self.catalog) + len(self.dynamic_catalog) + len(self.yaml_skills)

    def find_relevant(self, task: str) -> list[str]:
        """태스크에 관련된 메타스킬 + 동적 스킬 찾기"""
        matched = []
        task_lower = task.lower()

        # 메타스킬 검색
        for name, skill in self.catalog.items():
            triggers = skill.get('triggers', [])
            for trigger in triggers:
                trigger_str = str(trigger).lower()
                # 영문: word boundary
                if re.search(r'(?i)\b' + re.escape(trigger_str) + r'\b', task):
                    matched.append(name)
                    break
                # 한글: 조사 포함 매칭
                elif re.search(
                    r'(?i)(?:^|[\s,."\'!?:;()])' + re.escape(trigger_str) + self.KOREAN_PARTICLES + r'(?:[\s,."\'!?:;()]|$)',
                    task
                ):
                    matched.append(name)
                    break

        # 동적 스킬 검색
        for name, skill in self.dynamic_catalog.items():
            triggers = skill.get('triggers', [])
            for trigger in triggers:
                trigger_str = str(trigger).lower()
                if trigger_str in task_lower:
                    matched.append(f"dynamic/{name}")
                    break

        return matched

    def get_skill_with_config(self, skill_name: str, task: str) -> Optional[dict]:
        """메타스킬 + 적절한 config 반환"""
        # 동적 스킬인 경우
        if skill_name.startswith("dynamic/"):
            dyn_name = skill_name.replace("dynamic/", "")
            skill = self.dynamic_catalog.get(dyn_name)
            if not skill:
                return None
            return {
                'skill_md': skill.get('content', ''),
                'config': self._identify_target(task, skill.get('configs', {})),
                'name': skill_name,
                'is_dynamic': True
            }

        # 메타스킬인 경우
        skill = self.catalog.get(skill_name)
        if not skill:
            return None

        target_config = self._identify_target(task, skill.get('configs', {}))
        return {
            'skill_md': skill.get('content', ''),
            'config': target_config,
            'name': skill_name,
            'is_dynamic': False
        }

    def _identify_target(self, task: str, configs: dict) -> Optional[dict]:
        """태스크에서 대상 config 식별"""
        task_lower = task.lower()
        for config_name, config_data in configs.items():
            if not config_data:
                continue
            # config 이름으로 매칭
            if config_name in task_lower:
                return config_data
            # domain으로 매칭
            if config_data.get('domain', '') and config_data['domain'].lower() in task_lower:
                return config_data
            # name으로 매칭
            if config_data.get('name', '') and config_data['name'].lower() in task_lower:
                return config_data
        # 매칭 실패 시 None
        return None

    def load_skill(self, name: str) -> Optional[str]:
        """SKILL.md 전문 반환 (하위 호환)"""
        skill = self.catalog.get(name) or self.dynamic_catalog.get(name)
        if skill:
            return skill.get('content', '')
        return None

    def get_catalog_summary(self) -> str:
        """LLM 시스템 프롬프트에 넣을 스킬 목록 요약."""
        if not self.catalog and not self.dynamic_catalog and not self.yaml_skills:
            return "(no skills loaded)"

        lines = []
        for name, info in self.catalog.items():
            lines.append(f"- {name}: {info.get('description', '')}")
        for name, info in self.dynamic_catalog.items():
            lines.append(f"- dynamic/{name}: {info.get('description', '')}")
        # v6.0: YAML 스킬 추가
        for name, skill in self.yaml_skills.items():
            lines.append(f"- yaml/{name}: {skill.description}")
        return "\n".join(lines)

    # === v6.0: 스킬 분류 시스템 ===

    async def classify_task(
        self,
        task: str,
        llm_fn: Optional[Callable[[str], Awaitable[str]]] = None
    ) -> Optional[str]:
        """
        태스크를 적절한 스킬에 매핑.

        우선순위:
        1. 기존 메타스킬/동적스킬 (트리거 매칭)
        2. YAML 스킬 (패턴 매칭 → LLM 분류)

        Args:
            task: 분류할 태스크
            llm_fn: LLM 호출 함수 (선택적, 정밀 분류용)

        Returns:
            스킬 이름 (예: "blog-engine", "yaml/research-agent") 또는 None
        """
        # 1. 기존 트리거 매칭 시도
        matched = self.find_relevant(task)
        if matched:
            return matched[0]

        # 2. YAML 스킬 분류 시도
        yaml_match = await self.classifier.classify(
            task, self.yaml_skills, llm_fn
        )
        if yaml_match:
            return f"yaml/{yaml_match}"

        return None

    def get_yaml_skill(self, name: str) -> Optional[DynamicSkill]:
        """YAML 스킬 조회."""
        # yaml/ 프리픽스 제거
        if name.startswith("yaml/"):
            name = name[5:]
        return self.yaml_skills.get(name)

    def get_skill_info(self, skill_name: str) -> Optional[dict]:
        """
        스킬 정보 통합 조회.

        Returns:
            {
                'type': 'meta' | 'dynamic' | 'yaml',
                'name': str,
                'description': str,
                'allowed_tools': list (yaml 스킬만),
                'system_prompt': str (yaml 스킬만),
                'content': str (메타/동적 스킬만),
            }
        """
        # YAML 스킬
        if skill_name.startswith("yaml/"):
            skill = self.get_yaml_skill(skill_name)
            if skill:
                return {
                    'type': 'yaml',
                    'name': skill.name,
                    'description': skill.description,
                    'allowed_tools': skill.allowed_tools,
                    'system_prompt': skill.system_prompt,
                    'examples': skill.examples,
                }
            return None

        # 동적 스킬 (SKILL.md)
        if skill_name.startswith("dynamic/"):
            dyn_name = skill_name.replace("dynamic/", "")
            skill = self.dynamic_catalog.get(dyn_name)
            if skill:
                return {
                    'type': 'dynamic',
                    'name': skill_name,
                    'description': skill.get('description', ''),
                    'content': skill.get('content', ''),
                }
            return None

        # 메타스킬
        skill = self.catalog.get(skill_name)
        if skill:
            return {
                'type': 'meta',
                'name': skill_name,
                'description': skill.get('description', ''),
                'content': skill.get('content', ''),
            }

        return None
