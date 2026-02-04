"""Manus Context Manager - 도구/권한 동적 관리."""
import json
from datetime import datetime
from dataclasses import dataclass, field
from typing import Set, Dict, Optional, Any

import logging
logger = logging.getLogger("REZE.manus")


@dataclass
class ExecutionContext:
    """태스크 실행 컨텍스트."""
    task_id: str
    allowed_tools: Set[str]
    permission_level: str
    max_iterations: int
    timeout_seconds: int
    sandbox_mode: bool
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)


class ContextManager:
    """실행 컨텍스트 동적 관리."""

    # 기본 설정
    DEFAULT_TOOLS = {"web_search", "web_fetch", "file_read", "python_exec"}
    DEFAULT_MAX_ITERATIONS = 20
    DEFAULT_TIMEOUT = 300  # 5분

    # 권한 레벨별 도구
    PERMISSION_TOOLS = {
        "AUTO_APPROVE": {"web_search", "web_fetch", "file_read", "python_exec", "code_edit"},
        "STANDARD": {"web_search", "web_fetch", "file_read", "python_exec", "code_edit",
                    "shell", "calendar"},
        "DANGEROUS": {"web_search", "web_fetch", "file_read", "python_exec", "code_edit",
                     "shell", "calendar", "discord_send", "webhook_call"},
        "CRITICAL": set()  # 모든 도구 허용 (검증은 별도)
    }

    def __init__(self, permissions=None, tools=None, ssot=None):
        """
        Args:
            permissions: RezPermissions 인스턴스 (선택)
            tools: ToolExecutor 인스턴스 (선택)
            ssot: SSOT 인스턴스 (선택)
        """
        self.permissions = permissions
        self.tools = tools
        self.ssot = ssot
        self._contexts: Dict[str, ExecutionContext] = {}

    def create_context(
        self,
        task_id: str,
        skill_name: str = None,
        source: str = "api",
        allowed_tools: Set[str] = None,
        permission_level: str = "STANDARD",
        max_iterations: int = None,
        timeout_seconds: int = None,
        sandbox_mode: bool = False
    ) -> ExecutionContext:
        """
        태스크별 실행 컨텍스트 생성.

        Args:
            task_id: 태스크 ID
            skill_name: 스킬 이름 (스킬에서 도구 제한 가져옴)
            source: 태스크 소스 (api, discord, scheduler 등)
            allowed_tools: 허용 도구 (직접 지정)
            permission_level: 권한 레벨
            max_iterations: 최대 반복 횟수
            timeout_seconds: 타임아웃 (초)
            sandbox_mode: 샌드박스 모드

        Returns:
            ExecutionContext
        """
        # 도구 결정 우선순위: 직접 지정 > 스킬 > 권한레벨 > 기본값
        if allowed_tools:
            tools = allowed_tools
        elif skill_name:
            tools = self._get_skill_tools(skill_name)
        elif permission_level in self.PERMISSION_TOOLS:
            tools = self.PERMISSION_TOOLS[permission_level]
        else:
            tools = self.DEFAULT_TOOLS

        context = ExecutionContext(
            task_id=task_id,
            allowed_tools=tools,
            permission_level=permission_level,
            max_iterations=max_iterations or self.DEFAULT_MAX_ITERATIONS,
            timeout_seconds=timeout_seconds or self.DEFAULT_TIMEOUT,
            sandbox_mode=sandbox_mode,
            metadata={"skill": skill_name, "source": source}
        )

        self._contexts[task_id] = context
        logger.info(f"[CONTEXT] Created context for {task_id}: "
                   f"tools={len(tools)}, level={permission_level}")

        return context

    def get_context(self, task_id: str) -> Optional[ExecutionContext]:
        """
        현재 컨텍스트 조회.

        Args:
            task_id: 태스크 ID

        Returns:
            ExecutionContext (없으면 None)
        """
        return self._contexts.get(task_id)

    def restrict_tools(self, task_id: str, tools: Set[str]) -> bool:
        """
        도구 제한 동적 적용.

        Args:
            task_id: 태스크 ID
            tools: 허용할 도구 집합

        Returns:
            성공 여부
        """
        ctx = self._contexts.get(task_id)
        if not ctx:
            return False

        old_tools = ctx.allowed_tools
        ctx.allowed_tools = tools
        logger.info(f"[CONTEXT] Restricted tools for {task_id}: "
                   f"{len(old_tools)} -> {len(tools)}")
        return True

    def add_tools(self, task_id: str, tools: Set[str]) -> bool:
        """
        도구 추가.

        Args:
            task_id: 태스크 ID
            tools: 추가할 도구 집합

        Returns:
            성공 여부
        """
        ctx = self._contexts.get(task_id)
        if not ctx:
            return False

        ctx.allowed_tools = ctx.allowed_tools | tools
        logger.info(f"[CONTEXT] Added tools for {task_id}: {tools}")
        return True

    def elevate_permission(self, task_id: str, level: str, reason: str) -> bool:
        """
        권한 승격 (로그 필수).

        Args:
            task_id: 태스크 ID
            level: 새 권한 레벨
            reason: 승격 사유

        Returns:
            성공 여부
        """
        ctx = self._contexts.get(task_id)
        if not ctx:
            return False

        old_level = ctx.permission_level
        ctx.permission_level = level

        # 권한 레벨에 따른 도구 확장
        if level in self.PERMISSION_TOOLS:
            ctx.allowed_tools = ctx.allowed_tools | self.PERMISSION_TOOLS[level]

        logger.warning(f"[CONTEXT] Permission elevated for {task_id}: "
                      f"{old_level} -> {level}, reason: {reason}")

        # SSOT에 기록
        if self.ssot:
            self.ssot.log_event(
                kind="permission_elevation",
                raw_input=f"task={task_id}, {old_level}->{level}",
                output_preview=reason
            )

        return True

    def validate_tool_call(self, task_id: str, tool: str) -> bool:
        """
        도구 호출 허용 여부 검증.

        Args:
            task_id: 태스크 ID
            tool: 도구 이름

        Returns:
            허용 여부
        """
        ctx = self._contexts.get(task_id)
        if not ctx:
            # 컨텍스트 없으면 기본 허용 (backward compatibility)
            return True

        allowed = tool in ctx.allowed_tools
        if not allowed:
            logger.warning(f"[CONTEXT] Tool {tool} blocked for task {task_id} "
                          f"(allowed: {ctx.allowed_tools})")
        return allowed

    def cleanup_context(self, task_id: str):
        """
        컨텍스트 정리.

        Args:
            task_id: 태스크 ID
        """
        if task_id in self._contexts:
            del self._contexts[task_id]
            logger.debug(f"[CONTEXT] Cleaned up context for {task_id}")

    def get_active_contexts(self) -> Dict[str, Dict[str, Any]]:
        """
        활성 컨텍스트 목록.

        Returns:
            {task_id: context_info}
        """
        return {
            tid: {
                "allowed_tools": list(ctx.allowed_tools),
                "permission_level": ctx.permission_level,
                "max_iterations": ctx.max_iterations,
                "sandbox_mode": ctx.sandbox_mode,
                "created_at": ctx.created_at
            }
            for tid, ctx in self._contexts.items()
        }

    def _get_skill_tools(self, skill_name: str) -> Set[str]:
        """스킬에서 허용 도구 가져오기."""
        # skills_manager가 있으면 거기서 가져옴
        try:
            from skills_manager import SkillsManager
            # 싱글톤이 아니므로 기본 도구 반환
        except ImportError:
            pass

        # 기본 도구
        return self.DEFAULT_TOOLS
