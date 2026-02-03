"""REZE Daemon — FastAPI 서버 + 태스크 큐 + 스케줄러 + 능동적 판단"""
import asyncio
import time
import json
import re
import subprocess
import yaml
from datetime import datetime
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import aiohttp
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import config
from ssot import SSOT
from reze_permissions import PermissionSystem, BLOG_QUALITY_GATE, LOCK_ACTIONS, is_free
from reze_tools import ToolExecutor
from reze_core import REZECore, ModelRouter, CircuitBreaker
from skills_manager import SkillsManager
from redaction import mask_text
from reze_self_healing import SelfHealing
from reze_alert import AlertManager
from reze_biz import BizTracker

import logging

# === 로깅 설정 ===
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("REZE.daemon")


# ============================================================
# 글로벌 상태 (lifespan에서 초기화)
# ============================================================
class AppState:
    ssot: SSOT = None
    permissions: PermissionSystem = None
    tools: ToolExecutor = None
    router: ModelRouter = None
    skills: SkillsManager = None
    circuit_breaker: CircuitBreaker = None
    core: REZECore = None
    scheduler: AsyncIOScheduler = None
    notifier: "WebhookNotifier" = None
    queue_worker_task: asyncio.Task = None
    # v3.3 신규
    self_healing: SelfHealing = None
    alert_manager: AlertManager = None
    biz_tracker: BizTracker = None

state = AppState()


# ============================================================
# WebhookNotifier — 결과 알림
# ============================================================
class WebhookNotifier:
    """태스크 완료 시 webhook 알림. 3회 재시도."""

    def __init__(self, url: str = ""):
        self.url = url or config.WEBHOOK_URL

    async def notify(self, task_id: str, result: dict):
        if not self.url:
            return
        payload = {
            "event": "task_complete",
            "task_id": task_id,
            "success": result.get("success", False),
            "answer_preview": str(result.get("answer", ""))[:200],
            "steps": result.get("steps", 0),
            "total_tokens": result.get("total_tokens", 0),
        }
        delays = [1, 5, 15]
        for attempt, delay in enumerate(delays):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        self.url,
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as resp:
                        if resp.status < 400:
                            logger.info(f"Webhook sent: {task_id}")
                            return
                        logger.warning(f"Webhook HTTP {resp.status} (attempt {attempt+1})")
            except Exception as e:
                logger.warning(f"Webhook failed (attempt {attempt+1}): {e}")
            if attempt < len(delays) - 1:
                await asyncio.sleep(delay)
        logger.error(f"Webhook failed after 3 attempts: {task_id}")


# ============================================================
# TaskQueue Worker — 순차 실행
# ============================================================
async def queue_worker():
    """pending 태스크를 하나씩 꺼내서 실행. worker=1."""
    logger.info("Queue worker started")
    while True:
        try:
            task = state.ssot.pop_next_pending()
            if task is None:
                await asyncio.sleep(2)
                continue

            task_id = task["id"]
            task_spec = task["task_spec"]
            source = task.get("source", "api")

            logger.info(f"Processing: {task_id} — {task_spec[:80]}")

            try:
                result = await state.core.run(task_spec, source=source)

                status = "success" if result["success"] else "failed"
                state.ssot.complete_daemon_task(
                    task_id, status, json.dumps(result, ensure_ascii=False)
                )

                # Webhook 알림
                if state.notifier:
                    await state.notifier.notify(task_id, result)

                logger.info(f"Completed: {task_id} ({status}, {result['steps']} steps)")

            except Exception as e:
                logger.error(f"Task failed: {task_id} — {e}")
                state.ssot.complete_daemon_task(task_id, "error", str(e))

        except asyncio.CancelledError:
            logger.info("Queue worker shutting down")
            break
        except Exception as e:
            logger.error(f"Queue worker error: {e}")
            await asyncio.sleep(5)


# ============================================================
# 스케줄러 Jobs — 능동적 판단
# ============================================================

# SaaS 헬스체크 대상
SAAS_HEALTH_ENDPOINTS = {
    "postpilot-backend": "http://localhost:8000/health",
    "postpilot-frontend": "http://localhost:3000",
    "ai-tools-lab": "http://localhost:3005",
    "browserpilot-api": "http://localhost:8100/health",
    "agenthub-api": "http://localhost:8101/health",
    "rag-service": "http://localhost:8020/health",
    "quotepilot-api": "http://localhost:8030/health",
    "rapidapi-server": "http://localhost:8001/health",
    "rapidapi-nocode": "http://localhost:8002/health",
}

