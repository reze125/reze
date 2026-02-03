"""
REZE v4.0 ULTIMATE Capability Engine
- 역량 기반 메타스킬 (도메인 무관)
- 8개 역량: collect, analyze, create, execute, verify, communicate, optimize, learn
"""

import json
import asyncio
from typing import Optional, Any, Callable
from datetime import datetime

import logging
logger = logging.getLogger("REZE.capability")


# 역량별 메타스킬 정의
CAPABILITY_METASKILLS = {
    "collect": {
        "description": "데이터 수집 — API, 크롤링, DB 쿼리, 파일 읽기, 센서 데이터",
        "tools": ["tavily_search", "shell_exec", "api_call", "db_query", "file_read"],
        "examples": [
            "블로그 키워드 수집", "Stripe 결제 데이터", "Docker 상태",
            "경쟁사 가격", "Gumroad 판매 통계", "n8n 워크플로우 상태"
        ]
    },
    "analyze": {
        "description": "분석 — 숫자, 텍스트, 비교, 트렌드, 패턴 인식",
        "tools": ["llm_reasoning", "python_calc", "statistical_analysis"],
        "examples": [
            "트래픽 트렌드", "전환율 분석", "경쟁사 비교",
            "비용 대비 ROI", "에러 로그 패턴", "시장 규모 추정"
        ]
    },
    "create": {
        "description": "생성 — 글, 코드, 설정, 이미지, 제품, 문서",
        "tools": ["llm_generate", "code_write", "file_create", "config_generate"],
        "examples": [
            "블로그 글", "Python 스크립트", "YAML 설정", "Gumroad 제품 페이지",
            "SaaS 랜딩페이지", "Docker Compose", "SKILL.md"
        ]
    },
    "execute": {
        "description": "실행 — 셸 명령, API 호출, 배포, 스케줄링, 결제 처리",
        "tools": ["shell_exec", "api_call", "deploy", "cron_schedule"],
        "examples": [
            "git push", "WordPress 발행", "Docker restart",
            "n8n 워크플로우 트리거", "Stripe 환불 처리", "PM2 restart"
        ]
    },
    "verify": {
        "description": "검증 — 품질 체크, 테스트, 모니터링, 헬스체크, 수치 확인",
        "tools": ["quality_gate", "http_check", "test_runner", "metric_compare"],
        "examples": [
            "글 품질 검증", "사이트 200 OK", "Docker 컨테이너 healthy",
            "결제 성공 확인", "배포 후 smoke test", "스킬 3회 성공 검증"
        ]
    },
    "communicate": {
        "description": "소통 — Discord, 이메일, 알림, 리포트, 보스에게 질문",
        "tools": ["discord_send", "email_send", "alert", "report_generate"],
        "examples": [
            "일일 리포트", "장애 알림", "보스에게 승인 요청",
            "주간 매출 리포트", "에러 에스컬레이션", "작업 완료 보고"
        ]
    },
    "optimize": {
        "description": "최적화 — 성능, 비용, 전환율, SEO, 가격, 리소스",
        "tools": ["ab_test", "perf_tune", "cost_analyze", "seo_audit"],
        "examples": [
            "LLM 비용 절감", "페이지 속도 최적화", "전환율 개선",
            "SEO 메타태그", "가격 조정 제안", "디스크 정리"
        ]
    },
    "learn": {
        "description": "학습 — 반성, 리서치, 패턴 인식, 스킬 축적, 메타인지",
        "tools": ["tavily_search", "reflection_write", "plan_cache_save", "skill_create"],
        "examples": [
            "실패 원인 분석", "새 도메인 학습", "경험 패턴화",
            "프롬프트 자기 최적화", "주간 메타 리뷰", "스킬 검증→승격"
        ]
    }
}


