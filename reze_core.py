"""REZE Core — LLM Provider 래퍼 + ModelRouter + ReAct 엔진"""
import json
import re
import time
import asyncio
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol
from collections import deque

from pydantic import BaseModel
from openai import OpenAI
from groq import Groq
from google import genai

import config
from ssot import SSOT
from reze_tools import ToolExecutor
from reze_permissions import PermissionSystem
from skills_manager import SkillsManager
from redaction import mask_text

import logging
logger = logging.getLogger("REZE.core")


# ============================================================
# 1. LLMResponse
# ============================================================

@dataclass
class LLMResponse:
    """모든 Provider가 반환하는 통일된 응답 형식."""
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    model: str = ""
    provider: str = ""


# ============================================================
# 2. ToolChoice (Pydantic — instructor용)
# ============================================================

class ToolChoice(BaseModel):
    thought: str
    tool: str       # shell | python | http | filesystem | web_search | final_answer
    input: Any


# ============================================================
# 3. CerebrasProvider
# ============================================================

class CerebrasProvider:
    """Cerebras API (OpenAI SDK 호환). qwen-3-235b."""

    def __init__(self):
        self.client = OpenAI(
            base_url=config.CEREBRAS_BASE_URL,
            api_key=config.CEREBRAS_API_KEY,
        )
        self.model = config.CEREBRAS_MODEL
        self.name = "cerebras"

    async def call(self, messages: list[dict], system: str = "",
                   **kwargs) -> LLMResponse:
        """비동기 래퍼 (내부는 동기 호출을 executor로 감쌈)."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._call_sync, messages, system, kwargs
        )

    def _call_sync(self, messages: list[dict], system: str,
                   kwargs: dict) -> LLMResponse:
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.extend(messages)

        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=msgs,
                max_tokens=kwargs.get("max_tokens", 2000),
                temperature=kwargs.get("temperature", 0.3),
            )
            text = resp.choices[0].message.content or ""
            usage = resp.usage
            return LLMResponse(
                text=text,
                input_tokens=usage.prompt_tokens if usage else 0,
                output_tokens=usage.completion_tokens if usage else 0,
                total_tokens=usage.total_tokens if usage else 0,
                model=self.model,
                provider=self.name,
            )
        except Exception as e:
            logger.error(f"Cerebras call failed: {e}")
            raise


# ============================================================
# 4. GroqProvider
# ============================================================

class GroqProvider:
    """Groq API. 5키 라운드로빈."""

    def __init__(self):
        self.keys = config.GROQ_API_KEYS if config.GROQ_API_KEYS else [config.GROQ_API_KEY]
        self._key_index = 0
        self.model = config.GROQ_MODEL
        self.name = "groq"

    def _next_client(self) -> Groq:
        """라운드로빈으로 다음 키 선택."""
        key = self.keys[self._key_index % len(self.keys)]
        self._key_index += 1
        return Groq(api_key=key)

    async def call(self, messages: list[dict], system: str = "",
                   **kwargs) -> LLMResponse:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._call_sync, messages, system, kwargs
        )

    def _call_sync(self, messages: list[dict], system: str,
                   kwargs: dict) -> LLMResponse:
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.extend(messages)

        last_error = None
        for attempt in range(len(self.keys)):
            client = self._next_client()
            try:
                resp = client.chat.completions.create(
                    model=self.model,
                    messages=msgs,
                    max_tokens=kwargs.get("max_tokens", 2000),
                    temperature=kwargs.get("temperature", 0.3),
                )
                text = resp.choices[0].message.content or ""
                usage = resp.usage
                return LLMResponse(
                    text=text,
                    input_tokens=usage.prompt_tokens if usage else 0,
                    output_tokens=usage.completion_tokens if usage else 0,
                    total_tokens=usage.total_tokens if usage else 0,
                    model=self.model,
                    provider=self.name,
                )
            except Exception as e:
                last_error = e
                error_str = str(e).lower()
                if "429" in str(e) or "rate" in error_str or "quota" in error_str:
                    logger.warning(f"Groq key {self._key_index - 1} rate limited, trying next")
                    continue
                else:
                    logger.error(f"Groq call failed (non-rate-limit): {e}")
                    raise

        raise RuntimeError(f"All {len(self.keys)} Groq keys exhausted: {last_error}")


# ============================================================
# 5. GeminiProvider
# ============================================================

class GeminiProvider:
    """Google Gemini API (google-genai 패키지). 5키 라운드로빈."""

    def __init__(self, model: str = None, provider_name: str = None):
        self.keys = list(config.GEMINI_API_KEYS)
        if not self.keys:
            raise ValueError("GEMINI_API_KEYS not configured")
        self.model = model or config.GEMINI_PRO_MODEL
        self.name = provider_name or "gemini_pro"
        self._key_index = 0

    def _next_client(self) -> genai.Client:
        """라운드로빈으로 다음 키 선택."""
        key = self.keys[self._key_index % len(self.keys)]
        self._key_index += 1
        return genai.Client(api_key=key)

    async def call(self, messages: list[dict], system: str = "",
                   **kwargs) -> LLMResponse:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._call_sync, messages, system, kwargs
        )

    def _call_sync(self, messages: list[dict], system: str,
                   kwargs: dict) -> LLMResponse:
        # messages를 Gemini 형식으로 변환
        contents = self._convert_messages(messages)

        # 5키 전부 시도
        last_error = None
        for attempt in range(len(self.keys)):
            client = self._next_client()
            try:
                gen_config = {
                    "max_output_tokens": kwargs.get("max_tokens", 2000),
                    "temperature": kwargs.get("temperature", 0.3),
                }

                response = client.models.generate_content(
                    model=self.model,
                    contents=contents,
                    config=genai.types.GenerateContentConfig(
                        system_instruction=system if system else None,
                        max_output_tokens=gen_config["max_output_tokens"],
                        temperature=gen_config["temperature"],
                    ),
                )

                text = response.text or ""
                # 토큰 사용량 추출
                usage = getattr(response, 'usage_metadata', None)
                input_tokens = getattr(usage, 'prompt_token_count', 0) if usage else 0
                output_tokens = getattr(usage, 'candidates_token_count', 0) if usage else 0

                return LLMResponse(
                    text=text,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=input_tokens + output_tokens,
                    model=self.model,
                    provider=self.name,
                )
            except Exception as e:
                last_error = e
                error_str = str(e).lower()
                if "429" in error_str or "quota" in error_str or "rate" in error_str:
                    logger.warning(f"Gemini key {self._key_index - 1} rate limited, trying next")
                    continue
                else:
                    logger.error(f"Gemini call failed (non-rate-limit): {e}")
                    raise

        raise RuntimeError(f"All {len(self.keys)} Gemini keys exhausted: {last_error}")

    def _convert_messages(self, messages: list[dict]) -> list:
        """OpenAI 형식 messages → Gemini contents 변환."""
        contents = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            # Gemini는 role이 "user" 또는 "model"
            gemini_role = "model" if role == "assistant" else "user"
            # system은 별도 처리 (config에서)
            if role == "system":
                continue
            contents.append({"role": gemini_role, "parts": [{"text": content}]})

        # 연속된 같은 role 합치기 (Gemini 요구사항)
        merged = []
        for c in contents:
            if merged and merged[-1]["role"] == c["role"]:
                merged[-1]["parts"].extend(c["parts"])
            else:
                merged.append(c)

        return merged if merged else [{"role": "user", "parts": [{"text": "Hello"}]}]


# ============================================================
# 5.5 OpenRouterProvider (최후 폴백)
# ============================================================

class OpenRouterProvider:
    """OpenRouter API (OpenAI SDK 호환). DeepSeek V3."""

    def __init__(self):
        self.client = OpenAI(
            base_url=config.OPENROUTER_BASE_URL,
            api_key=config.OPENROUTER_API_KEY,
        )
        self.model = config.OPENROUTER_MODEL
        self.name = "openrouter"

    async def call(self, messages: list[dict], system: str = "",
                   **kwargs) -> LLMResponse:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._call_sync, messages, system, kwargs
        )

    def _call_sync(self, messages: list[dict], system: str,
                   kwargs: dict) -> LLMResponse:
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.extend(messages)

        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=msgs,
                max_tokens=kwargs.get("max_tokens", 2000),
                temperature=kwargs.get("temperature", 0.3),
            )
            text = resp.choices[0].message.content or ""
            usage = resp.usage
            return LLMResponse(
                text=text,
                input_tokens=usage.prompt_tokens if usage else 0,
                output_tokens=usage.completion_tokens if usage else 0,
                total_tokens=usage.total_tokens if usage else 0,
                model=self.model,
                provider=self.name,
            )
        except Exception as e:
            logger.error(f"OpenRouter call failed: {e}")
            raise


# ============================================================
# 6. ModelRouter
# ============================================================

class ModelRouter:
    """역할 기반 LLM 라우팅 + 폴백 체인."""

    # 역할 → provider 매핑 (v4.0 최적화)
    ROLE_ASSIGNMENT = {
        # 콘텐츠 생성 = Gemini Pro (품질 최우선)
        "writing": "gemini_pro",        # 블로그 글, 리포트, 이메일 본문
        "analysis": "gemini_pro",       # 분석 리포트
        "creative": "gemini_pro",       # 창의적 콘텐츠

        # 판단/분류 = Groq (빠른 판단)
        "reasoning": "groq",            # 논리적 추론
        "classification": "groq",       # 분류, 태스크 라우팅
        "evaluation": "groq",           # 품질 채점 (크로스 리뷰)
        "planning": "groq",             # 계획 수립
        "critic": "groq",               # 비평

        # 도구 선택 = Cerebras (최고 속도)
        "tool_call": "cerebras",        # 도구 선택/호출
        "extraction": "cerebras",       # 정보 추출
        "quick": "cerebras",            # 간단한 질의

        # 셀프 리플렉션 = Gemini Flash (깊은 반성)
        "reflection": "gemini_flash",   # 태스크 반성/교훈 추출
        "research": "gemini_flash",     # 웹 리서치 정리
        "final_review": "gemini_flash", # 최종 검토
        "summarization": "gemini_flash", # 요약
    }

    # 폴백 순서
    FALLBACK_CHAIN = {
        "cerebras": ["groq", "gemini_flash", "openrouter"],
        "groq": ["cerebras", "gemini_flash", "openrouter"],
        "gemini_pro": ["gemini_flash", "groq", "openrouter"],
        "gemini_flash": ["gemini_pro", "groq", "openrouter"],
        "openrouter": ["cerebras", "groq", "gemini_flash"],
    }

    def __init__(self, ssot: SSOT):
        self.ssot = ssot
        self.providers: dict = {}
        self._init_providers()

    def _init_providers(self):
        """사용 가능한 Provider만 초기화."""
        try:
            if config.CEREBRAS_API_KEY:
                self.providers["cerebras"] = CerebrasProvider()
                logger.info("Cerebras provider initialized")
        except Exception as e:
            logger.warning(f"Cerebras init failed: {e}")

        try:
            if config.GROQ_API_KEY:
                self.providers["groq"] = GroqProvider()
                logger.info("Groq provider initialized")
        except Exception as e:
            logger.warning(f"Groq init failed: {e}")

        try:
            if config.GEMINI_API_KEYS:
                self.providers["gemini_pro"] = GeminiProvider(
                    model=config.GEMINI_PRO_MODEL,
                    provider_name="gemini_pro"
                )
                self.providers["gemini_flash"] = GeminiProvider(
                    model=config.GEMINI_FLASH_MODEL,
                    provider_name="gemini_flash"
                )
                logger.info("Gemini providers initialized (Pro + Flash)")
        except Exception as e:
            logger.warning(f"Gemini init failed: {e}")

        try:
            if config.OPENROUTER_API_KEY:
                self.providers["openrouter"] = OpenRouterProvider()
                logger.info("OpenRouter provider initialized")
        except Exception as e:
            logger.warning(f"OpenRouter init failed: {e}")

        if not self.providers:
            raise RuntimeError("No LLM providers available!")

        logger.info(f"Available providers: {list(self.providers.keys())}")

    async def call(self, step_type: str, messages: list[dict],
                   system: str = "", trace_id: str = None, **kwargs) -> LLMResponse:
        """역할 기반 호출. 실패 시 폴백. trace_id가 있으면 traces 테이블에 기록."""
        # 1. 역할에 맞는 provider 선택
        target = self.ROLE_ASSIGNMENT.get(step_type, "cerebras")

        # 2. 시도 순서 결정
        try_order = [target] + self.FALLBACK_CHAIN.get(target, [])

        # 3. 순서대로 시도
        last_error = None
        for provider_name in try_order:
            if provider_name not in self.providers:
                continue

            # 일일 한도 체크
            calls = self.ssot.get_provider_calls(provider_name)
            limit = config.PROVIDER_DAILY_LIMITS.get(provider_name, 999_999)
            if calls >= limit:
                logger.warning(f"{provider_name} daily limit reached ({calls}/{limit})")
                continue

            start = time.monotonic()
            try:
                provider = self.providers[provider_name]
                response = await provider.call(messages, system=system, **kwargs)
                latency = int((time.monotonic() - start) * 1000)

                # 사용량 기록
                self.ssot.add_tokens(response.total_tokens)
                self.ssot.increment_provider_calls(provider_name)

                # traces 기록
                if trace_id:
                    self.ssot.log_trace(
                        trace_id, 'llm_call', provider_name, response.model,
                        response.input_tokens, response.output_tokens,
                        latency, 'ok' if provider_name == target else 'fallback'
                    )

                if provider_name != target:
                    logger.info(f"Fallback: {target} → {provider_name} for {step_type}")

                return response

            except Exception as e:
                latency = int((time.monotonic() - start) * 1000)
                last_error = e
                logger.warning(f"{provider_name} failed for {step_type}: {e}")

                # 에러 trace
                if trace_id:
                    error_type = 'rate_limit' if '429' in str(e) else (
                        'timeout' if 'timeout' in str(e).lower() else 'other'
                    )
                    self.ssot.log_trace(
                        trace_id, 'llm_call', provider_name, '',
                        0, 0, latency, 'error', error_type, str(e)[:500]
                    )
                continue

        raise RuntimeError(f"All providers failed for {step_type}: {last_error}")


# ============================================================
# 7. OutputValidator
# ============================================================

class OutputValidator:
    """LLM 출력을 JSON으로 파싱. 6단계 폴백."""

    def parse(self, text: str) -> dict:
        """텍스트 → dict. 실패 시 final_answer로 강제."""
        if not text or not text.strip():
            return {"thought": "empty response", "tool": "final_answer", "input": "No response from LLM"}

        # 1차: 직접 json.loads
        try:
            result = json.loads(text.strip())
            if self._is_valid(result):
                return result
        except json.JSONDecodeError:
            pass

        # 2차: markdown fence 제거
        cleaned = re.sub(r'^```(?:json)?\s*\n?', '', text.strip())
        cleaned = re.sub(r'\n?```\s*$', '', cleaned).strip()
        try:
            result = json.loads(cleaned)
            if self._is_valid(result):
                return result
        except json.JSONDecodeError:
            pass

        # 3차: bracket counting — 첫 { 부터 매칭 } 까지
        extracted = self._extract_json_bracket(text)
        if extracted:
            try:
                result = json.loads(extracted)
                if self._is_valid(result):
                    return result
            except json.JSONDecodeError:
                pass

        # 4차: regex 폴백
        match = re.search(r'\{[^{}]*"tool"\s*:\s*"[^"]+?"[^{}]*\}', text, re.DOTALL)
        if match:
            try:
                result = json.loads(match.group())
                if self._is_valid(result):
                    return result
            except json.JSONDecodeError:
                pass

        # 5차: 개별 필드 추출
        thought_match = re.search(r'"thought"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
        tool_match = re.search(r'"tool"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
        input_match = re.search(r'"input"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
        if tool_match:
            return {
                "thought": thought_match.group(1) if thought_match else "",
                "tool": tool_match.group(1),
                "input": input_match.group(1) if input_match else "",
            }

        # 6차: final_answer 강제
        logger.warning(f"OutputValidator: all parsing failed, forcing final_answer")
        return {
            "thought": "Failed to parse structured output",
            "tool": "final_answer",
            "input": text[:1000],
        }

    def _is_valid(self, d: dict) -> bool:
        """최소 요구 필드 확인."""
        return isinstance(d, dict) and "tool" in d

    def _extract_json_bracket(self, text: str) -> Optional[str]:
        """첫 { 부터 매칭 } 까지 추출. 따옴표 추적."""
        start = text.find('{')
        if start == -1:
            return None

        depth = 0
        in_string = False
        escape = False

        for i in range(start, len(text)):
            c = text[i]
            if escape:
                escape = False
                continue
            if c == '\\' and in_string:
                escape = True
                continue
            if c == '"' and not escape:
                in_string = not in_string
                continue
            if in_string:
                continue
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    return text[start:i+1]
        return None


# ============================================================
# 8. CircuitBreaker
# ============================================================

class CircuitBreaker:
    """예산/스텝/루프 제한."""

    def __init__(self, ssot: SSOT):
        self.ssot = ssot

    def check_budget(self) -> bool:
        """일일 토큰 예산 내인지. True = OK."""
        current = self.ssot.get_daily_tokens()
        ok = current < config.DAILY_TOKEN_BUDGET
        if not ok:
            logger.warning(f"Daily budget exceeded: {current}/{config.DAILY_TOKEN_BUDGET}")
        return ok

    def check_step_limit(self, current_step: int) -> bool:
        """스텝 한도 초과 여부. True = 초과 (중단해야 함)."""
        exceeded = current_step >= config.MAX_ITERATIONS
        if exceeded:
            logger.warning(f"Step limit reached: {current_step}/{config.MAX_ITERATIONS}")
        return exceeded

    def check_loop(self, recent_actions: deque, current_action: str) -> bool:
        """동일 행동 3회 반복 감지. True = 루프 감지."""
        if len(recent_actions) >= 3:
            last_three = list(recent_actions)[-3:]
            if all(a == current_action for a in last_three):
                logger.warning(f"Loop detected: '{current_action}' repeated 3 times")
                return True
        return False

    def record_usage(self, provider: str, tokens: int):
        """사용량 기록 (ModelRouter에서도 하지만 명시적 호출용)."""
        self.ssot.add_tokens(tokens)


# ============================================================
# 9. REZECore — 메인 ReAct 엔진
# ============================================================

class REZECore:
    """REZE의 두뇌. 자연어 태스크 → 도구 조합 → 결과."""

    def __init__(
        self,
        ssot: SSOT,
        tools: ToolExecutor,
        permissions: PermissionSystem,
        router: ModelRouter,
        skills_manager: SkillsManager,
        circuit_breaker: CircuitBreaker,
    ):
        self.ssot = ssot
        self.tools = tools
        self.permissions = permissions
        self.router = router
        self.skills_manager = skills_manager
        self.circuit_breaker = circuit_breaker
        self.output_validator = OutputValidator()

    async def run(self, task: str, source: str = "api") -> dict:
        """메인 ReAct 루프 (v4.0: 학습 루프 통합)."""
        logger.info(f"Task started: {task[:100]} (source={source})")

        # trace_id 생성
        trace_id = self.ssot._new_id("trace")

        # ── v4.0: 과거 경험 조회 ──
        cached = self.ssot.find_cached_plan_v4(task)
        reflections = self.ssot.get_recent_reflections_v4(limit=3)

        experience_context = ""
        if cached:
            experience_context += f"\n\n[이전 성공 절차 참고]\n{cached['procedure']}"
            self.ssot.increment_plan_usage_v4(cached['task_pattern'])
            logger.info(f"Found cached plan: score={cached['score']}")
        if reflections:
            experience_context += "\n\n[과거 교훈 — 이 실수를 반복하지 마시오]"
            for r in reflections:
                experience_context += f"\n- {r['lesson']}: {r.get('suggested_approach', '')}"

        # 1. 스킬 매칭
        relevant_skills = self.skills_manager.find_relevant(task)
        skill_context = ""
        for skill_name in relevant_skills:
            content = self.skills_manager.load_skill(skill_name)
            if content:
                skill_context += f"\n\n--- Skill: {skill_name} ---\n{content}"
        if relevant_skills:
            logger.info(f"Skills matched: {relevant_skills}")

        # 2. 시스템 프롬프트 (v4.0: 경험 컨텍스트 포함)
        system_prompt = self._build_system_prompt(skill_context + experience_context)

        # 3. SSOT 태스크 기록
        task_id = self.ssot.create_task(task)

        # 4. ReAct 루프
        messages = [{"role": "user", "content": task}]
        recent_actions: deque = deque(maxlen=5)
        consecutive_failures = 0
        total_tokens_used = 0

        for step in range(config.MAX_ITERATIONS):
            # --- Circuit Breaker 체크 ---
            if not self.circuit_breaker.check_budget():
                self.ssot.complete_task(task_id, "budget_exceeded", "Daily token budget exceeded")
                return self._result(False, "Daily token budget exceeded", task_id, step + 1, total_tokens_used)

            if self.circuit_breaker.check_step_limit(step):
                break

            # --- LLM 호출 ---
            # 메시지 truncation (128K 컨텍스트 초과 방지)
            if len(messages) > 10:
                messages = [messages[0]] + messages[-8:]

            try:
                response = await self.router.call(
                    "tool_call", messages, system=system_prompt, trace_id=trace_id
                )
            except Exception as e:
                logger.error(f"LLM call failed at step {step + 1}: {e}")
                self.ssot.complete_task(task_id, "error", f"LLM call failed: {e}")
                return self._result(False, f"LLM call failed: {e}", task_id, step + 1, total_tokens_used)

            total_tokens_used += response.total_tokens

            # --- 파싱 ---
            parsed = self.output_validator.parse(response.text)

            # --- SSOT 기록 ---
            iter_id = self.ssot.log_iteration(
                task_id, step + 1,
                parsed.get("thought", ""),
                parsed.get("tool", "unknown"),
                str(parsed.get("input", ""))[:2000],
            )

            # --- final_answer 체크 ---
            if parsed.get("tool") == "final_answer":
                answer = str(parsed.get("input", ""))
                self.ssot.update_iteration(iter_id, "FINAL_ANSWER", True)
                self.ssot.complete_task(task_id, "success", answer)
                logger.info(f"Task completed: {task_id} in {step + 1} steps, {total_tokens_used} tokens")

                # ── v4.0: 성공 시 plan_cache 저장 ──
                if step >= 1:  # 최소 2스텝 이상 걸린 태스크만
                    try:
                        procedure = self._extract_procedure(messages)
                        self.ssot.cache_plan_v4(
                            task_pattern=self._abstract_task(task),
                            skills_used=relevant_skills,
                            procedure=procedure,
                            steps=step + 1,
                            tokens=total_tokens_used,
                            score=0.8
                        )
                    except Exception as e:
                        logger.warning(f"Plan cache save failed: {e}")

                # ── v4.0: 반성 + 교훈 추출 ──
                result = self._result(True, answer, task_id, step + 1, total_tokens_used,
                                      skills_used=relevant_skills, quality_score=0.8)
                try:
                    await self._reflect_and_learn(task, result)
                except Exception as e:
                    logger.warning(f"Reflect and learn failed: {e}")

                return result

            # --- 루프 감지 ---
            current_action = f"{parsed['tool']}:{str(parsed.get('input', ''))[:100]}"
            if self.circuit_breaker.check_loop(recent_actions, current_action):
                # 루프 감지 시 강제 reflection
                messages.append({"role": "assistant", "content": response.text})
                messages.append({
                    "role": "user",
                    "content": "WARNING: 같은 행동을 3번 반복했습니다. 다른 접근 방식을 시도하세요. 현재 방법이 작동하지 않으면 final_answer로 현재까지의 결과를 보고하세요."
                })
                recent_actions.clear()
                continue
            recent_actions.append(current_action)

            # --- 도구 실행 ---
            tool_name = parsed.get("tool", "")
            tool_input = parsed.get("input", "")

            observation = await self.tools.execute(tool_name, tool_input, source=source)

            # --- Observation 트리밍 ---
            if len(observation) > config.MAX_OBSERVATION_CHARS:
                observation = observation[:config.MAX_OBSERVATION_CHARS] + "\n...(truncated)"

            # --- SSOT 업데이트 ---
            is_success = not observation.startswith("ERROR") and not observation.startswith("BLOCKED")
            self.ssot.update_iteration(iter_id, observation, is_success)

            # 도구 실행 trace
            self.ssot.log_trace(
                trace_id, 'tool_exec', tool_name, '',
                0, 0, 0, 'ok' if is_success else 'error',
                metadata=str(tool_input)[:200]
            )

            # --- 대화에 추가 ---
            messages.append({"role": "assistant", "content": response.text})
            messages.append({"role": "user", "content": f"Observation:\n{observation}"})

            # --- Reflexion (연속 실패) ---
            if not is_success:
                consecutive_failures += 1
                if consecutive_failures >= config.REFLECTION_THRESHOLD:
                    try:
                        reflection_resp = await self.router.call(
                            "reflection",
                            [{
                                "role": "user",
                                "content": (
                                    f"Task: {task}\n\n"
                                    f"최근 {consecutive_failures}번 연속 실패했습니다.\n"
                                    f"마지막 에러: {observation[:500]}\n\n"
                                    "무엇이 잘못되었는지 분석하고, 다른 접근 방식을 제안하세요."
                                )
                            }],
                            system="당신은 AI 에이전트의 실패를 분석하는 전문가입니다. 간결하게 핵심만 말하세요.",
                            trace_id=trace_id
                        )
                        total_tokens_used += reflection_resp.total_tokens
                        messages.append({
                            "role": "user",
                            "content": f"Reflection:\n{reflection_resp.text}"
                        })
                        self.ssot.log_reflection(task_id, observation[:500], reflection_resp.text[:500])
                        logger.info(f"Reflection triggered after {consecutive_failures} failures")
                    except Exception as e:
                        logger.warning(f"Reflection call failed: {e}")
                    consecutive_failures = 0
            else:
                consecutive_failures = 0

        # --- 루프 종료 (미완료) ---
        self.ssot.complete_task(task_id, "incomplete", "Max iterations reached")
        return self._result(False, "Max iterations reached", task_id, config.MAX_ITERATIONS, total_tokens_used)

    def _build_system_prompt(self, skill_context: str = "") -> str:
        """시스템 프롬프트 조립."""
        available_skills = self.skills_manager.get_catalog_summary()

        return f"""너는 REZE — 리눅스 서버의 범용 AI 에이전트다.

