"""REZE Daemon State - 공유 상태 및 헬퍼 함수들."""
import asyncio
import logging
from typing import TYPE_CHECKING

# Type hints only (실제 import는 orchestrator에서)
if TYPE_CHECKING:
    from ssot import SSOT
    from reze_permissions import PermissionSystem
    from reze_tools import ToolExecutor
    from reze_core import REZECore, ModelRouter, CircuitBreaker
    from skills_manager import SkillsManager
    from reze_self_healing import SelfHealing
    from reze_alert import AlertManager
    from reze_biz import BizTracker
    from saas_monitor import SaaSMonitor
    from landing_optimizer import LandingOptimizer
    from launch_sequence import LaunchSequence
    from capability_engine import CapabilityEngine
    from autonomous_ops import AutonomousLoop
    from goal_execution_bridge import GoalExecutionBridge
    from agent_supervisor import AgentSupervisor
    from saas_operations import SaaSOperations
    from gumroad_operations import GumroadOperations
    from growth_engine import CrossPortfolioGrowth
    from meta_cognition import MetaCognitionReview
    from prompt_evolver import PromptEvolver
    from discovery_engine import DiscoveryEngine
    from universal_planner import UniversalPlanner, TaskExecutor as PlanExecutor
    from feedback_engine import FeedbackEngine
    from worker_pool import WorkerPool
    from config_tuner import ConfigTuner
    from plan_memory import PlanMemory
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = logging.getLogger("REZE.daemon")


# ============================================================
# 글로벌 상태 (lifespan에서 초기화)
# ============================================================
class AppState:
    ssot: "SSOT" = None
    permissions: "PermissionSystem" = None
    tools: "ToolExecutor" = None
    router: "ModelRouter" = None
    skills: "SkillsManager" = None
    circuit_breaker: "CircuitBreaker" = None
    core: "REZECore" = None
    scheduler: "AsyncIOScheduler" = None
    notifier: "WebhookNotifier" = None
    queue_worker_task: asyncio.Task = None
    # v3.3 신규
    self_healing: "SelfHealing" = None
    alert_manager: "AlertManager" = None
    biz_tracker: "BizTracker" = None
    # Phase 4 Part D+E
    saas_monitor: "SaaSMonitor" = None
    landing_optimizer: "LandingOptimizer" = None
    launch_sequence: "LaunchSequence" = None
    # v4.0 ULTIMATE
    capability_engine: "CapabilityEngine" = None
    autonomous_loop: "AutonomousLoop" = None
    goal_bridge: "GoalExecutionBridge" = None
    agent_supervisor: "AgentSupervisor" = None
    saas_ops: "SaaSOperations" = None
    gumroad_ops: "GumroadOperations" = None
    growth_engine: "CrossPortfolioGrowth" = None
    meta_cognition: "MetaCognitionReview" = None
    prompt_evolver: "PromptEvolver" = None
    # v5.0 SOVEREIGN
    discovery: "DiscoveryEngine" = None
    planner: "UniversalPlanner" = None
    plan_executor: "PlanExecutor" = None
    # v5.0 Phase 3
    feedback: "FeedbackEngine" = None
    worker_pool: "WorkerPool" = None
    # v5.0 Phase 4
    config_tuner: "ConfigTuner" = None
    plan_memory: "PlanMemory" = None


# Forward declaration for WebhookNotifier
class WebhookNotifier:
    """Placeholder - 실제 구현은 orchestrator.py에서."""
    pass


state = AppState()


# ============================================================
# SaaS 헬스체크 대상
# ============================================================
SAAS_HEALTH_ENDPOINTS = {
    "postpilot-backend": "http://localhost:8000/health",
    "postpilot-frontend": "http://localhost:3000",
    # "ai-tools-lab": "http://localhost:3005",  # migrating to nocodetoolslab
    "browserpilot-api": "http://localhost:8100/health",
    "agenthub-api": "http://localhost:8101/health",
    "rag-service": "http://localhost:8020/health",
    "quotepilot-api": "http://localhost:8030/health",
    "rapidapi-server": "http://localhost:8001/health",
    "rapidapi-nocode": "http://localhost:8002/health",
}


# ============================================================
# 헬퍼 함수들
# ============================================================
async def _call_llm_for_learning(prompt: str, role: str = "reasoning") -> str:
    """학습/진화 모듈용 LLM 호출 헬퍼."""
    if not state.router:
        logger.warning("Router not initialized, cannot call LLM")
        return ""
    response = await state.router.call(
        role,
        [{"role": "user", "content": prompt}],
        system="REZE 자기 진화 및 학습 시스템."
    )
    return response.text


async def _discord_notify_fn(message: str):
    """Discord 알림 헬퍼."""
    if state.alert_manager:
        await state.alert_manager.send("info", "reze_ultimate", message)


async def _tavily_search_fn(query: str) -> list:
    """Tavily 검색 헬퍼 - tools._exec_web_search() 재사용."""
    try:
        if state.tools:
            result = await state.tools._exec_web_search(query)
            if result.startswith("ERROR"):
                logger.warning(f"Tavily search error: {result}")
                return []
            # 결과를 리스트 형태로 변환
            return [{"content": result}]
        return []
    except Exception as e:
        logger.warning(f"Tavily search failed: {e}")
        return []
