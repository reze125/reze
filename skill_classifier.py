"""REZE v6.0 Skill Classifier - 의미 기반 스킬 분류기.

v6.0 Phase 2 Gap Fix: Cerebras 직접 호출
- 분류는 10토큰이면 충분 → Cerebras가 가장 빠름
- Cerebras 실패 시에만 Groq로 폴백
- Cascade 거치지 않아 ~100ms (vs ~500ms)
"""
import re
import json
import asyncio
from typing import Optional, Callable, Awaitable, TYPE_CHECKING

import logging
logger = logging.getLogger("REZE.skills")

if TYPE_CHECKING:
    from skill_loader import DynamicSkill


class SkillClassifier:
    """태스크를 적절한 YAML 스킬에 매핑."""

    # 한글 조사 패턴
    KOREAN_PARTICLES = r'(?:에|을|를|이|가|는|은|의|와|과|로|으로|도|만|부터|까지|에서)?'

    def __init__(self):
        self._pattern_cache: dict[str, list] = {}
        self._cerebras_client = None
        self._groq_clients = None

    def _get_cerebras(self):
        """Cerebras 클라이언트 지연 로드."""
        if self._cerebras_client is None:
            try:
                from openai import OpenAI
                import config
                if config.CEREBRAS_API_KEY:
                    self._cerebras_client = OpenAI(
                        base_url=config.CEREBRAS_BASE_URL,
                        api_key=config.CEREBRAS_API_KEY
                    )
            except Exception as e:
                logger.warning(f"Cerebras client init failed: {e}")
        return self._cerebras_client

    def _get_groq(self):
        """Groq 클라이언트 지연 로드."""
        if self._groq_clients is None:
            try:
                from groq import Groq
                import config
                keys = config.GROQ_API_KEYS if config.GROQ_API_KEYS else [config.GROQ_API_KEY]
                self._groq_clients = [Groq(api_key=k) for k in keys if k]
            except Exception as e:
                logger.warning(f"Groq client init failed: {e}")
                self._groq_clients = []
        return self._groq_clients

    async def _call_cerebras_direct(self, prompt: str, max_tokens: int = 20) -> Optional[str]:
        """Cerebras 직접 호출 (분류 전용, 매우 빠름)."""
        client = self._get_cerebras()
        if not client:
            return None

        try:
            import config
            loop = asyncio.get_event_loop()

            def _sync_call():
                resp = client.chat.completions.create(
                    model=config.CEREBRAS_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=max_tokens,
                    temperature=0.1
                )
                return resp.choices[0].message.content or ""

            result = await loop.run_in_executor(None, _sync_call)
            logger.debug(f"[SkillClassifier] Cerebras direct: {result[:50]}")
            return result
        except Exception as e:
            logger.warning(f"Cerebras direct call failed: {e}")
            return None

    async def _call_groq_fallback(self, prompt: str, max_tokens: int = 20) -> Optional[str]:
        """Groq 폴백 (Cerebras 실패 시)."""
        clients = self._get_groq()
        if not clients:
            return None

        try:
            import config
            client = clients[0]  # 첫 번째 클라이언트 사용
            loop = asyncio.get_event_loop()

            def _sync_call():
                resp = client.chat.completions.create(
                    model=config.GROQ_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=max_tokens,
                    temperature=0.1
                )
                return resp.choices[0].message.content or ""

            result = await loop.run_in_executor(None, _sync_call)
            logger.debug(f"[SkillClassifier] Groq fallback: {result[:50]}")
            return result
        except Exception as e:
            logger.warning(f"Groq fallback failed: {e}")
            return None

    def _compile_patterns(self, skill_name: str, patterns: list[str]) -> list:
        """intent_patterns를 컴파일된 regex로 변환."""
        if skill_name in self._pattern_cache:
            return self._pattern_cache[skill_name]

        compiled = []
        for pattern in patterns:
            try:
                # 파이프(|)로 분리된 패턴은 OR 조건
                if "|" in pattern:
                    # 각 부분을 이스케이프하고 OR로 결합
                    parts = [re.escape(p.strip()) for p in pattern.split("|")]
                    regex_str = "|".join(parts)
                else:
                    regex_str = re.escape(pattern)

                # 한글 조사 허용
                regex_str = f"(?:{regex_str}){self.KOREAN_PARTICLES}"
                compiled.append(re.compile(regex_str, re.IGNORECASE))
            except re.error as e:
                logger.warning(f"Invalid pattern '{pattern}' in skill {skill_name}: {e}")

        self._pattern_cache[skill_name] = compiled
        return compiled

    def classify_fast(
        self, task: str, skills: dict[str, "DynamicSkill"]
    ) -> Optional[str]:
        """
        빠른 분류 (패턴 매칭).
        intent_patterns를 사용해 태스크와 매칭.
        """
        task_lower = task.lower()
        matches = []

        for skill_name, skill in skills.items():
            patterns = self._compile_patterns(skill_name, skill.intent_patterns)
            match_count = 0

            for regex in patterns:
                if regex.search(task_lower):
                    match_count += 1

            if match_count > 0:
                matches.append((skill_name, match_count))

        if not matches:
            return None

        # 가장 많이 매칭된 스킬 반환
        matches.sort(key=lambda x: x[1], reverse=True)
        return matches[0][0]

    async def classify_precise(
        self,
        task: str,
        skills: dict[str, "DynamicSkill"],
        llm_fn: Callable[[str], Awaitable[str]] = None,
    ) -> Optional[str]:
        """
        정밀 분류 (LLM 사용).

        v6.0 Phase 2 Gap Fix:
        1. Cerebras 직접 호출 먼저 시도 (가장 빠름, ~100ms)
        2. Cerebras 실패 시 Groq 폴백
        3. 둘 다 실패 시 외부 llm_fn 사용 (Cascade)
        """
        if not skills:
            return None

        # 스킬 목록 구성
        skill_list = []
        for name, skill in skills.items():
            skill_list.append(f"- {name}: {skill.description}")

        prompt = f"""아래 태스크에 가장 적합한 스킬을 선택하세요.

## 태스크
{task}

## 사용 가능한 스킬
{chr(10).join(skill_list)}

## 응답 형식
스킬 이름만 출력하세요. 적합한 스킬이 없으면 "none"을 출력하세요.

응답:"""

        response = None

        # 1. Cerebras 직접 호출 (최우선, 가장 빠름)
        response = await self._call_cerebras_direct(prompt, max_tokens=20)

        # 2. Groq 폴백
        if not response:
            response = await self._call_groq_fallback(prompt, max_tokens=20)

        # 3. 외부 llm_fn 폴백 (최후 수단)
        if not response and llm_fn:
            try:
                response = await llm_fn(prompt)
            except Exception as e:
                logger.warning(f"External LLM classification failed: {e}")
                return None

        if not response:
            return None

        response = response.strip().lower()

        # "none" 응답 처리
        if response in ("none", "없음", "null", ""):
            return None

        # 스킬 이름 추출 (응답에 추가 텍스트가 있을 수 있음)
        for skill_name in skills.keys():
            if skill_name.lower() in response:
                return skill_name

        return None

    async def classify(
        self,
        task: str,
        skills: dict[str, "DynamicSkill"],
        llm_fn: Optional[Callable[[str], Awaitable[str]]] = None,
    ) -> Optional[str]:
        """
        2단계 분류: fast 시도 → 실패 시 precise.

        Args:
            task: 분류할 태스크
            skills: 스킬 딕셔너리
            llm_fn: LLM 호출 함수 (선택적)

        Returns:
            매칭된 스킬 이름 또는 None
        """
        # 1단계: 빠른 분류 시도
        result = self.classify_fast(task, skills)
        if result:
            logger.debug(f"Fast classification: '{task[:50]}...' → {result}")
            return result

        # 2단계: LLM 기반 분류 (llm_fn이 제공된 경우만)
        if llm_fn is not None:
            result = await self.classify_precise(task, skills, llm_fn)
            if result:
                logger.debug(f"Precise classification: '{task[:50]}...' → {result}")
                return result

        return None

    def clear_cache(self):
        """패턴 캐시 초기화."""
        self._pattern_cache.clear()