## 도구
반드시 아래 6개 중 하나를 사용해라:
- shell: bash 명령 실행 (체이닝 금지 — 한 번에 하나의 명령만)
- python: Python 코드 실행 (import 불가, math만 가능)
- http: HTTP 요청 ({{"url":"...","method":"GET","headers":{{}},"body":{{}}}})
- filesystem: 파일 읽기/쓰기 ({{"operation":"read|write|list","path":"...","content":"..."}})
- web_search: 웹 검색 (검색어 문자열)
- final_answer: 최종 답변 (완료 시 반드시 사용)

## 응답 형식
반드시 JSON으로 응답해라. 다른 형식 절대 금지:
{{"thought": "현재 상태 분석 + 다음 행동 이유", "tool": "도구명", "input": "도구 입력"}}

완료 시:
{{"thought": "결과 요약", "tool": "final_answer", "input": "최종 답변"}}

## 규칙
1. 한 번에 하나의 도구만 사용
2. shell에서 ; | && || ` $() 사용 금지 — 명령을 나눠서 실행
3. Observation을 확인한 후 다음 행동 결정
4. 같은 행동을 반복하지 마라 — 안 되면 다른 방법
5. 에러가 나면 에러 메시지를 읽고 대응
6. 작업이 끝나면 반드시 final_answer로 결과 보고

## 사용 가능한 스킬
{available_skills}
{skill_context}"""

    def _result(self, success: bool, answer: str, task_id: str,
                steps: int, tokens: int, skills_used: list = None,
                quality_score: float = 0.0) -> dict:
        """결과 딕셔너리."""
        return {
            "success": success,
            "answer": answer,
            "task_id": task_id,
            "steps": steps,
            "total_tokens": tokens,
            "skills_used": skills_used or [],
            "quality_score": quality_score,
        }

    # ============================================================
    # v4.0 Learning Loop + Quality Gate
    # ============================================================

    async def _classify_output(self, task: str, output: str) -> str:
        """산출물 유형 분류 (Cerebras — 빠른 분류)"""
        prompt = f"""태스크: {task}
산출물 첫 200자: {output[:200]}

이 산출물의 유형을 다음 중 하나로 분류:
blog_article, saas_report, email_outreach, code_change, strategy_document, discord_report, unknown

유형만 영문으로 답하시오."""

        try:
            result = await self.router.call("classification", [{"role": "user", "content": prompt}])
            type_str = result.text.strip().lower()
            from reze_permissions import QUALITY_GATES
            if type_str in QUALITY_GATES:
                return type_str
        except Exception as e:
            logger.warning(f"Output classification failed: {e}")
        return "unknown"

    def _run_hard_checks(self, output: str, checks: dict) -> dict:
        """규칙 기반 검증 (LLM 불필요)"""
        failures = []
        word_count = len(output.split())

        if checks.get("min_words") and word_count < checks["min_words"]:
            failures.append(f"단어 수 부족: {word_count} < {checks['min_words']}")
        if checks.get("max_words") and word_count > checks["max_words"]:
            failures.append(f"단어 수 초과: {word_count} > {checks['max_words']}")
        if checks.get("has_h2") and output.count("## ") < 3 and output.count("<h2") < 3:
            failures.append("H2 소제목 3개 미만")
        if checks.get("has_cta") and not any(kw in output.lower() for kw in ["try", "get started", "sign up", "check out", "learn more"]):
            failures.append("CTA(Call to Action) 없음")
        if checks.get("has_summary") and "요약" not in output and "summary" not in output.lower():
            failures.append("요약 섹션 없음")
        if checks.get("has_numbers") and not re.search(r'\d+', output):
            failures.append("수치 데이터 없음")

        return {'passed': len(failures) == 0, 'failures': failures}

    async def _cross_review(self, output: str, config: dict) -> dict:
        """크로스 리뷰: 다른 LLM이 채점"""
        prompt = f"""다음 콘텐츠를 100점 만점으로 채점하시오.

채점 기준:
1. 정보의 정확성과 깊이 (25점)
2. 구조와 가독성 (25점)
3. 실용성과 행동 가능성 (25점)
4. 전문성과 신뢰도 (25점)

콘텐츠:
{output[:3000]}

JSON 응답: {{"score": 숫자, "feedback": "구체적 개선 방향"}}"""

        try:
            result = await self.router.call("evaluation", [{"role": "user", "content": prompt}])
            parsed = json.loads(result.text)
            return {'score': parsed.get('score', 0), 'feedback': parsed.get('feedback', '')}
        except Exception as e:
            logger.warning(f"Cross review failed: {e}")
            return {'score': 70, 'feedback': 'Review parsing failed'}

    async def _reflect_and_learn(self, task: str, result: dict):
        """모든 태스크 완료 후 반성 + 교훈 추출"""
        try:
            reflection_prompt = f"""태스크: {task}
결과: {"성공" if result.get('success') else "실패"}
소요 스텝: {result.get('steps', 0)}
소요 토큰: {result.get('total_tokens', 0)}
품질 점수: {result.get('quality_score', 'N/A')}
사용 스킬: {result.get('skills_used', [])}

다음을 추출하시오:
1. 핵심 교훈 (1문장): 이 경험에서 배운 가장 중요한 것
2. 개선점: 다음에 같은 종류의 태스크를 할 때 뭘 바꿔야 하는가
3. 패턴: 비슷한 다른 태스크에도 적용할 수 있는 일반 원칙

JSON: {{"lesson": "...", "improvement": "...", "pattern": "..."}}"""

            reflection = await self.router.call("reflection", [{"role": "user", "content": reflection_prompt}])
            parsed = json.loads(reflection.text)

            # signals 테이블에 교훈 저장
            self.ssot.add_signal(
                type_="task_lesson",
                data={
                    "task": task[:200],
                    "success": result.get('success', False),
                    "lesson": parsed.get('lesson', ''),
                    "improvement": parsed.get('improvement', ''),
                    "pattern": parsed.get('pattern', ''),
                    "steps": result.get('steps', 0),
                    "tokens": result.get('total_tokens', 0),
                    "score": result.get('quality_score', 0)
                }
            )

            # 실패인 경우 reflections_v4 테이블에도 저장
            if not result.get('success'):
                self.ssot.save_reflection_v4(
                    task_pattern=self._abstract_task(task),
                    failure_reason=str(result.get('errors', 'unknown')),
                    lesson=parsed.get('lesson', ''),
                    suggested_approach=parsed.get('improvement', '')
                )

            logger.info(f"Reflection saved: {parsed.get('lesson', '')[:50]}")

        except Exception as e:
            logger.warning(f"Reflection failed: {e}")

    def _abstract_task(self, task: str) -> str:
        """태스크를 패턴으로 추상화"""
        abstractions = {
            'aitoolslab': '[blog]', 'nocodetoolslab': '[blog]',
            'postpilot': '[saas]', 'quotepilot': '[saas]',
            'browserpilot': '[saas]', 'agenthub': '[saas]',
        }
        result = task.lower()
        for specific, abstract in abstractions.items():
            result = result.replace(specific, abstract)
        return result[:200]

    def _extract_procedure(self, messages: list) -> str:
        """성공한 태스크의 실행 절차를 텍스트로 추출"""
        steps = []
        step_num = 1
        for msg in messages:
            if isinstance(msg, dict) and msg.get('role') == 'assistant':
                content = msg.get('content', '')
                try:
                    parsed = json.loads(content) if content.startswith('{') else {}
                    action = parsed.get('tool')
                    if action and action != 'final_answer':
                        steps.append(f"{step_num}. {action}: {str(parsed.get('input', ''))[:100]}")
                        step_num += 1
                except:
                    pass
        return "\n".join(steps) if steps else "절차 추출 실패"
