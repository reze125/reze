"""REZE Daemon API Routes - 21개 FastAPI 엔드포인트."""
import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel

import config
from daemon.state import state
from daemon.scheduler_jobs import judgment_job

logger = logging.getLogger("REZE.daemon")


# ============================================================
# Request/Response 모델
# ============================================================

class RunRequest(BaseModel):
    task: str
    priority: int = 1
    source: str = "api"
    sync: bool = False  # True면 즉시 실행, False면 큐에 추가


class RunResponse(BaseModel):
    task_id: str
    status: str
    message: str


class TaskResult(BaseModel):
    success: Optional[bool] = None
    answer: Optional[str] = None
    steps: Optional[int] = None
    total_tokens: Optional[int] = None


# ============================================================
# 인증
# ============================================================

async def verify_token(authorization: Optional[str] = Header(None)):
    """Bearer token 검증."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")
    parts = authorization.split(" ")
    if len(parts) != 2 or parts[0] != "Bearer":
        raise HTTPException(status_code=401, detail="Invalid authorization format")
    if parts[1] != config.REZE_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")
    return parts[1]


# ============================================================
# Router 정의
# ============================================================

router = APIRouter()


# ============================================================
# 엔드포인트
# ============================================================

@router.get("/health")
async def health():
    """헬스체크 (인증 없음)."""
    return {"status": "ok", "version": "4.0-ultimate", "agent": "REZE"}


@router.get("/health/detail")
async def health_detail(_=Depends(verify_token)):
    """상세 헬스체크."""
    return {
        "status": "ok",
        "version": "4.0-ultimate",
        "providers": list(state.router.providers.keys()) if state.router else [],
        "skills": list(state.skills.catalog.keys()) if state.skills else [],
        "pending_tasks": state.ssot.count_pending() if state.ssot else 0,
        "daily_tokens": state.ssot.get_daily_tokens() if state.ssot else 0,
        "scheduler_jobs": [j.id for j in state.scheduler.get_jobs()] if state.scheduler else [],
    }


@router.post("/run", response_model=RunResponse)
async def run_task(req: RunRequest, _=Depends(verify_token)):
    """태스크 실행."""
    if not req.task.strip():
        raise HTTPException(status_code=400, detail="Task cannot be empty")

    if req.sync:
        # 즉시 실행 (동기)
        try:
            result = await state.core.run(req.task, source=req.source)
            task_id = result["task_id"]

            # webhook 알림
            if state.notifier:
                await state.notifier.notify(task_id, result)

            return RunResponse(
                task_id=task_id,
                status="completed",
                message=json.dumps(result, ensure_ascii=False),
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    else:
        # 큐에 추가 (비동기)
        task_id = state.ssot.enqueue(
            req.task, priority=req.priority, source=req.source
        )
        return RunResponse(
            task_id=task_id,
            status="queued",
            message=f"Task queued with priority {req.priority}",
        )


@router.post("/plan")
async def plan_endpoint(req: RunRequest, _=Depends(verify_token)):
    """v5.0: 복잡한 태스크를 계획→실행."""
    task = req.task
    if not task.strip():
        raise HTTPException(status_code=400, detail="Task cannot be empty")

    if not state.planner or not state.plan_executor:
        raise HTTPException(status_code=503, detail="Planner not initialized")

    try:
        plan = await state.planner.plan(task)
        result = await state.plan_executor.execute(plan, source="api")
        return result
    except Exception as e:
        logger.error(f"/plan error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/worker/status")
async def worker_status(_=Depends(verify_token)):
    """v5.0: WorkerPool 상태."""
    if not state.worker_pool:
        raise HTTPException(status_code=503, detail="WorkerPool not initialized")
    return state.worker_pool.status()


@router.get("/feedback/stats")
async def feedback_stats(_=Depends(verify_token)):
    """v5.0: Feedback 통계."""
    if not state.feedback:
        raise HTTPException(status_code=503, detail="FeedbackEngine not initialized")
    return state.feedback.summary(days=30)


@router.get("/tasks")
async def list_tasks(_=Depends(verify_token), limit: int = 20):
    """최근 태스크 목록."""
    tasks = state.ssot.get_recent_tasks(limit=limit)
    return {"tasks": tasks, "count": len(tasks)}


@router.get("/status/{task_id}")
async def task_status(task_id: str, _=Depends(verify_token)):
    """태스크 상태 조회."""
    history = state.ssot.get_task_history(task_id)
    if not history["task"]:
        raise HTTPException(status_code=404, detail="Task not found")
    return history


@router.post("/reload-skills")
async def reload_skills(_=Depends(verify_token)):
    """스킬 재로딩."""
    count = state.skills.scan()
    return {"reloaded": count, "skills": list(state.skills.catalog.keys())}


@router.get("/budget")
async def budget_status(_=Depends(verify_token)):
    """일일 예산 현황."""
    return {
        "date": state.ssot._kst_date(),
        "total_tokens": state.ssot.get_daily_tokens(),
        "budget_limit": config.DAILY_TOKEN_BUDGET,
        "remaining": config.DAILY_TOKEN_BUDGET - state.ssot.get_daily_tokens(),
        "providers": {
            "cerebras": state.ssot.get_provider_calls("cerebras"),
            "groq": state.ssot.get_provider_calls("groq"),
            "gemini_pro": state.ssot.get_provider_calls("gemini_pro"),
            "gemini_flash": state.ssot.get_provider_calls("gemini_flash"),
        }
    }


@router.get("/traces")
async def trace_stats(_=Depends(verify_token), hours: int = 24):
    """프로바이더별 traces 통계."""
    stats = state.ssot.get_provider_stats(hours=hours)
    return {"hours": hours, "providers": stats}


@router.post("/signal")
async def manual_signal(kind: str, data: str, _=Depends(verify_token)):
    """수동 신호 추가 (테스트/외부 연동용)."""
    sig_id = state.ssot.save_signal(kind, data)
    return {"signal_id": sig_id}


@router.post("/judge-now")
async def trigger_judgment(_=Depends(verify_token)):
    """즉시 판단 엔진 실행 (테스트용)."""
    await judgment_job()
    return {"status": "judgment executed"}


# ============================================================
# v5.0 Phase 4: Config Tuner + Memory API
# ============================================================

@router.get("/config/pending")
async def get_pending_configs(_=Depends(verify_token)):
    """보스 승인 대기 중인 config 변경 목록."""
    return state.ssot.get_pending_config_changes()


@router.post("/config/approve/{change_id}")
async def approve_config(change_id: int, _=Depends(verify_token)):
    """config 변경 승인 + 적용."""
    success = state.ssot.approve_config_change(change_id)
    if success:
        state.config_tuner.apply_change(change_id)
        return {"status": "approved_and_applied", "id": change_id}
    return {"status": "not_found_or_already_processed", "id": change_id}


@router.post("/config/reject/{change_id}")
async def reject_config(change_id: int, _=Depends(verify_token)):
    """config 변경 거부."""
    state.ssot.reject_config_change(change_id)
    return {"status": "rejected", "id": change_id}


@router.post("/config/rollback/{change_id}")
async def rollback_config(change_id: int, _=Depends(verify_token)):
    """적용된 config 변경 롤백."""
    success = state.config_tuner.rollback(change_id)
    return {"status": "rolled_back" if success else "failed", "id": change_id}


@router.post("/config-tuner/run")
async def run_config_tuner(_=Depends(verify_token)):
    """ConfigTuner 수동 실행."""
    if not state.config_tuner:
        raise HTTPException(status_code=503, detail="ConfigTuner not initialized")
    result = await state.config_tuner.run_cycle()
    return result


@router.get("/config/history")
async def get_config_history(_=Depends(verify_token), limit: int = 20):
    """최근 config 변경 이력."""
    return state.ssot.get_config_change_history(limit=limit)


@router.get("/memory/stats")
async def get_memory_stats(_=Depends(verify_token)):
    """PlanMemory 통계."""
    return state.ssot.get_memory_stats()


@router.get("/memory/search")
async def search_memory(memory_type: str, keyword: str, _=Depends(verify_token), limit: int = 10):
    """메모리 검색."""
    if memory_type not in ("strategic", "procedural", "tool"):
        raise HTTPException(status_code=400, detail="Invalid memory_type. Use: strategic, procedural, tool")
    return state.ssot.search_memory(memory_type, keyword, limit=limit)


# ============================================================
# v6.0 Phase 2B-3: Agentless 3-Step 버그 수정
# ============================================================

class AgentlessRequest(BaseModel):
    bug_description: str
    repo_path: str = "/home/reze/reze-agent"
    error_trace: Optional[str] = None
    test_command: Optional[str] = None


@router.post("/agentless")
async def run_agentless(req: AgentlessRequest, _=Depends(verify_token)):
    """
    Agentless 3-step 자동 버그 수정.

    1. LOCALIZE: 버그 위치 탐지
    2. REPAIR: 패치 생성 및 적용
    3. VALIDATE: 테스트 검증
    """
    from agentless.pipeline import AgentlessPipeline

    if not req.bug_description.strip():
        raise HTTPException(status_code=400, detail="bug_description cannot be empty")

    pipeline = AgentlessPipeline(state.tools, state.router, state.ssot)
    result = await pipeline.run(
        bug_description=req.bug_description,
        repo_path=req.repo_path,
        error_trace=req.error_trace,
        test_command=req.test_command
    )

    return result.to_dict()


# ============================================================
# v6.0 Phase 2B-4: Manus 3종 API
# ============================================================

@router.get("/manus/failures")
async def get_failures(
    task_id: Optional[str] = None,
    hours: int = 24,
    limit: int = 100,
    _=Depends(verify_token)
):
    """실패 로그 조회."""
    from manus import FailureTracker

    tracker = FailureTracker(state.ssot)

    if task_id:
        failures = tracker.get_task_failures(task_id)
    else:
        failures = tracker.get_recent_failures(hours=hours, limit=limit)

    return {
        "count": len(failures),
        "failures": [
            {
                "failure_id": f.failure_id,
                "task_id": f.task_id,
                "failure_type": f.failure_type.value,
                "step_number": f.step_number,
                "tool_name": f.tool_name,
                "error_message": f.error_message[:500],
                "recovered": f.recovered,
                "recovery_method": f.recovery_method,
                "timestamp": f.timestamp
            }
            for f in failures
        ]
    }


@router.get("/manus/failures/analyze")
async def analyze_failures(hours: int = 24, _=Depends(verify_token)):
    """실패 패턴 분석."""
    from manus import FailureTracker

    tracker = FailureTracker(state.ssot)
    return tracker.analyze_patterns(hours=hours)


@router.get("/manus/interrupted")
async def get_interrupted(_=Depends(verify_token)):
    """중단된 태스크 목록."""
    from manus import PlanRecovery

    recovery = PlanRecovery(state.ssot)
    interrupted = await recovery.detect_interrupted()
    return {"count": len(interrupted), "tasks": interrupted}


@router.post("/manus/recover/{task_id}")
async def recover_task(
    task_id: str,
    strategy: str = "resume",
    _=Depends(verify_token)
):
    """태스크 복구 실행."""
    from manus import PlanRecovery, RecoveryStrategy

    recovery = PlanRecovery(state.ssot, getattr(state, 'planner', None))

    # 전략 파싱
    try:
        strat = RecoveryStrategy(strategy)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid strategy. Use: resume, retry_step, skip_step, replan"
        )

    # 복구 계획 생성
    plan = await recovery.create_recovery_plan(task_id, strategy=strat)
    if not plan:
        raise HTTPException(status_code=404, detail="No recoverable plan found for task")

    # 복구 실행
    new_task_id = await recovery.inject_plan(plan)

    return {
        "status": "recovery_created",
        "original_task_id": task_id,
        "recovery_id": plan.recovery_id,
        "new_task_id": new_task_id,
        "strategy": strategy,
        "resume_from_step": plan.resume_from_step
    }


@router.get("/manus/context/{task_id}")
async def get_context(task_id: str, _=Depends(verify_token)):
    """실행 컨텍스트 조회."""
    from manus import ContextManager

    manager = ContextManager()
    ctx = manager.get_context(task_id)

    if not ctx:
        return {"found": False, "task_id": task_id}

    return {
        "found": True,
        "task_id": task_id,
        "allowed_tools": list(ctx.allowed_tools),
        "permission_level": ctx.permission_level,
        "max_iterations": ctx.max_iterations,
        "timeout_seconds": ctx.timeout_seconds,
        "sandbox_mode": ctx.sandbox_mode,
        "created_at": ctx.created_at
    }


@router.get("/manus/contexts")
async def get_active_contexts(_=Depends(verify_token)):
    """활성 컨텍스트 목록."""
    from manus import ContextManager

    manager = ContextManager()
    contexts = manager.get_active_contexts()

    return {"count": len(contexts), "contexts": contexts}


# ============================================================
# v6.0 Phase 2B-5: MCP Client API
# ============================================================

class MCPConnectRequest(BaseModel):
    server_id: str
    transport_type: str  # "stdio" or "http"
    stdio_command: Optional[list] = None
    stdio_env: Optional[dict] = None
    http_url: Optional[str] = None
    http_api_key: Optional[str] = None
    timeout: int = 30


class MCPCallRequest(BaseModel):
    tool_name: str
    arguments: Optional[dict] = None


@router.post("/mcp/connect")
async def connect_mcp(req: MCPConnectRequest, _=Depends(verify_token)):
    """
    MCP 서버 연결.

    - stdio: subprocess 기반 로컬 MCP 서버
    - http: HTTP 기반 원격 MCP 서버
    """
    if req.transport_type not in ("stdio", "http"):
        raise HTTPException(
            status_code=400,
            detail="transport_type must be 'stdio' or 'http'"
        )

    if req.transport_type == "stdio" and not req.stdio_command:
        raise HTTPException(
            status_code=400,
            detail="stdio_command required for stdio transport"
        )

    if req.transport_type == "http" and not req.http_url:
        raise HTTPException(
            status_code=400,
            detail="http_url required for http transport"
        )

    result = await state.tools.connect_mcp(
        server_id=req.server_id,
        transport_type=req.transport_type,
        stdio_command=req.stdio_command,
        stdio_env=req.stdio_env,
        http_url=req.http_url,
        http_api_key=req.http_api_key,
        timeout=req.timeout
    )

    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Connection failed"))

    return result


@router.post("/mcp/call/{server_id}")
async def call_mcp_tool(server_id: str, req: MCPCallRequest, _=Depends(verify_token)):
    """MCP 도구 호출."""
    result = await state.tools.call_mcp(
        server_id=server_id,
        tool_name=req.tool_name,
        arguments=req.arguments
    )
    return {"server_id": server_id, "tool": req.tool_name, "result": result}


@router.get("/mcp/servers")
async def list_mcp_servers(_=Depends(verify_token)):
    """연결된 MCP 서버 목록."""
    servers = state.tools.list_mcp_servers()
    return {"count": len(servers), "servers": servers}


@router.get("/mcp/server/{server_id}")
async def get_mcp_server(server_id: str, _=Depends(verify_token)):
    """특정 MCP 서버 정보."""
    servers = state.tools.list_mcp_servers()
    server = next((s for s in servers if s["server_id"] == server_id), None)

    if not server:
        raise HTTPException(status_code=404, detail=f"Server '{server_id}' not found")

    return server


@router.delete("/mcp/disconnect/{server_id}")
async def disconnect_mcp(server_id: str, _=Depends(verify_token)):
    """MCP 서버 연결 해제."""
    result = await state.tools.disconnect_mcp(server_id)

    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])

    return result


# ============================================================
# v6.0 Phase 2C-1: Reflexion API
# ============================================================

class LessonFeedbackRequest(BaseModel):
    success: bool


@router.get("/reflexion/lessons")
async def list_lessons(
    failure_type: Optional[str] = None,
    tool_name: Optional[str] = None,
    limit: int = 20,
    _=Depends(verify_token)
):
    """
    교훈 목록 조회.

    - failure_type: 실패 유형 필터 (tool_error, timeout, etc.)
    - tool_name: 도구 이름 필터
    - limit: 최대 반환 수
    """
    from manus.reflexion import ReflexionEngine

    reflexion = ReflexionEngine(ssot=state.ssot)
    lessons = reflexion.get_relevant_lessons(
        tools=[tool_name] if tool_name else None,
        failure_type=failure_type,
        limit=limit
    )

    return {
        "count": len(lessons),
        "lessons": [
            {
                "lesson_id": l.lesson_id,
                "failure_type": l.failure_type,
                "tool_name": l.tool_name,
                "error_pattern": l.error_pattern,
                "lesson_text": l.lesson_text,
                "corrective_action": l.corrective_action,
                "confidence": l.confidence,
                "success_rate": round(l.success_count / l.apply_count * 100, 1) if l.apply_count > 0 else 0,
                "apply_count": l.apply_count
            }
            for l in lessons
        ]
    }


@router.get("/reflexion/lessons/{lesson_id}")
async def get_lesson(lesson_id: str, _=Depends(verify_token)):
    """특정 교훈 상세 조회."""
    from manus.reflexion import ReflexionEngine

    reflexion = ReflexionEngine(ssot=state.ssot)
    lesson = reflexion.get_lesson_by_id(lesson_id)

    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found")

    return {
        "lesson_id": lesson.lesson_id,
        "failure_id": lesson.failure_id,
        "task_id": lesson.task_id,
        "failure_type": lesson.failure_type,
        "tool_name": lesson.tool_name,
        "error_pattern": lesson.error_pattern,
        "lesson_text": lesson.lesson_text,
        "corrective_action": lesson.corrective_action,
        "avoid_pattern": lesson.avoid_pattern,
        "confidence": lesson.confidence,
        "apply_count": lesson.apply_count,
        "success_count": lesson.success_count,
        "tags": lesson.tags,
        "applicable_tools": lesson.applicable_tools
    }


@router.delete("/reflexion/lessons/{lesson_id}")
async def delete_lesson(lesson_id: str, _=Depends(verify_token)):
    """교훈 삭제."""
    from manus.reflexion import ReflexionEngine

    reflexion = ReflexionEngine(ssot=state.ssot)
    deleted = reflexion.delete_lesson(lesson_id)

    if not deleted:
        raise HTTPException(status_code=404, detail="Lesson not found")

    return {"status": "deleted", "lesson_id": lesson_id}


@router.post("/reflexion/lessons/{lesson_id}/feedback")
async def lesson_feedback(
    lesson_id: str,
    req: LessonFeedbackRequest,
    _=Depends(verify_token)
):
    """교훈 적용 피드백 (수동)."""
    from manus.reflexion import ReflexionEngine

    reflexion = ReflexionEngine(ssot=state.ssot)

    # 존재 확인
    lesson = reflexion.get_lesson_by_id(lesson_id)
    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found")

    reflexion.record_application(lesson_id, req.success)

    return {"status": "recorded", "lesson_id": lesson_id, "success": req.success}


@router.get("/reflexion/stats")
async def get_reflexion_stats(_=Depends(verify_token)):
    """교훈 통계."""
    from manus.reflexion import ReflexionEngine

    reflexion = ReflexionEngine(ssot=state.ssot)
    stats = reflexion.get_stats()

    return stats
