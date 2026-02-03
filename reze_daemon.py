"""REZE Daemon — FastAPI 서버 + 태스크 큐 + 스케줄러 + 능동적 판단"""
import asyncio
import time
import json
import re
import subprocess
import yaml
from datetime import datetime, timedelta
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
        # Phase 3: 가속 검증 - 기한 도래한 발견 즉시 검증
        try:
            from accelerated_learning import AcceleratedLearning
            learner = AcceleratedLearning(
                _call_llm_for_learning,
                state.ssot.save_signal,
                state.ssot._get_db
            )
            await learner.verify_due()
        except Exception as e:
            logger.warning(f"Accelerated verification failed: {e}")

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
# Phase 2: Discovery Pipeline & Research Jobs
# ============================================================

async def process_discovery(discovery_type: str, source_skill: str, detail: dict) -> int:
    """
    발견 처리 파이프라인: Detect → Interpret → Connect → Act → Verify

    Returns: discovery_id from SSOT
    """
    logger.info(f"Processing discovery: {discovery_type} from {source_skill}")

    # 1. Save discovery to SSOT
    discovery_id = state.ssot.save_discovery(
        discovery_type=discovery_type,
        source_skill=source_skill,
        detail=json.dumps(detail, ensure_ascii=False),
        urgency=detail.get("urgency", "medium")
    )

    # Phase 3: 가속 검증 스케줄링 (7일 고정 대신 LEARNING_SPEED 기반)
    try:
        from accelerated_learning import AcceleratedLearning
        learner = AcceleratedLearning(
            _call_llm_for_learning,
            state.ssot.save_signal,
            state.ssot._get_db
        )
        await learner.schedule_verification(discovery_id, discovery_type)
    except Exception as e:
        logger.warning(f"Accelerated verification scheduling failed: {e}")

    # 2. Interpret & Connect using CONNECTION_MAP
    connection = config.CONNECTION_MAP.get(discovery_type)
    if not connection:
        logger.warning(f"No connection map for: {discovery_type}")
        return discovery_id

    affects = connection.get("affects", [])
    actions = connection.get("actions", [])
    urgency = connection.get("urgency", "medium")

    # 3. Generate actions based on urgency
    if urgency == "critical":
        # 즉시 행동 생성
        for action in actions[:2]:
            task_spec = f"[{discovery_type}] {action}: {detail.get('summary', str(detail)[:100])}"
            task_id = state.ssot.enqueue(task_spec, priority=1, source="discovery")
            logger.info(f"Critical discovery → task: {task_id}")

    elif urgency == "high":
        # 우선순위 높은 태스크 생성
        task_spec = f"[{discovery_type}] 분석 및 대응: {detail.get('summary', str(detail)[:100])}"
        task_id = state.ssot.enqueue(task_spec, priority=2, source="discovery")
        logger.info(f"High urgency discovery → task: {task_id}")

    elif urgency == "medium":
        # 일반 큐에 추가
        task_spec = f"[{discovery_type}] 검토: {detail.get('summary', str(detail)[:100])}"
        task_id = state.ssot.enqueue(task_spec, priority=3, source="discovery")

    # low urgency: 기록만, 주간 전략에서 처리

    # 4. Alert if critical/high
    if urgency in ("critical", "high") and state.alert_manager:
        severity = "critical" if urgency == "critical" else "warning"
        await state.alert_manager.send(
            severity, discovery_type,
            f"발견: {detail.get('summary', str(detail)[:200])}"
        )

    # 5. Record connection for later analysis
    state.ssot.save_signal("discovery_connected", json.dumps({
        "discovery_id": discovery_id,
        "type": discovery_type,
        "affects": affects,
        "actions_generated": actions[:2] if urgency in ("critical", "high") else []
    }))

    return discovery_id