class CapabilityEngine:
    """
    역량 기반 실행 엔진.
    도메인 구분 없이 역량 조합으로 모든 태스크 처리.
    """

    def __init__(self, call_llm_fn: Callable, ssot, tools: dict = None,
                 discord_notify: Callable = None, tavily_search: Callable = None):
        """
        Args:
            call_llm_fn: LLM 호출 함수 (async, prompt + role 인자)
            ssot: SSOT 인스턴스
            tools: 사용 가능한 도구들 딕셔너리
            discord_notify: Discord 알림 함수
            tavily_search: Tavily 검색 함수
        """
        self.call_llm = call_llm_fn
        self.ssot = ssot
        self.tools = tools or {}
        self.discord_notify = discord_notify
        self.tavily_search = tavily_search
        self.capabilities = CAPABILITY_METASKILLS

    def get_capability(self, name: str) -> "Capability":
        """특정 역량 인스턴스 반환."""
        if name not in self.capabilities:
            raise ValueError(f"Unknown capability: {name}")
        return Capability(name, self.capabilities[name], self)

    async def plan_capabilities(self, task: str, context: dict = None) -> list:
        """
        태스크에 필요한 역량 시퀀스 계획.
        LLM이 도메인 무관하게 역량 조합을 결정.
        """
        prompt = f"""너는 만능 자율 에이전트의 역량 계획기다.

## 사용 가능한 역량
{json.dumps(self.capabilities, indent=2, ensure_ascii=False)}

## 태스크
{task}

## 컨텍스트
{json.dumps(context or {}, indent=2, ensure_ascii=False)}

## 지시
이 태스크를 완료하기 위해 필요한 역량의 순서를 계획하라.
각 역량에 대해 구체적으로 무엇을 해야 하는지 명시하라.

JSON 형식:
{{
    "plan": [
        {{"capability": "collect", "action": "구체적 행동", "expected_output": "기대 결과"}},
        {{"capability": "analyze", "action": "구체적 행동", "expected_output": "기대 결과"}},
        ...
    ],
    "estimated_steps": 5,
    "domain_detected": "blog|saas|gumroad|infra|unknown",
    "confidence": 0.85
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
            logger.error(f"Capability planning failed: {e}")
            # 기본 계획: collect → analyze → create/execute → verify
            return {
                "plan": [
                    {"capability": "collect", "action": "관련 데이터 수집", "expected_output": "데이터"},
                    {"capability": "analyze", "action": "데이터 분석", "expected_output": "인사이트"},
                    {"capability": "execute", "action": "필요한 조치 실행", "expected_output": "결과"},
                    {"capability": "verify", "action": "결과 검증", "expected_output": "검증 완료"}
                ],
                "estimated_steps": 4,
                "domain_detected": "unknown",
                "confidence": 0.5
            }

    async def execute_plan(self, plan: list, context: dict = None) -> dict:
        """
        역량 계획을 순차적으로 실행.
        """
        results = []
        accumulated_context = context or {}

        for step in plan.get("plan", []):
            cap_name = step.get("capability")
            action = step.get("action")

            logger.info(f"Executing capability: {cap_name} - {action}")

            try:
                cap = self.get_capability(cap_name)
                result = await cap.execute(action, accumulated_context)
                results.append({
                    "capability": cap_name,
                    "action": action,
                    "status": "success",
                    "result": result
                })
                # 다음 단계를 위해 컨텍스트 누적
                accumulated_context[f"{cap_name}_result"] = result
            except Exception as e:
                logger.error(f"Capability execution failed: {cap_name} - {e}")
                results.append({
                    "capability": cap_name,
                    "action": action,
                    "status": "failed",
                    "error": str(e)
                })

        return {
            "results": results,
            "success": all(r["status"] == "success" for r in results),
            "context": accumulated_context
        }


class Capability:
    """개별 역량 인스턴스."""

    def __init__(self, name: str, spec: dict, engine: CapabilityEngine):
        self.name = name
        self.spec = spec
        self.engine = engine

    async def execute(self, action: str, context: dict = None) -> Any:
        """역량별 액션 실행."""
        method_name = f"_execute_{self.name}"
        if hasattr(self, method_name):
            return await getattr(self, method_name)(action, context)
        else:
            # 기본: LLM 기반 실행
            return await self._default_execute(action, context)

    async def _default_execute(self, action: str, context: dict) -> str:
        """기본 LLM 기반 실행."""
        prompt = f"""역량: {self.name}
설명: {self.spec['description']}
액션: {action}
컨텍스트: {json.dumps(context or {}, indent=2, ensure_ascii=False)}

이 액션을 수행하고 결과를 반환하라."""

        return await self.engine.call_llm(prompt, role="execution")

    async def _run_tool(self, tool: str, input_data: Any) -> str:
        """v5.0: ToolExecutor를 통한 도구 실행."""
        if hasattr(self.engine.tools, 'execute'):
            return await self.engine.tools.execute(tool, input_data, source="capability")
        return f"ERROR: ToolExecutor not available"

    # === COLLECT 역량 구현 ===
    async def _execute_collect(self, action: str, context: dict) -> Any:
        """데이터 수집 역량."""
        # v5.0: ToolExecutor.execute() 사용

        # 웹 검색
        if "search" in action.lower() or "조사" in action or "검색" in action:
            return await self._run_tool("web_search", action)

        # Shell 실행 (docker, pm2 등)
        if any(cmd in action.lower() for cmd in ["docker", "pm2", "df", "free", "ls", "curl"]):
            return await self._run_tool("shell", action)

        # 웹 페이지 가져오기
        if "fetch" in action.lower() or "페이지" in action or "url" in action.lower():
            url = context.get("url") if context else None
            return await self._run_tool("web_fetch", url or action)

        # HTTP API 호출
        if "api" in action.lower() or "http" in action.lower():
            return await self._run_tool("http", context or action)

        # 기본: LLM에게 수집 방법 요청
        return await self._default_execute(action, context)

    # === ANALYZE 역량 구현 ===
    async def _execute_analyze(self, action: str, context: dict) -> Any:
        """분석 역량."""
        prompt = f"""[분석 역량]