async def health_check_job():
    """매시간: 서버 상태 체크 → 이상 있으면 신호 저장."""
    logger.info("Running health check")
    try:
        result = await state.tools.execute("shell", "df -h / | tail -1", source="schedule")
        state.ssot.save_signal("disk", result)

        result = await state.tools.execute("shell", "free -h | grep Mem", source="schedule")
        state.ssot.save_signal("memory", result)

        result = await state.tools.execute(
            "shell",
            "docker ps --format '{{.Names}}:{{.Status}}' 2>/dev/null || echo 'docker not available'",
            source="schedule",
        )
        state.ssot.save_signal("docker", result)

        result = await state.tools.execute(
            "shell",
            "pm2 jlist 2>/dev/null | python3 -c \"import sys,json; data=json.load(sys.stdin); print(','.join(f'{p[\\\"name\\\"]}:{p[\\\"pm2_env\\\"][\\\"status\\\"]}' for p in data))\" 2>/dev/null || echo 'pm2 not available'",
            source="schedule",
        )
        state.ssot.save_signal("pm2", result)

        # SaaS 개별 헬스체크
        down_services = []
        try:
            timeout = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                for name, url in SAAS_HEALTH_ENDPOINTS.items():
                    try:
                        async with session.get(url) as resp:
                            if resp.status >= 500:
                                down_services.append(f"{name}(HTTP {resp.status})")
                    except Exception:
                        down_services.append(f"{name}(unreachable)")

            state.ssot.save_signal("saas_health", json.dumps({
                "down": down_services,
                "total": len(SAAS_HEALTH_ENDPOINTS),
                "healthy": len(SAAS_HEALTH_ENDPOINTS) - len(down_services),
            }))

            if down_services:
                logger.warning(f"Services down: {down_services}")
                # Self-Healing 연동
                if state.self_healing:
                    for svc in down_services:
                        try:
                            await state.self_healing.handle(svc)
                        except Exception as e:
                            logger.error(f"Self-heal error for {svc}: {e}")
                # Alert 연동
                if state.alert_manager:
                    severity = "critical" if len(down_services) >= 3 else "warning"
                    await state.alert_manager.send(
                        severity, "health_check",
                        f"서비스 다운 ({len(down_services)}개): {', '.join(down_services)}"
                    )
        except Exception as e:
            logger.error(f"SaaS health check failed: {e}")

        logger.info("Health check completed")
    except Exception as e:
        logger.error(f"Health check failed: {e}")


async def judgment_job():
    """6시간마다: 최근 신호를 보고 '할 일 있나?' 판단. LLM 1회."""
    logger.info("Running judgment engine")
    try:
        # 최근 6시간 신호 수집
        signals = state.ssot.get_recent_signals(hours=6)
        if not signals:
            logger.info("No signals to judge")
            return

        signals_text = "\n".join(
            f"[{s['kind']}] {s['data'][:200]}" for s in signals[:20]
        )

        # LLM에게 판단 요청
        response = await state.router.call(
            "reasoning",
            [{
                "role": "user",
                "content": (
                    f"너는 서버 관리 AI다. 최근 6시간 시스템 신호를 분석해라:\n\n"
                    f"{signals_text}\n\n"
                    f"문제가 있거나 조치가 필요한 것이 있으면 JSON 배열로 태스크를 제안해라:\n"
                    f'[{{"task": "설명", "priority": 1-5}}]\n\n'
                    f"문제 없으면 빈 배열 []을 반환해라.\n"
                    f"JSON만 반환. 다른 텍스트 금지."
                )
            }],
            system="시스템 신호를 분석하고 필요한 조치를 판단하는 전문가.",
        )

        # 파싱
        text = response.text.strip()
        # fence 제거
        text = text.replace("```json", "").replace("```", "").strip()

        try:
            tasks = json.loads(text)
        except json.JSONDecodeError:
            logger.warning(f"Judgment parse failed: {text[:100]}")
            return

        if not isinstance(tasks, list) or not tasks:
            logger.info("Judgment: no action needed")
            return

        # 태스크 큐에 추가
        for t in tasks[:3]:  # 최대 3개
            if isinstance(t, dict) and "task" in t:
                priority = min(max(int(t.get("priority", 1)), 1), 5)
                task_id = state.ssot.enqueue(
                    t["task"], priority=priority, source="judgment"
                )
                logger.info(f"Judgment created task: {task_id} — {t['task'][:60]}")

    except Exception as e:
        logger.error(f"Judgment engine failed: {e}")