async def trend_scan_job():
    """매일 08:00: AI/노코드 트렌드 스캔."""
    logger.info("Running trend scan")

    try:
        # 트렌드 소스 목록
        sources = [
            {"name": "Product Hunt", "url": "https://www.producthunt.com/topics/artificial-intelligence"},
            {"name": "Hacker News", "url": "https://news.ycombinator.com/"},
            {"name": "AI Tools Directory", "url": "https://www.futuretools.io/"},
        ]

        discoveries = []

        for source in sources:
            try:
                # LLM에게 트렌드 분석 요청
                response = await state.router.call(
                    "fast",
                    [{
                        "role": "user",
                        "content": (
                            f"다음 사이트에서 주목할 AI/노코드 도구 트렌드를 분석해라: {source['name']}\n\n"
                            f"1. 새로운 도구가 있으면 JSON으로 보고:\n"
                            f'{{"type": "new_tool_discovered", "tool_name": "...", "category": "...", "summary": "..."}}\n\n'
                            f"2. 없으면 빈 객체 {{}}\n\n"
                            f"JSON만 반환."
                        )
                    }],
                    system="AI 도구 트렌드 분석가. 새롭고 주목할만한 도구만 보고한다."
                )

                text = response.text.strip()
                text = text.replace("```json", "").replace("```", "").strip()

                try:
                    result = json.loads(text)
                    if result and result.get("type"):
                        discoveries.append(result)
                except json.JSONDecodeError:
                    pass

            except Exception as e:
                logger.warning(f"Trend scan failed for {source['name']}: {e}")

        # 발견 처리
        for d in discoveries:
            disc_type = d.get("type", "new_tool_discovered")
            await process_discovery(disc_type, "trend_scan", d)

            # Phase 3: self_improvement_tech 발견 시 자기 진화 시도
            if disc_type == "self_improvement_tech" and d.get("tool_name"):
                try:
                    from self_evolution import SelfEvolution
                    evolver = SelfEvolution(
                        _call_llm_for_learning,
                        state.ssot.save_signal,
                        state.ssot._get_db
                    )
                    tech_info = {
                        "name": d.get("tool_name", "unknown")[:50],
                        "description": d.get("summary", "")[:200],
                        "source": "trend_scan"
                    }
                    evo_result = await evolver.evaluate_and_evolve(tech_info)
                    if evo_result.get("success"):
                        logger.info(f"Auto-evolution: {tech_info['name']}")
                except Exception as e:
                    logger.warning(f"Self-evolution from trend scan failed: {e}")

        state.ssot.save_signal("trend_scan_complete", json.dumps({
            "discoveries": len(discoveries),
            "sources_checked": len(sources)
        }))

        logger.info(f"Trend scan complete: {len(discoveries)} discoveries")

    except Exception as e:
        logger.error(f"Trend scan failed: {e}")


async def competitor_check_job():
    """매주 월요일 09:00: 경쟁사 모니터링."""
    logger.info("Running competitor check")

    try:
        # 모니터링 대상
        competitors = {
            "postpilot": ["buffer.com", "hootsuite.com", "later.com"],
            "quotepilot": ["quotefancy.com", "brainyquote.com"],
            "browserpilot": ["browse.ai", "bardeen.ai", "axiom.ai"],
        }

        discoveries = []

        for product, comp_list in competitors.items():
            for comp in comp_list:
                try:
                    response = await state.router.call(
                        "fast",
                        [{
                            "role": "user",
                            "content": (
                                f"{comp}의 최근 변화를 분석해라:\n"
                                f"- 가격 변동\n"
                                f"- 새 기능\n"
                                f"- 중요 공지\n\n"
                                f"변화가 있으면 JSON:\n"
                                f'{{"type": "competitor_price_change" 또는 "competitor_new_feature", '
                                f'"competitor": "{comp}", "product": "{product}", "summary": "..."}}\n\n'
                                f"없으면 {{}}"
                            )
                        }],
                        system="경쟁사 분석가. 중요한 변화만 보고한다."
                    )

                    text = response.text.strip()
                    text = text.replace("```json", "").replace("```", "").strip()

                    try:
                        result = json.loads(text)
                        if result and result.get("type"):
                            discoveries.append(result)
                    except json.JSONDecodeError:
                        pass

                except Exception as e:
                    logger.warning(f"Competitor check failed for {comp}: {e}")

        for d in discoveries:
            await process_discovery(d.get("type"), "competitor_check", d)

        state.ssot.save_signal("competitor_check_complete", json.dumps({
            "discoveries": len(discoveries)
        }))

        logger.info(f"Competitor check complete: {len(discoveries)} discoveries")

    except Exception as e:
        logger.error(f"Competitor check failed: {e}")