태스크: {action}

입력 데이터:
{json.dumps(context, indent=2, ensure_ascii=False)}

분석 요청:
1. 데이터에서 핵심 패턴/인사이트 추출
2. 이상치나 문제점 식별
3. 액션 가능한 결론 도출

JSON 형식으로 응답:
{{
    "insights": ["인사이트1", "인사이트2"],
    "anomalies": ["이상치1"],
    "recommendations": ["권장사항1"],
    "summary": "한 줄 요약"
}}"""

        return await self.engine.call_llm(prompt, role="analysis")

    # === CREATE 역량 구현 ===
    async def _execute_create(self, action: str, context: dict) -> Any:
        """생성 역량."""
        # v5.0: code_edit 도구 사용

        # 코드/파일 생성
        if "코드" in action or "code" in action.lower() or "파일" in action or "file" in action.lower():
            path = context.get("path") if context else None
            content = context.get("content") if context else None
            if path and content:
                return await self._run_tool("code_edit", {
                    "action": "create",
                    "path": path,
                    "content": content
                })

        # 기본: LLM 생성
        prompt = f"""[생성 역량]
태스크: {action}
컨텍스트: {json.dumps(context, indent=2, ensure_ascii=False)}

고품질 결과물을 생성하라. 완벽을 추구하라."""

        return await self.engine.call_llm(prompt, role="writing")

    # === EXECUTE 역량 구현 ===
    async def _execute_execute(self, action: str, context: dict) -> Any:
        """실행 역량."""
        # v5.0: ToolExecutor 사용

        # Shell 명령
        if any(cmd in action.lower() for cmd in
               ["git", "docker", "pm2", "curl", "npm", "pip", "restart", "deploy", "systemctl"]):
            return await self._run_tool("shell", action)

        # HTTP API 호출
        if "api" in action.lower() or "http" in action.lower():
            return await self._run_tool("http", context or action)

        # Python 코드 실행
        if "python" in action.lower() or "계산" in action:
            code = context.get("code") if context else None
            if code:
                return await self._run_tool("python", code)

        # 기본: LLM에게 실행 계획 요청
        return await self._default_execute(action, context)

    # === VERIFY 역량 구현 ===
    async def _execute_verify(self, action: str, context: dict) -> Any:
        """검증 역량."""
        # v5.0: ToolExecutor 사용

        # HTTP 헬스체크
        if "health" in action.lower() or "200" in action or "status" in action.lower():
            url = context.get("url") if context else None
            if url:
                return await self._run_tool("http", url)
            # shell로 헬스체크
            return await self._run_tool("shell", action)

        # 파일 검증
        if "file" in action.lower() or "파일" in action:
            path = context.get("path") if context else None
            if path:
                return await self._run_tool("code_edit", {"action": "read", "path": path})

        # LLM 기반 검증
        prompt = f"""[검증 역량]
검증 대상: {action}

입력 데이터:
{json.dumps(context, indent=2, ensure_ascii=False)}

검증 기준:
1. 객관적 체크 (데이터 존재, 형식 정확성, 에러 없음)
2. 품질 체크 (완성도, 정확성, 일관성)
3. 비즈니스 체크 (목적 달성, 가치 제공)

JSON 형식:
{{
    "passed": true/false,
    "objective_checks": [{{"check": "항목", "passed": true/false}}],
    "quality_score": 8.5,
    "issues": ["문제1"],
    "suggestions": ["개선사항1"]
}}"""

        return await self.engine.call_llm(prompt, role="evaluation")

    # === COMMUNICATE 역량 구현 ===
    async def _execute_communicate(self, action: str, context: dict) -> Any:
        """소통 역량."""
        # v5.0: ToolExecutor 사용

        # Discord 전송 (webhook HTTP 호출)
        if "discord" in action.lower() or "알림" in action:
            # Discord는 engine의 discord_notify 함수 또는 http 도구 사용
            if self.engine.discord_notify:
                message = context.get("message", action) if context else action
                try:
                    await self.engine.discord_notify(message)
                    return "Discord 알림 전송 완료"
                except Exception as e:
                    return f"Discord 전송 실패: {e}"

        # HTTP API 알림 (슬랙, 웹훅 등)
        if "webhook" in action.lower() or "http" in action.lower():
            return await self._run_tool("http", context or action)

        # 리포트 생성
        prompt = f"""[소통 역량]