async def self_review_job():
    """매주 월요일: 지난 주 실행 결과 분석. 자기 리뷰."""
    logger.info("Running weekly self-review")
    try:
        recent = state.ssot.get_recent_tasks(limit=50)
        if not recent:
            return

        total = len(recent)
        success = sum(1 for t in recent if t.get("status") == "success")
        failed = sum(1 for t in recent if t.get("status") in ("error", "failed", "incomplete"))

        summary = (
            f"최근 태스크 {total}개: 성공 {success}, 실패 {failed}, "
            f"성공률 {success/total*100:.0f}%"
        )

        state.ssot.save_signal("self_review", summary)
        logger.info(f"Self-review: {summary}")

    except Exception as e:
        logger.error(f"Self-review failed: {e}")


# ============================================================
# v3.3 신규 Jobs
# ============================================================

def _parse_skill_meta(skill_md: Path) -> dict:
    """SKILL.md에서 YAML frontmatter 파싱."""
    try:
        content = skill_md.read_text()
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                return yaml.safe_load(parts[1]) or {}
    except Exception:
        pass
    return {}


async def skill_health_check_job():
    """모든 스킬의 health_checks를 실행. 실패 시 자동수리."""
    logger.info("Running skill health checks")
    skills_dir = Path.home() / "reze-agent" / "skills"
    total_checks = 0
    total_pass = 0
    total_fail = 0

    for skill_dir in sorted(skills_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue

        meta = _parse_skill_meta(skill_md)
        if not meta.get("health_checks"):
            continue

        for check in meta["health_checks"]:
            total_checks += 1
            name = f"{skill_dir.name}/{check['name']}"

            try:
                result = subprocess.run(
                    ["bash", "-c", check["command"]],
                    capture_output=True, text=True, timeout=30
                )
                output = result.stdout.strip()
                ok = True

                if check.get("expect"):
                    ok = check["expect"] in output
                elif check.get("verify_check"):
                    try:
                        ok = eval(check["verify_check"], {"output": output, "int": int, "float": float})
                    except Exception:
                        ok = False
                if result.returncode != 0 and not check.get("verify_check"):
                    ok = False

            except subprocess.TimeoutExpired:
                ok = False
                output = "TIMEOUT"
            except Exception as e:
                ok = False
                output = str(e)

            if ok:
                total_pass += 1
                state.ssot.save_signal("health_ok", json.dumps({"check": name}))
            else:
                total_fail += 1
                severity = check.get("severity", "warning")
                state.ssot.save_signal("health_fail", json.dumps({
                    "check": name, "output": output[:200], "severity": severity
                }))

                # 자동수리 시도
                for fix in meta.get("fix_actions", []):
                    if fix.get("trigger") and fix["trigger"] in check["name"]:
                        logger.info(f"Auto-fix attempting: {fix['command'][:50]}")
                        try:
                            subprocess.run(
                                ["bash", "-c", fix["command"]],
                                capture_output=True, text=True, timeout=60
                            )
                            state.ssot.save_signal("auto_fix_success", json.dumps({
                                "skill": skill_dir.name, "fix": fix["command"][:100]
                            }))
                        except Exception as e:
                            logger.error(f"Auto-fix failed: {e}")
                        break

    logger.info(f"Skill health check: {total_pass}/{total_checks} passed, {total_fail} failed")


async def daily_report_job():
    """데일리 리포트 생성 → Discord 전송."""
    logger.info("Generating daily report")
    today = datetime.now(config.KST).strftime("%Y-%m-%d")

    try:
        # 오늘 데이터 수집
        signals_today = state.ssot.get_signals_by_date(today)

        blog_published = [s for s in signals_today if s["kind"] == "blog_published"]
        blog_held = [s for s in signals_today if s["kind"] == "blog_held"]
        auto_fixes = [s for s in signals_today if s["kind"] == "auto_fix_success"]
        health_fails = [s for s in signals_today if s["kind"] == "health_fail"]
        evolutions = [s for s in signals_today if s["kind"] == "self_evolution_success"]
        approvals = [s for s in signals_today if s["kind"] == "approval_request"]

        # 리소스
        disk_result = subprocess.run(
            ["bash", "-c", "df / --output=pcent | tail -1 | tr -d ' %'"],
            capture_output=True, text=True
        )
        disk = disk_result.stdout.strip() + "%" if disk_result.returncode == 0 else "?"

        mem_result = subprocess.run(
            ["bash", "-c", "free | grep Mem | awk '{printf \"%.0f\", $3/$2*100}'"],
            capture_output=True, text=True
        )
        memory = mem_result.stdout.strip() + "%" if mem_result.returncode == 0 else "?"

        tokens = state.ssot.get_daily_tokens()

        report = f"""REZE 데일리 리포트 - {today}

오늘 한 일 (FREE)
"""

        if blog_published:
            for b in blog_published:
                try:
                    p = json.loads(b.get("data", "{}"))
                    report += f"  발행: \"{p.get('title', '?')}\" (점수: {p.get('score', '?')})\n"
                except:
                    pass

        if blog_held:
            for b in blog_held:
                try:
                    p = json.loads(b.get("data", "{}"))
                    report += f"  보류: \"{p.get('title', '?')}\" (품질 미달)\n"
                except:
                    pass

        if auto_fixes:
            for f in auto_fixes:
                try:
                    p = json.loads(f.get("data", "{}"))
                    report += f"  자동수리: {p.get('skill', '?')}\n"
                except:
                    pass

        if evolutions:
            for e in evolutions:
                try:
                    p = json.loads(e.get("data", "{}"))
                    report += f"  자기진화: {p.get('tech', '?')}\n"
                except:
                    pass

        if not (blog_published or blog_held or auto_fixes or evolutions):
            report += "  (특별한 작업 없음)\n"

        healthy_count = len(SAAS_HEALTH_ENDPOINTS) - len([h for h in health_fails])
        report += f"""
서비스: {healthy_count}/{len(SAAS_HEALTH_ENDPOINTS)} 정상

리소스
  토큰: {tokens:,} / 500,000
  디스크: {disk}
  메모리: {memory}
"""

        if approvals:
            report += "\n승인 대기 (LOCK)\n"
            for a in approvals:
                try:
                    p = json.loads(a.get("data", "{}"))
                    report += f"  {p.get('action', '?')}: {p.get('reason', '?')}\n"
                except:
                    pass
        else:
            report += "\n승인 대기 (LOCK): 없음\n"

        # Discord 전송
        async with aiohttp.ClientSession() as session:
            await session.post(
                config.DISCORD_WEBHOOK_DAILY,
                json={"content": report[:2000]}
            )

        # SSOT에 기록
        state.ssot.save_signal("daily_report", json.dumps({"date": today}))
        logger.info("Daily report sent")

    except Exception as e:
        logger.error(f"Daily report failed: {e}")


async def request_approval(action: str, reason: str, analysis: str = ""):
    """LOCK 행동 시 Discord로 승인 요청."""
    msg = (
        f"REZE 승인 요청\n\n"
        f"행동: {action}\n"
        f"이유: {reason}\n"
    )
    if analysis:
        msg += f"분석: {analysis[:500]}\n"
    msg += "\n-> 승인 / 거절 / 수정"

    try:
        async with aiohttp.ClientSession() as session:
            await session.post(
                config.DISCORD_WEBHOOK_ALERT,
                json={"content": msg[:2000]}
            )
        state.ssot.save_signal("approval_request", json.dumps({
            "action": action, "reason": reason, "status": "pending"
        }))
        logger.info(f"Approval requested: {action}")
    except Exception as e:
        logger.error(f"Approval request failed: {e}")


# ============================================================
# Lifespan — 초기화 + 종료
# ============================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """서버 시작/종료 관리."""
    logger.info("=== REZE Agent v3.3 Starting ===")

    # 초기화
    state.ssot = SSOT()
    state.permissions = PermissionSystem()
    state.tools = ToolExecutor(state.ssot, state.permissions)
    state.router = ModelRouter(state.ssot)
    state.skills = SkillsManager()
    state.circuit_breaker = CircuitBreaker(state.ssot)
    state.core = REZECore(
        state.ssot, state.tools, state.permissions,
        state.router, state.skills, state.circuit_breaker,
    )
    state.notifier = WebhookNotifier()

    # v3.3 신규 모듈
    state.self_healing = SelfHealing(
        state.tools, state.ssot, state.router, dry_run=False  # 자동수리 활성화
    )
    state.alert_manager = AlertManager(state.ssot)
    state.biz_tracker = BizTracker(state.ssot)  # LS API key는 추후 설정

    # 스케줄러
    state.scheduler = AsyncIOScheduler(timezone="Asia/Seoul")
    state.scheduler.add_job(health_check_job, "interval", hours=1, id="health_check")
    state.scheduler.add_job(judgment_job, "interval", hours=6, id="judgment")
    state.scheduler.add_job(self_review_job, "cron", day_of_week="mon", hour=9, id="self_review")

    # v3.3 신규 스케줄
    state.scheduler.add_job(
        state.biz_tracker.collect, "interval", hours=6, id="biz_check"
    )
    state.scheduler.add_job(
        skill_health_check_job, "interval", hours=1, id="skill_health_check"
    )
    state.scheduler.add_job(
        daily_report_job, "cron", hour=21, minute=0, id="daily_report_discord"
    )

    state.scheduler.start()

    # 큐 워커
    state.queue_worker_task = asyncio.create_task(queue_worker())

    providers = list(state.router.providers.keys())
    skills_count = len(state.skills.catalog)
    logger.info(f"Providers: {providers}")
    logger.info(f"Skills: {skills_count}")
    logger.info(f"Scheduler jobs: {[j.id for j in state.scheduler.get_jobs()]}")
    logger.info("=== REZE Agent v3.3 Ready ===")

    yield

    # 종료
    logger.info("=== REZE Agent Shutting Down ===")
    state.scheduler.shutdown(wait=False)

    if state.queue_worker_task:
        state.queue_worker_task.cancel()
        try:
            await state.queue_worker_task
        except asyncio.CancelledError:
            pass

    state.ssot.close()
    logger.info("=== REZE Agent Stopped ===")


# ============================================================
# FastAPI App
# ============================================================
app = FastAPI(
    title="REZE Agent",
    version="3.3",
    lifespan=lifespan,
)


# === 인증 ===
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


# === Request/Response 모델 ===
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


# === 엔드포인트 ===

@app.get("/health")
async def health():
    """헬스체크 (인증 없음)."""
    return {"status": "ok", "version": "3.3", "agent": "REZE"}


@app.get("/health/detail")
async def health_detail(_=Depends(verify_token)):
    """상세 헬스체크."""
    return {
        "status": "ok",
        "version": "3.3",
        "providers": list(state.router.providers.keys()),
        "skills": list(state.skills.catalog.keys()),
        "pending_tasks": state.ssot.count_pending(),
        "daily_tokens": state.ssot.get_daily_tokens(),
        "scheduler_jobs": [j.id for j in state.scheduler.get_jobs()],
    }


@app.post("/run", response_model=RunResponse)
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


@app.get("/tasks")
async def list_tasks(_=Depends(verify_token), limit: int = 20):
    """최근 태스크 목록."""
    tasks = state.ssot.get_recent_tasks(limit=limit)
    return {"tasks": tasks, "count": len(tasks)}


@app.get("/status/{task_id}")
async def task_status(task_id: str, _=Depends(verify_token)):
    """태스크 상태 조회."""
    history = state.ssot.get_task_history(task_id)
    if not history["task"]:
        raise HTTPException(status_code=404, detail="Task not found")
    return history


@app.post("/reload-skills")
async def reload_skills(_=Depends(verify_token)):
    """스킬 재로딩."""
    count = state.skills.scan()
    return {"reloaded": count, "skills": list(state.skills.catalog.keys())}


@app.get("/budget")
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


@app.get("/traces")
async def trace_stats(_=Depends(verify_token), hours: int = 24):
    """프로바이더별 traces 통계."""
    stats = state.ssot.get_provider_stats(hours=hours)
    return {"hours": hours, "providers": stats}


@app.post("/signal")
async def manual_signal(kind: str, data: str, _=Depends(verify_token)):
    """수동 신호 추가 (테스트/외부 연동용)."""
    sig_id = state.ssot.save_signal(kind, data)
    return {"signal_id": sig_id}


@app.post("/judge-now")
async def trigger_judgment(_=Depends(verify_token)):
    """즉시 판단 엔진 실행 (테스트용)."""
    await judgment_job()
    return {"status": "judgment executed"}