async def keyword_scan_job():
    """매주 수요일 09:00: 키워드 기회 발굴."""
    logger.info("Running keyword scan")

    try:
        # 타겟 니치
        niches = [
            "ai tools for small business",
            "nocode automation tools",
            "ai writing assistant",
            "browser automation",
            "social media scheduling",
        ]

        discoveries = []

        for niche in niches:
            try:
                response = await state.router.call(
                    "fast",
                    [{
                        "role": "user",
                        "content": (
                            f"'{niche}' 관련 블로그 키워드 기회를 분석해라:\n"
                            f"- 검색량이 있지만 경쟁이 낮은 롱테일 키워드\n"
                            f"- 최근 트렌드 키워드\n\n"
                            f"기회가 있으면 JSON:\n"
                            f'{{"type": "keyword_opportunity", "keyword": "...", '
                            f'"estimated_difficulty": "low/medium/high", "summary": "..."}}\n\n'
                            f"없으면 {{}}"
                        )
                    }],
                    system="SEO 키워드 분석가. 실제 기회만 보고한다."
                )

                text = response.text.strip()
                text = text.replace("```json", "").replace("```", "").strip()

                try:
                    result = json.loads(text)
                    if result and result.get("type"):
                        discoveries.append(result)
                except json.JSONDecodeError:
                    pass

            except Exception as e:
                logger.warning(f"Keyword scan failed for {niche}: {e}")

        for d in discoveries:
            await process_discovery("keyword_opportunity", "keyword_scan", d)

        state.ssot.save_signal("keyword_scan_complete", json.dumps({
            "discoveries": len(discoveries)
        }))

        logger.info(f"Keyword scan complete: {len(discoveries)} discoveries")

    except Exception as e:
        logger.error(f"Keyword scan failed: {e}")


async def strategic_thinking_job():
    """매주 일요일 20:00: 주간 회고 + 다음 주 전략."""
    logger.info("Running strategic thinking")

    try:
        # 이번 주 데이터 수집
        today = datetime.now(config.KST)
        week_start = (today - timedelta(days=7)).strftime("%Y-%m-%d")

        # 주간 신호 수집
        signals = state.ssot.get_recent_signals(hours=168)  # 7일

        # 분류
        discoveries = [s for s in signals if s["kind"].startswith("discovery")]
        blog_published = [s for s in signals if s["kind"] == "blog_published"]
        auto_fixes = [s for s in signals if s["kind"] == "auto_fix_success"]
        health_fails = [s for s in signals if s["kind"] == "health_fail"]

        # LLM에게 전략 분석 요청
        response = await state.router.call(
            "reasoning",
            [{
                "role": "user",
                "content": (
                    f"REZE 주간 전략 회의.\n\n"
                    f"이번 주 실적:\n"
                    f"- 블로그 발행: {len(blog_published)}개\n"
                    f"- 자동 수리: {len(auto_fixes)}회\n"
                    f"- 장애: {len(health_fails)}건\n"
                    f"- 발견: {len(discoveries)}건\n\n"
                    f"비즈니스 목표: 월 $3,100~$9,500 수익\n\n"
                    f"다음 JSON 형식으로 분석 제공:\n"
                    f'{{\n'
                    f'  "retrospective": {{"biggest_win": "...", "biggest_issue": "..."}},\n'
                    f'  "opportunities": ["..."],\n'
                    f'  "risks": ["..."],\n'
                    f'  "next_week_priorities": [\n'
                    f'    {{"rank": 1, "goal": "...", "actions": ["..."], "expected_outcome": "..."}}\n'
                    f'  ],\n'
                    f'  "lessons": ["..."]\n'
                    f'}}\n\n'
                    f"JSON만 반환."
                )
            }],
            system="비즈니스 전략가. 데이터 기반 의사결정."
        )

        text = response.text.strip()
        text = text.replace("```json", "").replace("```", "").strip()

        try:
            strategy = json.loads(text)

            # 우선순위 행동 → 태스크 큐
            for p in strategy.get("next_week_priorities", [])[:3]:
                for action in p.get("actions", [])[:2]:
                    task_id = state.ssot.enqueue(
                        f"[전략] {action}",
                        priority=p.get("rank", 3),
                        source="strategy"
                    )
                    logger.info(f"Strategy task created: {task_id}")

            # 교훈 → 신호 저장
            for lesson in strategy.get("lessons", []):
                state.ssot.save_signal("lesson_learned", lesson)

            state.ssot.save_signal("weekly_strategy", json.dumps(strategy))

        except json.JSONDecodeError:
            logger.warning(f"Strategy parse failed: {text[:200]}")

        logger.info("Strategic thinking complete")

    except Exception as e:
        logger.error(f"Strategic thinking failed: {e}")