태스크: {action}
컨텍스트: {json.dumps(context, indent=2, ensure_ascii=False)}

명확하고 간결한 메시지를 작성하라.
- 핵심만 전달
- 액션 아이템 명시
- 긴급도 표시"""

        return await self.engine.call_llm(prompt, role="writing")

    # === OPTIMIZE 역량 구현 ===
    async def _execute_optimize(self, action: str, context: dict) -> Any:
        """최적화 역량."""
        prompt = f"""[최적화 역량]
태스크: {action}

현재 상태:
{json.dumps(context, indent=2, ensure_ascii=False)}

최적화 분석:
1. 현재 성능/효율 측정
2. 병목/비효율 식별
3. 구체적 개선 방안 제시
4. 예상 개선 효과 추정

JSON 형식:
{{
    "current_state": {{}},
    "bottlenecks": ["병목1"],
    "optimizations": [
        {{"action": "개선1", "expected_impact": "10% 향상", "effort": "low"}}
    ],
    "priority_order": ["개선1", "개선2"]
}}"""

        return await self.engine.call_llm(prompt, role="analysis")

    # === LEARN 역량 구현 ===
    async def _execute_learn(self, action: str, context: dict) -> Any:
        """학습 역량."""
        # v5.0: ToolExecutor 사용

        # 반성 저장
        if "반성" in action or "reflection" in action.lower():
            return await self._reflect(context)

        # 리서치 (웹 검색)
        if "조사" in action or "research" in action.lower() or "검색" in action:
            return await self._run_tool("web_search", action)

        # 경험 패턴화
        prompt = f"""[학습 역량]
태스크: {action}

경험 데이터:
{json.dumps(context, indent=2, ensure_ascii=False)}

학습 분석:
1. 이 경험에서 배운 점
2. 다음에 적용할 패턴
3. 스킬로 승격할 만한 반복 패턴
4. 개선이 필요한 영역

JSON 형식:
{{
    "lessons": ["교훈1"],
    "patterns": ["패턴1"],
    "skill_candidates": ["스킬 후보"],
    "improvement_areas": ["개선 영역"]
}}"""

        return await self.engine.call_llm(prompt, role="reflection")

    async def _reflect(self, context: dict) -> dict:
        """반성 수행 및 저장."""
        prompt = f"""[반성]
경험:
{json.dumps(context, indent=2, ensure_ascii=False)}

반성:
1. 무엇이 잘못되었나? (또는 잘 되었나?)
2. 왜 그랬나?
3. 다음에는 어떻게 할 것인가?

JSON 형식:
{{
    "what_happened": "...",
    "why": "...",
    "lesson": "...",
    "next_time": "..."
}}"""

        response = await self.engine.call_llm(prompt, role="reflection")

        try:
            text = response
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            reflection = json.loads(text.strip())

            # SSOT에 저장
            self.engine.ssot.save_reflection_v4(
                task_pattern=context.get("task_pattern", "unknown"),
                failure_reason=reflection.get("why", ""),
                lesson=reflection.get("lesson", ""),
                suggested_approach=reflection.get("next_time", "")
            )

            return reflection
        except Exception as e:
            logger.error(f"Reflection parsing failed: {e}")
            return {"error": str(e)}


# === 역량 조합 템플릿 ===

CAPABILITY_TEMPLATES = {
    "blog_publish": ["collect", "analyze", "create", "verify", "execute", "communicate"],
    "saas_monitor": ["collect", "analyze", "verify", "communicate"],
    "gumroad_optimize": ["collect", "analyze", "optimize", "verify", "communicate"],
    "infra_fix": ["collect", "analyze", "execute", "verify", "communicate", "learn"],
    "new_domain_learn": ["collect", "analyze", "learn", "create", "verify"],
    "goal_execute": ["analyze", "create", "execute", "verify", "learn"],
}


def get_template(task_type: str) -> list:
    """태스크 타입에 맞는 역량 템플릿 반환."""
    return CAPABILITY_TEMPLATES.get(task_type, ["collect", "analyze", "execute", "verify"])