async def weekly_report_job():
    """매주 일요일 21:00: 주간 리포트 → Discord."""
    logger.info("Generating weekly report")

    try:
        today = datetime.now(config.KST)
        week_start = (today - timedelta(days=7)).strftime("%Y-%m-%d")

        # 주간 데이터
        signals = state.ssot.get_recent_signals(hours=168)

        blog_published = len([s for s in signals if s["kind"] == "blog_published"])
        discoveries = len([s for s in signals if s["kind"].startswith("discovery")])
        auto_fixes = len([s for s in signals if s["kind"] == "auto_fix_success"])
        tasks_completed = len(state.ssot.get_recent_tasks(limit=100))

        # 전략 데이터
        strategy_signals = [s for s in signals if s["kind"] == "weekly_strategy"]
        strategy_summary = ""
        if strategy_signals:
            try:
                strat = json.loads(strategy_signals[-1].get("data", "{}"))
                biggest_win = strat.get("retrospective", {}).get("biggest_win", "N/A")
                priorities = strat.get("next_week_priorities", [])
                if priorities:
                    p1 = priorities[0].get("goal", "N/A")
                    strategy_summary = f"\n주간 하이라이트: {biggest_win}\n다음 주 1순위: {p1}"
            except:
                pass

        report = f"""REZE 주간 리포트 ({week_start} ~ {today.strftime('%Y-%m-%d')})

요약
  블로그 발행: {blog_published}개
  발견/기회: {discoveries}건
  자동 수리: {auto_fixes}회
  태스크 완료: {tasks_completed}건
{strategy_summary}

보스님, 이번 주도 열심히 일했습니다! 🫡
"""

        # Discord 전송
        async with aiohttp.ClientSession() as session:
            await session.post(
                config.DISCORD_WEBHOOK_DAILY,
                json={"content": report[:2000]}
            )

        state.ssot.save_signal("weekly_report", json.dumps({
            "week_start": week_start,
            "blog_published": blog_published,
            "discoveries": discoveries
        }))

        logger.info("Weekly report sent")

    except Exception as e:
        logger.error(f"Weekly report failed: {e}")


async def security_scan_job():
    """매주 토요일 03:00: 보안 스캔."""
    logger.info("Running security scan")

    try:
        findings = []

        # 1. npm audit (workspace 내 프로젝트들)
        workspace = Path.home() / "reze-agent" / "workspace"
        for project in workspace.iterdir():
            package_json = project / "package.json"
            if package_json.exists():
                try:
                    result = subprocess.run(
                        ["npm", "audit", "--json"],
                        cwd=str(project),
                        capture_output=True, text=True, timeout=60
                    )
                    if result.returncode != 0:
                        try:
                            audit = json.loads(result.stdout)
                            vulns = audit.get("metadata", {}).get("vulnerabilities", {})
                            critical = vulns.get("critical", 0) + vulns.get("high", 0)
                            if critical > 0:
                                findings.append({
                                    "type": "npm_vulnerability",
                                    "project": project.name,
                                    "critical_high": critical
                                })
                        except:
                            pass
                except Exception:
                    pass

        # 2. pip check (Python deps)
        try:
            result = subprocess.run(
                ["pip", "check"],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode != 0:
                findings.append({
                    "type": "pip_conflict",
                    "detail": result.stdout[:200]
                })
        except Exception:
            pass

        # 3. 민감 파일 체크
        sensitive_patterns = [".env", "credentials", "secret", "private_key"]
        for pattern in sensitive_patterns:
            try:
                result = subprocess.run(
                    ["find", str(Path.home() / "reze-agent"), "-name", f"*{pattern}*", "-type", "f"],
                    capture_output=True, text=True, timeout=30
                )
                files = [f for f in result.stdout.strip().split("\n") if f and not "node_modules" in f]
                for f in files:
                    # .env는 정상, 하지만 .env.backup 같은건 위험
                    if f.endswith(".env"):
                        continue
                    findings.append({
                        "type": "sensitive_file",
                        "path": f
                    })
            except Exception:
                pass

        # 4. 결과 처리
        if findings:
            # 발견 저장
            for f in findings:
                if f["type"] == "npm_vulnerability" and f.get("critical_high", 0) >= 5:
                    await process_discovery(
                        "security_vulnerability",
                        "security_scan",
                        {"summary": f"npm 취약점: {f['project']} ({f['critical_high']}개)", **f}
                    )

            state.ssot.save_signal("security_scan", json.dumps({
                "findings": len(findings),
                "details": findings[:10]
            }))

            # Alert for critical
            critical_count = sum(1 for f in findings if f["type"] == "npm_vulnerability" and f.get("critical_high", 0) >= 5)
            if critical_count > 0 and state.alert_manager:
                await state.alert_manager.send(
                    "warning", "security_scan",
                    f"보안 스캔: {critical_count}개 프로젝트에서 심각한 취약점 발견"
                )
        else:
            state.ssot.save_signal("security_scan", json.dumps({"findings": 0, "status": "clean"}))

        logger.info(f"Security scan complete: {len(findings)} findings")

    except Exception as e:
        logger.error(f"Security scan failed: {e}")


# ============================================================
# Phase 3: Self-Evolution & Accelerated Learning Jobs
# ============================================================

async def _call_llm_for_learning(prompt: str, role: str = "reasoning") -> str:
    """학습/진화 모듈용 LLM 호출 헬퍼."""
    response = await state.router.call(
        role,
        [{"role": "user", "content": prompt}],
        system="REZE 자기 진화 및 학습 시스템."
    )
    return response.text


async def self_assessment_job():
    """
    매주 금 15시: REZE 자기 평가.
    - 이번 주 진화 결과 리뷰
    - 내 코드 약점 분석
    - 메타학습 실행
    """
    logger.info("=== Self Assessment Start ===")

    from self_evolution import SelfEvolution
    from accelerated_learning import AcceleratedLearning

    evolver = SelfEvolution(
        _call_llm_for_learning,
        state.ssot.save_signal,
        state.ssot._get_db
    )
    learner = AcceleratedLearning(
        _call_llm_for_learning,
        state.ssot.save_signal,
        state.ssot._get_db
    )

    db = state.ssot._get_db()

    # 이번 주 진화 결과
    evolutions = db.execute(
        """SELECT tech_name, status, performance_before, performance_after
           FROM evolutions WHERE created_at > datetime('now', '-7 days')"""
    ).fetchall()

    success = sum(1 for e in evolutions if e[1] == 'success')
    failed = sum(1 for e in evolutions if e[1] == 'failed')

    # 이번 주 교훈 수
    lessons_count = db.execute(
        "SELECT COUNT(*) FROM signals WHERE kind='lesson_learned' AND created_at > datetime('now', '-7 days')"
    ).fetchone()[0]

    # 자기 분석
    self_state = evolver._analyze_self()

    assessment = await _call_llm_for_learning(
        f"""REZE 자기 평가.

내 코드: {self_state['python_files']}
총 코드: {self_state['total_lines']}줄
의존성: {self_state['dependencies'][:15]}
이번 주: 진화 성공 {success}, 실패 {failed}, 교훈 {lessons_count}개

1. 내 코드에서 병목이 될 곳은?
2. 없는 의존성 중 있으면 좋을 것은?
3. 다음 주 자기 개선 우선순위 3가지

JSON:
{{
    "bottlenecks": ["..."],
    "missing_deps": [{{"name": "...", "benefit": "..."}}],
    "evolution_rate": "{success}/{success+failed}",
    "next_improvements": [{{"name": "...", "description": "...", "priority": 1}}]
}}
JSON만 반환.
""",
        role="reasoning"
    )

    # JSON 파싱
    text = assessment.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]

    try:
        result = json.loads(text.strip())
    except:
        result = {"raw": assessment[:500]}

    # 우선순위 높은 개선점 -> 자기 진화 시도
    for imp in result.get("next_improvements", []):
        if imp.get("priority", 5) <= 2:
            try:
                eval_result = await evolver.evaluate({
                    "name": imp["name"],
                    "description": imp.get("description", ""),
                    "source": "self_assessment"
                })
                if eval_result.get("should_apply") and eval_result.get("risk_level") != "high":
                    await evolver.evolve(
                        {"name": imp["name"], "description": imp.get("description", "")},
                        eval_result
                    )
            except Exception as e:
                logger.warning(f"Self-evolution from assessment failed: {e}")

    # 메타학습 트리거
    await learner.meta_learn()

    state.ssot.save_signal("self_assessment", json.dumps({
        "evolutions": {"success": success, "failed": failed},
        "lessons": lessons_count,
        "assessment": result
    }))

    logger.info("=== Self Assessment Complete ===")


async def cost_review_job():
    """매월 1일 09시: 비용 분석."""
    logger.info("=== Cost Review Start ===")

    db = state.ssot._get_db()

    month_evolutions = db.execute(
        "SELECT COUNT(*) FROM evolutions WHERE created_at > datetime('now', '-30 days')"
    ).fetchone()[0]

    month_blogs = db.execute(
        "SELECT COUNT(*) FROM signals WHERE kind='blog_published' AND created_at > datetime('now', '-30 days')"
    ).fetchone()[0]

    month_discoveries = db.execute(
        "SELECT COUNT(*) FROM discoveries WHERE created_at > datetime('now', '-30 days')"
    ).fetchone()[0]

    analysis = await _call_llm_for_learning(
        f"""REZE 월간 비용 분석.
진화: {month_evolutions}회, 블로그: {month_blogs}개, 발견: {month_discoveries}건
API: Groq(무료), Gemini(무료), Cerebras(무료), Tavily(무료 1000/월)
서버: Contabo VPS(고정)
비용 최적화 제안. JSON: {{"estimated_cost": "$X", "optimizations": ["제안"]}}
JSON만 반환.""",
        role="reasoning"
    )

    state.ssot.save_signal("cost_review", json.dumps({"analysis": analysis}))

    msg = f"**월간 비용**\n진화:{month_evolutions} | 블로그:{month_blogs} | 발견:{month_discoveries}\n{analysis[:500]}"
    try:
        async with aiohttp.ClientSession() as session:
            await session.post(config.DISCORD_WEBHOOK_DAILY, json={"content": msg[:1900]})
    except Exception as e:
        logger.warning(f"Cost review Discord notification failed: {e}")

    logger.info("=== Cost Review Complete ===")


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

    # Phase 2: Research & Strategy Jobs
    state.scheduler.add_job(
        trend_scan_job, "cron", hour=8, minute=0, id="trend_scan"
    )  # 매일 08:00
    state.scheduler.add_job(
        competitor_check_job, "cron", day_of_week="mon", hour=9, minute=0, id="competitor_check"
    )  # 월요일 09:00
    state.scheduler.add_job(
        keyword_scan_job, "cron", day_of_week="wed", hour=9, minute=0, id="keyword_scan"
    )  # 수요일 09:00
    state.scheduler.add_job(
        strategic_thinking_job, "cron", day_of_week="sun", hour=20, minute=0, id="strategic_thinking"
    )  # 일요일 20:00
    state.scheduler.add_job(
        weekly_report_job, "cron", day_of_week="sun", hour=21, minute=0, id="weekly_report"
    )  # 일요일 21:00
    state.scheduler.add_job(
        security_scan_job, "cron", day_of_week="sat", hour=3, minute=0, id="security_scan"
    )  # 토요일 03:00

    # Phase 3: Self-Evolution & Learning Jobs
    state.scheduler.add_job(
        self_assessment_job, "cron", day_of_week="fri", hour=15, minute=0, id="self_assessment"
    )  # 금요일 15:00
    state.scheduler.add_job(
        cost_review_job, "cron", day=1, hour=9, minute=0, id="cost_review"
    )  # 매월 1일 09:00

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
