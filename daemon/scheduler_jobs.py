"""REZE Daemon Scheduler Jobs - 42개 스케줄 Job 함수들."""
import asyncio
import json
import logging
import subprocess
import yaml
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import aiohttp

import config
from daemon.state import (
    state, SAAS_HEALTH_ENDPOINTS,
    _call_llm_for_learning, _discord_notify_fn, _tavily_search_fn
)

logger = logging.getLogger("REZE.daemon")


# ============================================================
# Job 전용 헬퍼 함수들
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

    # Phase 3: 가속 검증 스케줄링
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
        for action in actions[:2]:
            task_spec = f"[{discovery_type}] {action}: {detail.get('summary', str(detail)[:100])}"
            task_id = state.ssot.enqueue(task_spec, priority=1, source="discovery")
            logger.info(f"Critical discovery → task: {task_id}")

    elif urgency == "high":
        task_spec = f"[{discovery_type}] 분석 및 대응: {detail.get('summary', str(detail)[:100])}"
        task_id = state.ssot.enqueue(task_spec, priority=2, source="discovery")
        logger.info(f"High urgency discovery → task: {task_id}")

    elif urgency == "medium":
        task_spec = f"[{discovery_type}] 검토: {detail.get('summary', str(detail)[:100])}"
        task_id = state.ssot.enqueue(task_spec, priority=3, source="discovery")

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


async def assess_task_complexity(task_spec: str, llm_fn) -> str:
    """LLM이 복잡도 판단. 키워드 매칭 아님."""
    try:
        response = await llm_fn(
            f"""태스크 복잡도를 판단. "simple" 또는 "complex" 한 단어만 출력.
simple = 명령어 1-2개로 끝남 (재시작, 상태확인, 로그보기)
complex = 여러 단계 필요 (분석, 구현, 다단계 작업)

태스크: {task_spec}

출력:""",
            role="judgment"
        )
        text = response.strip().lower() if isinstance(response, str) else str(response).strip().lower()
        return "complex" if "complex" in text else "simple"
    except:
        return "complex" if len(task_spec) > 80 else "simple"


# ============================================================
# Health & Judgment Jobs
# ============================================================

async def health_check_job():
    """매시간: 서버 상태 체크 → 이상 있으면 신호 저장."""
    logger.info("Running health check")
    try:
        if not state.tools:
            logger.warning("Tools not initialized, skipping health check")
            return

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
                if state.self_healing:
                    for svc in down_services:
                        try:
                            await state.self_healing.handle(svc)
                        except Exception as e:
                            logger.error(f"Self-heal error for {svc}: {e}")
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
        # Phase 3: 가속 검증
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

        signals = state.ssot.get_recent_signals(hours=6)
        if not signals:
            logger.info("No signals to judge")
            return

        signals_text = "\n".join(
            f"[{s['kind']}] {s['data'][:200]}" for s in signals[:20]
        )

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

        text = response.text.strip()
        text = text.replace("```json", "").replace("```", "").strip()

        try:
            tasks = json.loads(text)
        except json.JSONDecodeError:
            logger.warning(f"Judgment parse failed: {text[:100]}")
            return

        if not isinstance(tasks, list) or not tasks:
            logger.info("Judgment: no action needed")
            return

        for t in tasks[:3]:
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
# v3.3 Jobs - Skill Health & Daily Report
# ============================================================

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
        signals_today = state.ssot.get_signals_by_date(today)

        blog_published = [s for s in signals_today if s["kind"] == "blog_published"]
        blog_held = [s for s in signals_today if s["kind"] == "blog_held"]
        auto_fixes = [s for s in signals_today if s["kind"] == "auto_fix_success"]
        health_fails = [s for s in signals_today if s["kind"] == "health_fail"]
        evolutions = [s for s in signals_today if s["kind"] == "self_evolution_success"]
        approvals = [s for s in signals_today if s["kind"] == "approval_request"]

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

        saas_signals = [s for s in signals_today if s["kind"] == "saas_subscription_check"]
        gumroad_signals = [s for s in signals_today if s["kind"] == "gumroad_sales_check"]

        if saas_signals or gumroad_signals:
            report += "\n수익\n"
            for s in saas_signals:
                try:
                    p = json.loads(s.get("data", "{}"))
                    report += f"  SaaS: {p.get('active', 0)} active, MRR ${p.get('mrr_usd', 0):.2f}\n"
                except:
                    pass
            for s in gumroad_signals:
                try:
                    p = json.loads(s.get("data", "{}"))
                    report += f"  Gumroad: {p.get('total_sales', 0)}건, ${p.get('total_usd', 0):.2f} (30d)\n"
                except:
                    pass

        async with aiohttp.ClientSession() as session:
            await session.post(
                config.DISCORD_WEBHOOK_DAILY,
                json={"content": report[:2000]}
            )

        state.ssot.save_signal("daily_report", json.dumps({"date": today}))
        logger.info("Daily report sent")

    except Exception as e:
        logger.error(f"Daily report failed: {e}")


# ============================================================
# Phase 2: Discovery Pipeline & Research Jobs
# ============================================================

async def trend_scan_job():
    """매일 08:00: AI/노코드 트렌드 스캔."""
    logger.info("Running trend scan")

    try:
        sources = [
            {"name": "Product Hunt", "url": "https://www.producthunt.com/topics/artificial-intelligence"},
            {"name": "Hacker News", "url": "https://news.ycombinator.com/"},
            {"name": "AI Tools Directory", "url": "https://www.futuretools.io/"},
        ]

        discoveries = []

        for source in sources:
            try:
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

        for d in discoveries:
            disc_type = d.get("type", "new_tool_discovered")
            await process_discovery(disc_type, "trend_scan", d)

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

        # Phase 4: 추가 소스에서 수집
        extra_count = 0
        try:
            from input_sources import collect_all_sources, classify_discovery
            extra_discoveries = await collect_all_sources()

            for item in extra_discoveries:
                disc_type = classify_discovery(item)
                discovery = {
                    "type": disc_type,
                    "tool_name": item.get("title", ""),
                    "summary": item.get("description", item.get("url", "")),
                    "source": item.get("source", "external"),
                    "url": item.get("url", ""),
                }
                await process_discovery(disc_type, f"trend_scan_{item.get('source', 'external')}", discovery)

                if disc_type == "self_improvement_tech" and discovery.get("tool_name"):
                    try:
                        from self_evolution import SelfEvolution
                        evolver = SelfEvolution(
                            _call_llm_for_learning,
                            state.ssot.save_signal,
                            state.ssot._get_db
                        )
                        tech_info = {
                            "name": discovery["tool_name"][:50],
                            "description": discovery.get("summary", "")[:200],
                            "source": f"trend_scan_{item.get('source', 'external')}"
                        }
                        evo_result = await evolver.evaluate_and_evolve(tech_info)
                        if evo_result.get("success"):
                            logger.info(f"Auto-evolution from external: {tech_info['name']}")
                    except Exception as e:
                        logger.warning(f"Self-evolution from external source failed: {e}")

                extra_count += 1
        except Exception as e:
            logger.warning(f"External source collection failed: {e}")

        state.ssot.save_signal("trend_scan_complete", json.dumps({
            "discoveries": len(discoveries),
            "external_discoveries": extra_count,
            "sources_checked": len(sources)
        }))

        logger.info(f"Trend scan complete: {len(discoveries)} LLM + {extra_count} external")

    except Exception as e:
        logger.error(f"Trend scan failed: {e}")


async def competitor_check_job():
    """매주 월요일 09:00: 경쟁사 모니터링."""
    logger.info("Running competitor check")

    try:
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


async def discovery_scan_job():
    """30분마다: 서버 변화 감지 (v5.0 SOVEREIGN)."""
    try:
        if not state.discovery:
            return
        discoveries = await state.discovery.full_scan()
        if discoveries:
            logger.info(f"Discovery: {len(discoveries)} changes")
            state.ssot.save_signal("discovery",
                json.dumps([d.get("name", "?") for d in discoveries]))
    except Exception as e:
        logger.error(f"Discovery scan error: {e}")


async def keyword_scan_job():
    """매주 수요일 09:00: 키워드 기회 발굴."""
    logger.info("Running keyword scan")

    try:
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
        today = datetime.now(config.KST)
        week_start = (today - timedelta(days=7)).strftime("%Y-%m-%d")

        signals = state.ssot.get_recent_signals(hours=168)

        discoveries = [s for s in signals if s["kind"].startswith("discovery")]
        blog_published = [s for s in signals if s["kind"] == "blog_published"]
        auto_fixes = [s for s in signals if s["kind"] == "auto_fix_success"]
        health_fails = [s for s in signals if s["kind"] == "health_fail"]

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

            for p in strategy.get("next_week_priorities", [])[:3]:
                for action in p.get("actions", [])[:2]:
                    task_id = state.ssot.enqueue(
                        f"[전략] {action}",
                        priority=p.get("rank", 3),
                        source="strategy"
                    )
                    logger.info(f"Strategy task created: {task_id}")

            for lesson in strategy.get("lessons", []):
                state.ssot.save_signal("lesson_learned", lesson)

            state.ssot.save_signal("weekly_strategy", json.dumps(strategy))

            # Phase 4: 시장 진입 제안
            try:
                from blog_spinup import BlogSpinup
                spinup = BlogSpinup(_call_llm_for_learning, state.ssot.save_signal)

                db = state.ssot._get_db()
                popular_niches = db.execute(
                    """SELECT discovery_type, COUNT(*) as cnt
                       FROM discoveries
                       WHERE created_at > datetime('now', '-7 days')
                       GROUP BY discovery_type
                       ORDER BY cnt DESC LIMIT 5"""
                ).fetchall()

                current_blogs = 2
                target_blogs = 10

                if current_blogs < target_blogs and popular_niches:
                    top_niche = popular_niches[0][0] if popular_niches else ""

                    proposal = await spinup.propose_new_blog(niche=top_niche)

                    if proposal.get("competition_level") != "high" and "raw" not in proposal:
                        from discord_interactive import request_boss_approval
                        await request_boss_approval(
                            action=f"새 블로그: {proposal.get('brand_name', 'unknown')}",
                            reason=f"니치: {proposal.get('niche')}, 예상 6개월 수익: {proposal.get('estimated_monthly_revenue_6m', '?')}",
                            analysis=json.dumps(proposal, ensure_ascii=False)[:500]
                        )
            except Exception as e:
                logger.warning(f"Blog spinup proposal failed: {e}")

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

        signals = state.ssot.get_recent_signals(hours=168)

        blog_published = len([s for s in signals if s["kind"] == "blog_published"])
        discoveries = len([s for s in signals if s["kind"].startswith("discovery")])
        auto_fixes = len([s for s in signals if s["kind"] == "auto_fix_success"])
        tasks_completed = len(state.ssot.get_recent_tasks(limit=100))

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

보스님, 이번 주도 열심히 일했습니다!
"""

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

        sensitive_patterns = [".env", "credentials", "secret", "private_key"]
        for pattern in sensitive_patterns:
            try:
                result = subprocess.run(
                    ["find", str(Path.home() / "reze-agent"), "-name", f"*{pattern}*", "-type", "f"],
                    capture_output=True, text=True, timeout=30
                )
                files = [f for f in result.stdout.strip().split("\n") if f and not "node_modules" in f]
                for f in files:
                    if f.endswith(".env"):
                        continue
                    findings.append({
                        "type": "sensitive_file",
                        "path": f
                    })
            except Exception:
                pass

        if findings:
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
# Phase 3: Self-Evolution & Learning Jobs
# ============================================================

async def self_assessment_job():
    """매주 금 15시: REZE 자기 평가."""
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

    evolutions = db.execute(
        """SELECT tech_name, status, performance_before, performance_after
           FROM evolutions WHERE created_at > datetime('now', '-7 days')"""
    ).fetchall()

    success = sum(1 for e in evolutions if e[1] == 'success')
    failed = sum(1 for e in evolutions if e[1] == 'failed')

    lessons_count = db.execute(
        "SELECT COUNT(*) FROM signals WHERE kind='lesson_learned' AND created_at > datetime('now', '-7 days')"
    ).fetchone()[0]

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

    text = assessment.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]

    try:
        result = json.loads(text.strip())
    except:
        result = {"raw": assessment[:500]}

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

    await learner.meta_learn()

    try:
        from autonomy_adjuster import AutonomyAdjuster
        adjuster = AutonomyAdjuster(state.ssot._get_db, state.ssot.save_signal)
        autonomy_result = await adjuster.evaluate_autonomy()

        from discord_interactive import request_boss_approval
        for proposal in autonomy_result.get("proposals", []):
            if proposal.get("requires_approval"):
                await request_boss_approval(
                    action=proposal["action"],
                    reason=proposal["reason"],
                    analysis=f"Risk: {proposal['risk']}"
                )
            elif proposal.get("auto_action") == "pause_evolution":
                state.ssot.save_signal("evolution_paused", json.dumps({
                    "reason": proposal["reason"],
                    "auto": True,
                }))
                logger.warning(f"Evolution auto-paused: {proposal['reason']}")

        meta_signals = db.execute(
            """SELECT data FROM signals
               WHERE kind='meta_learning'
               ORDER BY created_at DESC LIMIT 1"""
        ).fetchone()

        if meta_signals:
            try:
                meta = json.loads(meta_signals[0])
                principles = meta.get("principles", [])
                if principles:
                    db.execute(
                        """INSERT OR REPLACE INTO plan_cache (key, value, updated_at)
                           VALUES ('meta_principles', ?, datetime('now'))""",
                        (json.dumps(principles, ensure_ascii=False),)
                    )
                    db.commit()
                    logger.info(f"Meta principles applied to plan_cache: {len(principles)}")
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"Autonomy evaluation failed: {e}")

    state.ssot.save_signal("self_assessment", json.dumps({
        "evolutions": {"success": success, "failed": failed},
        "lessons": lessons_count,
        "assessment": result
    }))

    logger.info("=== Self Assessment Complete ===")


async def cost_review_job():
    """매월 1일 09시: 비용 + 수익 분석."""
    logger.info("=== Monthly Review Start ===")

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

    revenue_report = None
    try:
        from revenue_tracker import RevenueTracker
        tracker = RevenueTracker(
            state.ssot._get_db,
            state.ssot.save_signal,
            _call_llm_for_learning
        )
        revenue_report = await tracker.monthly_report()
    except Exception as e:
        logger.warning(f"Revenue tracking failed: {e}")

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

    strategy = revenue_report.get("strategy", {}) if revenue_report else {}
    priorities = strategy.get("next_month_priorities", ["N/A"])

    msg = f"""**REZE 월간 리뷰**

**실적:**
블로그: {month_blogs}개
발견: {month_discoveries}건
진화: {month_evolutions}회

**전략:**
다음 달 우선순위: {', '.join(priorities[:3])}
새 블로그 추가: {'권장' if strategy.get('should_add_blog') else '아직'}

{analysis[:300]}"""

    try:
        async with aiohttp.ClientSession() as session:
            await session.post(config.DISCORD_WEBHOOK_DAILY, json={"content": msg[:1900]})
    except Exception as e:
        logger.warning(f"Monthly review Discord notification failed: {e}")

    logger.info("=== Monthly Review Complete ===")


# ============================================================
# v5.0 Phase 3-4 Jobs
# ============================================================

async def feedback_processor_job():
    """피드백 큐에서 due된 체크 실행."""
    try:
        if not state.feedback:
            return
        results = await state.feedback.process_due()
        if results:
            logger.info(f"Feedback: {len(results)} checks processed")
    except Exception as e:
        logger.error(f"Feedback processor error: {e}")


async def daemon_task_processor_job():
    """daemon_tasks에서 pending 태스크를 WorkerPool로 실행."""
    try:
        pending = []
        for _ in range(3):
            task = state.ssot.pop_next_pending()
            if task:
                pending.append(task)
            else:
                break

        if not pending:
            return

        for task in pending:
            tid = task["id"]
            spec = task.get("task_spec", "")
            src = task.get("source", "schedule")

            async def _run(task_id=tid, task_spec=spec, source=src):
                try:
                    complexity = await assess_task_complexity(
                        task_spec, _call_llm_for_learning
                    )

                    if complexity == "complex" and state.planner:
                        plan = await state.planner.plan(task_spec)
                        result = await state.plan_executor.execute(
                            plan, task_id=task_id, source=source
                        )
                    else:
                        result = await state.core.run(task_spec, source=source)

                    ok = result.get("status") in ("success", "completed")
                    state.ssot.complete_daemon_task(
                        task_id,
                        "success" if ok else "failed",
                        json.dumps(result, ensure_ascii=False, default=str)[:2000]
                    )

                    if state.feedback:
                        state.feedback.register(
                            task_id=task_id,
                            task_type=result.get("task_type", "other"),
                            result=result,
                            metadata={
                                "task_spec": task_spec,
                                "source": source,
                                "complexity": complexity
                            }
                        )

                except Exception as e:
                    state.ssot.complete_daemon_task(task_id, "failed", str(e)[:500])
                    logger.error(f"Task {task_id} failed: {e}")

            await state.worker_pool.submit(tid, spec[:50], _run())

    except Exception as e:
        logger.error(f"Daemon task processor error: {e}")


async def config_tuner_job():
    """주 1회 실행: config 값 자동 조정 사이클."""
    try:
        if not state.config_tuner:
            return
        result = await state.config_tuner.run_cycle()
        logger.info(f"ConfigTuner result: {result}")

        if result.get("pending_approval"):
            pending = state.ssot.get_pending_config_changes()
            for p in pending:
                logger.warning(
                    f"CONFIG APPROVAL NEEDED: #{p['id']} "
                    f"{p['key']} {p['old']}->{p['new']} [{p['risk']}] "
                    f"Reason: {p['reason']}"
                )
    except Exception as e:
        logger.error(f"ConfigTuner job failed: {e}")


async def memory_cleanup_job():
    """월 1회: 안 쓰이는 메모리 정리."""
    try:
        if not state.plan_memory:
            return
        cleaned = state.plan_memory.cleanup_stale(unused_days=30)
        stats = state.ssot.get_memory_stats()
        logger.info(f"Memory cleanup: removed {cleaned}, stats: {stats}")
    except Exception as e:
        logger.error(f"Memory cleanup failed: {e}")


async def stale_task_detector_job():
    """매 10분: 좀비 태스크 감지 및 정리 (running > 1시간)."""
    try:
        cursor = state.ssot.conn.execute("""
            UPDATE tasks SET status='incomplete',
              final_answer='zombie: auto-marked after 1h stale'
            WHERE status='running'
            AND datetime(created_at) < datetime('now', '-1 hour')
        """)
        tasks_cleaned = cursor.rowcount

        cursor = state.ssot.conn.execute("""
            UPDATE daemon_tasks SET status='failed',
              result='zombie: auto-marked after 1h stale'
            WHERE status='running'
            AND datetime(started_at) < datetime('now', '-1 hour')
        """)
        daemon_cleaned = cursor.rowcount

        state.ssot.conn.commit()

        if tasks_cleaned or daemon_cleaned:
            logger.warning(f"[ZOMBIE] Cleaned: tasks={tasks_cleaned}, daemon_tasks={daemon_cleaned}")
        else:
            logger.debug("[ZOMBIE] No stale tasks found")
    except Exception as e:
        logger.error(f"Stale task detector failed: {e}")


# ============================================================
# Phase 4 Part D+E Jobs
# ============================================================

async def saas_daily_check_job():
    """매일 07:30: LemonSqueezy SaaS 전체 체크."""
    try:
        if state.saas_monitor:
            await state.saas_monitor.daily_check()
    except Exception as e:
        logger.error(f"SaaS daily check failed: {e}")


async def gumroad_daily_check_job():
    """매일 07:45: Gumroad 판매 체크."""
    try:
        from gumroad_manager import get_gumroad
        gumroad = get_gumroad()
        if gumroad:
            await gumroad.daily_check()
    except Exception as e:
        logger.error(f"Gumroad daily check failed: {e}")


async def landing_weekly_review_job():
    """월요일 10:00: 랜딩페이지 전환율 주간 리뷰."""
    try:
        if state.landing_optimizer:
            review = await state.landing_optimizer.weekly_review()

            for product_key in config.SAAS_PRODUCTS:
                try:
                    await state.landing_optimizer.generate_variants(product_key)
                except Exception as e:
                    logger.warning(f"Variant generation failed for {product_key}: {e}")
    except Exception as e:
        logger.error(f"Landing weekly review failed: {e}")


async def launch_check_job():
    """매일 08:30: 런치 일정 체크 → 알림."""
    try:
        if state.launch_sequence:
            await state.launch_sequence.check_due_launches()
    except Exception as e:
        logger.error(f"Launch check failed: {e}")


async def feature_monthly_report_job():
    """매월 1일 10:00: 피드백 월간 리포트."""
    try:
        from feature_prioritizer import get_prioritizer
        prioritizer = get_prioritizer()
        if prioritizer:
            await prioritizer.monthly_report()
    except Exception as e:
        logger.error(f"Feature monthly report failed: {e}")


async def saas_monthly_report_job():
    """매월 1일 10:30: SaaS 월간 리포트."""
    try:
        if state.saas_monitor:
            report = await state.saas_monitor.monthly_report()

            if state.alert_manager and report.get("strategy"):
                strategy = report["strategy"]
                msg = (
                    f"**SaaS 월간 리포트**\n"
                    f"건강한 제품: {strategy.get('healthiest_product', 'N/A')}\n"
                    f"위험 제품: {strategy.get('at_risk_product', 'N/A')}\n"
                    f"전략: {', '.join(strategy.get('growth_strategies', [])[:3])}"
                )
                try:
                    await state.alert_manager.send("info", "saas_monthly", msg[:1900])
                except Exception:
                    pass
    except Exception as e:
        logger.error(f"SaaS monthly report failed: {e}")


# ============================================================
# v4.0 신규 Jobs
# ============================================================

async def auto_discovery_job():
    """매시간: 서버에 새로 등장한 서비스를 감지하고 자동 등록."""
    logger.info("Running auto-discovery")
    try:
        known = state.ssot.get_known_services()
        new_services = []

        try:
            pm2_result = subprocess.run(
                ["pm2", "jlist"], capture_output=True, text=True, timeout=30
            )
            if pm2_result.returncode == 0:
                pm2_list = json.loads(pm2_result.stdout)
                for proc in pm2_list:
                    name = proc.get('name', '')
                    status = proc.get('pm2_env', {}).get('status', '')
                    if name and name not in known and status == 'online':
                        new_services.append({
                            'name': name,
                            'type_hint': 'pm2',
                            'port': proc.get('pm2_env', {}).get('PORT'),
                            'cwd': proc.get('pm2_env', {}).get('pm_cwd', '')
                        })
        except Exception as e:
            logger.warning(f"PM2 scan failed: {e}")

        try:
            docker_result = subprocess.run(
                ["docker", "ps", "--format", "{{.Names}}\t{{.Ports}}\t{{.Image}}"],
                capture_output=True, text=True, timeout=30
            )
            if docker_result.returncode == 0:
                for line in docker_result.stdout.strip().split('\n'):
                    if not line.strip():
                        continue
                    parts = line.split('\t')
                    name = parts[0]
                    if name and name not in known:
                        new_services.append({
                            'name': name,
                            'type_hint': 'docker',
                            'port': parts[1] if len(parts) > 1 else None,
                            'image': parts[2] if len(parts) > 2 else None
                        })
        except Exception as e:
            logger.warning(f"Docker scan failed: {e}")

        for svc in new_services[:5]:
            try:
                classification = await state.router.call(
                    "classification",
                    [{"role": "user", "content": f"""서버에서 새 서비스 감지:
이름: {svc['name']}
타입: {svc['type_hint']}
포트: {svc.get('port')}

유형 하나만 답: blog / saas / api / tool / infra / unknown"""}]
                )
                svc_type = classification.text.strip().lower()
                if svc_type not in ['blog', 'saas', 'api', 'tool', 'infra']:
                    svc_type = 'unknown'

                state.ssot.register_service(
                    name=svc['name'],
                    type_=svc_type,
                    port=svc.get('port'),
                    meta=svc
                )

                if state.alert_manager:
                    await state.alert_manager.send(
                        "info", "auto_discovery",
                        f"새 서비스 감지: **{svc['name']}** ({svc_type})"
                    )
                logger.info(f"Auto-discovered service: {svc['name']} ({svc_type})")
            except Exception as e:
                logger.warning(f"Service registration failed: {e}")

        if new_services:
            logger.info(f"Auto-discovery: found {len(new_services)} new services")
    except Exception as e:
        logger.error(f"Auto-discovery failed: {e}")


async def self_improvement_research_job():
    """매주 월요일 03:00: 약한 영역 파악 + 인터넷 리서치."""
    logger.info("Running self-improvement research")
    try:
        db = state.ssot._get_db()
        low_scores = db.execute("""
            SELECT task_pattern, AVG(score) as avg_score
            FROM plan_cache_v4
            WHERE created_at > datetime('now', '-7 days')
            GROUP BY task_pattern
            HAVING avg_score < 0.8
            ORDER BY avg_score ASC
            LIMIT 3
        """).fetchall()

        repeated_failures = db.execute("""
            SELECT task_pattern, COUNT(*) as fail_count
            FROM reflections_v4
            WHERE created_at > datetime('now', '-7 days')
            GROUP BY task_pattern
            HAVING fail_count >= 2
            LIMIT 3
        """).fetchall()

        weak_areas = [r[0] for r in low_scores] + [r[0] for r in repeated_failures]

        if not weak_areas:
            if state.alert_manager:
                await state.alert_manager.send(
                    "info", "research", "주간 리서치: 약한 영역 없음. 모든 영역 양호."
                )
            return

        insights_count = 0
        for area in weak_areas[:3]:
            try:
                summary = await state.router.call(
                    "research",
                    [{"role": "user", "content": f"""다음 영역에서 개선할 수 있는 best practice 3가지를 제안:
영역: {area}

실행 가능한 구체적 인사이트만 간결하게."""}]
                )

                db.execute("""
                    INSERT INTO research_insights (area, insight, applicability_score)
                    VALUES (?, ?, 0.7)
                """, [area, summary.text[:500]])
                insights_count += 1
            except Exception as e:
                logger.warning(f"Research failed for {area}: {e}")

        db.commit()

        if state.alert_manager:
            await state.alert_manager.send(
                "info", "research",
                f"주간 리서치 완료: {len(weak_areas)}개 약한 영역 분석, {insights_count}개 인사이트 수집"
            )
    except Exception as e:
        logger.error(f"Self-improvement research failed: {e}")


async def competitor_research_job():
    """수/토 06:00: 블로그 경쟁사 콘텐츠 분석."""
    logger.info("Running competitor research")
    try:
        blog_skill = state.skills.catalog.get('blog-engine')
        if not blog_skill:
            return

        for config_name, blog_config in blog_skill.get('configs', {}).items():
            if not blog_config:
                continue
            competitors = blog_config.get('seo', {}).get('competitor_sites', [])[:2]
            if not competitors:
                continue

            for comp_url in competitors:
                try:
                    gap = await state.router.call(
                        "research",
                        [{"role": "user", "content": f"""경쟁사 {comp_url}의 최근 콘텐츠 주제를 분석하고,
블로그 '{blog_config.get('name')}'에 없는 주제를 3개 제안.

간결하게 주제명 + 검색 의도만."""}]
                    )

                    if state.alert_manager:
                        await state.alert_manager.send(
                            "info", "competitor_research",
                            f"경쟁사 분석 [{config_name}]\n경쟁사: {comp_url}\n콘텐츠 갭:\n{gap.text[:400]}"
                        )
                except Exception as e:
                    logger.warning(f"Competitor research failed for {comp_url}: {e}")
    except Exception as e:
        logger.error(f"Competitor research failed: {e}")


async def weekly_skill_evolution_job():
    """매주 일요일 04:00: 스킬 프롬프트 자기 최적화."""
    logger.info("Running weekly skill evolution")
    try:
        from self_evolution import SelfEvolution
        se = SelfEvolution(
            _call_llm_for_learning,
            state.ssot.save_signal,
            state.ssot._get_db
        )

        results = []
        for skill_name in list(state.skills.catalog.keys())[:3]:
            try:
                if hasattr(se, 'evolve_skill_prompt'):
                    result = await se.evolve_skill_prompt(skill_name)
                    results.append(f"{skill_name}: {result}")
            except Exception as e:
                results.append(f"{skill_name}: error - {str(e)[:50]}")

        if state.alert_manager and results:
            await state.alert_manager.send(
                "info", "skill_evolution",
                f"주간 스킬 진화:\n" + "\n".join(results[:5])
            )
    except Exception as e:
        logger.error(f"Weekly skill evolution failed: {e}")


async def weekly_goal_review_job():
    """매주 월요일 09:00: 목표 진행 리뷰."""
    logger.info("Running weekly goal review")
    try:
        db = state.ssot._get_db()
        active_goals = db.execute("""
            SELECT id, goal, progress_pct FROM goal_tree
            WHERE status = 'active'
        """).fetchall()

        if not active_goals:
            if state.alert_manager:
                await state.alert_manager.send(
                    "info", "goal_review", "주간 목표 리뷰: 활성 목표 없음"
                )
            return

        report_parts = []
        for goal_id, goal_text, progress in active_goals:
            tasks = db.execute("""
                SELECT task_name, status FROM goal_tasks WHERE goal_id = ?
            """, [goal_id]).fetchall()

            completed = sum(1 for t in tasks if t[1] == 'completed')
            total = len(tasks)

            report_parts.append(
                f"**{goal_text[:50]}** ({completed}/{total} 완료)"
            )

        if state.alert_manager:
            await state.alert_manager.send(
                "info", "goal_review",
                f"주간 목표 리뷰\n" + "\n".join(report_parts[:5])
            )
    except Exception as e:
        logger.error(f"Weekly goal review failed: {e}")


# ============================================================
# v4.0 ULTIMATE Jobs
# ============================================================

async def autonomous_loop_job():
    """6시간마다: 자율 운영 루프 실행 (SENSE->SEARCH->THINK->ACT->VERIFY->LEARN)."""
    logger.info("=== Running Autonomous Loop ===")
    try:
        if state.autonomous_loop:
            cycle_results = await state.autonomous_loop.run_cycle()
            targets_processed = len(cycle_results) if isinstance(cycle_results, list) else 0
            actions_taken = sum(1 for r in (cycle_results or [])
                              if isinstance(r, dict) and r.get('status') == 'success')
            logger.info(f"Autonomous loop completed: {targets_processed} targets processed")

            if state.alert_manager and targets_processed > 0:
                await state.alert_manager.send(
                    "info", "autonomous_loop",
                    f"자율 루프 완료: {targets_processed}개 서비스 처리, "
                    f"액션 {actions_taken}개 실행"
                )
    except Exception as e:
        logger.error(f"Autonomous loop failed: {e}")


async def agent_supervisor_scan_job():
    """30분마다: Docker/n8n/PM2/cron/Dify 에이전트 감시."""
    logger.info("Running agent supervisor scan")
    try:
        if state.agent_supervisor:
            issues = await state.agent_supervisor.scan_all_agents()

            unhealthy = [i.get("agent", {}) for i in issues if isinstance(i, dict)]
            if unhealthy:
                for agent in unhealthy[:3]:
                    try:
                        recovery = await state.agent_supervisor.recover_agent(agent["name"])
                        if recovery.get("success"):
                            logger.info(f"Agent recovered: {agent['name']}")
                        else:
                            logger.warning(f"Agent recovery failed: {agent['name']}")
                    except Exception as e:
                        logger.error(f"Agent recovery error: {agent['name']} - {e}")

                if state.alert_manager:
                    await state.alert_manager.send(
                        "warning", "agent_supervisor",
                        f"에이전트 이상 감지: {', '.join(a['name'] for a in unhealthy[:5])}"
                    )
    except Exception as e:
        logger.error(f"Agent supervisor scan failed: {e}")


async def agent_discovery_job():
    """12시간마다: 새 에이전트 자동 발견 및 등록."""
    logger.info("Running agent discovery")
    try:
        if state.agent_supervisor:
            discovered = await state.agent_supervisor.auto_discover_agents()

            if discovered:
                logger.info(f"Discovered {len(discovered)} new agents")
                if state.alert_manager:
                    await state.alert_manager.send(
                        "info", "agent_discovery",
                        f"새 에이전트 발견: {', '.join(a['name'] for a in discovered[:5])}"
                    )
    except Exception as e:
        logger.error(f"Agent discovery failed: {e}")


async def goal_progress_job():
    """매일 21:00: 목표 진행 상황 체크 및 리포트."""
    logger.info("Running goal progress check")
    try:
        if state.goal_bridge:
            progress_results = await state.goal_bridge.progress_check()

            if isinstance(progress_results, list) and progress_results:
                report_lines = ["일일 목표 진행 현황"]
                for goal in progress_results[:5]:
                    report_lines.append(
                        f"  {goal['goal'][:40]}: {goal['progress']:.0f}% "
                        f"({goal['tasks_done']}/{goal['tasks_total']} 완료)"
                    )

                if state.alert_manager:
                    await state.alert_manager.send(
                        "info", "goal_progress",
                        "\n".join(report_lines)
                    )
    except Exception as e:
        logger.error(f"Goal progress check failed: {e}")


async def portfolio_dashboard_job():
    """매일 09:00: 포트폴리오 수익 대시보드 생성."""
    logger.info("Running portfolio dashboard")
    try:
        if state.growth_engine:
            dashboard = await state.growth_engine.portfolio_revenue_dashboard()
            logger.info(f"Portfolio dashboard: ${dashboard.get('total', 0):.0f} total revenue")
    except Exception as e:
        logger.error(f"Portfolio dashboard failed: {e}")


async def churn_detection_job():
    """매일 10:00: SaaS 이탈 감지."""
    logger.info("Running churn detection")
    try:
        if state.saas_ops:
            results = await state.saas_ops.churn_detection_all()

            at_risk_count = sum(len(v) for v in results.values() if v)
            if at_risk_count > 0:
                logger.warning(f"Churn detection: {at_risk_count} at-risk signals")
    except Exception as e:
        logger.error(f"Churn detection failed: {e}")


async def meta_review_job():
    """매주 일요일 22:00: 메타인지 리뷰 (강점/약점 분석)."""
    logger.info("=== Running Meta-Cognition Review ===")
    try:
        if state.meta_cognition:
            review = await state.meta_cognition.weekly_meta_review()
            logger.info(f"Meta review completed: overall health = {review.get('overall_health', 'unknown')}")
    except Exception as e:
        logger.error(f"Meta-cognition review failed: {e}")


async def prompt_evolution_job():
    """매주 일요일 23:00: 프롬프트 자기 최적화 (EvoPrompt + A/B 테스트)."""
    logger.info("=== Running Prompt Evolution ===")
    try:
        if state.prompt_evolver:
            result = await state.prompt_evolver.evolve_weekly()
            logger.info(
                f"Prompt evolution completed: {result.get('evolved', 0)} evolved, "
                f"{len(result.get('completed_tests', []))} A/B tests completed"
            )
    except Exception as e:
        logger.error(f"Prompt evolution failed: {e}")


async def saas_ops_daily_job():
    """매일 08:00: SaaS 5개 일일 운영 체크."""
    logger.info("Running SaaS operations daily check")
    try:
        if state.saas_ops:
            results = await state.saas_ops.run_daily_checks()
            logger.info(f"SaaS ops check completed: {len(results)} services checked")
    except Exception as e:
        logger.error(f"SaaS operations daily check failed: {e}")


async def gumroad_ops_daily_job():
    """매일 08:15: Gumroad 4개 일일 운영 체크."""
    logger.info("Running Gumroad operations daily check")
    try:
        if state.gumroad_ops:
            results = await state.gumroad_ops.run_daily_checks()
            logger.info(f"Gumroad ops check completed: {len(results)} products checked")
    except Exception as e:
        logger.error(f"Gumroad operations daily check failed: {e}")


async def cross_sell_analysis_job():
    """매주 수요일 11:00: 크로스셀 기회 분석."""
    logger.info("Running cross-sell analysis")
    try:
        if state.growth_engine:
            results = await state.growth_engine.cross_sell_opportunities()

            opportunities = results.get("opportunities", [])
            if opportunities and state.alert_manager:
                await state.alert_manager.send(
                    "info", "cross_sell",
                    f"크로스셀 기회 발견: {len(opportunities)}개\n" +
                    "\n".join(f"  {o['source']}: {o.get('suggestions', ['N/A'])[0]}" for o in opportunities[:3])
                )
    except Exception as e:
        logger.error(f"Cross-sell analysis failed: {e}")


async def dynamic_skill_verification_job():
    """매일 14:00: 동적 스킬 검증 (3회 연속 성공 -> verified)."""
    logger.info("Running dynamic skill verification")
    try:
        db = state.ssot._get_db()

        pending_skills = db.execute("""
            SELECT id, skill_name, test_count, success_count
            FROM dynamic_skills
            WHERE status = 'pending'
        """).fetchall()

        for skill in pending_skills:
            skill_id, name, test_count, success_count = skill

            if success_count >= 3:
                db.execute("""
                    UPDATE dynamic_skills SET status = 'verified', updated_at = datetime('now')
                    WHERE id = ?
                """, [skill_id])
                db.commit()

                if state.alert_manager:
                    await state.alert_manager.send(
                        "info", "skill_verified",
                        f"스킬 검증 완료: {name} (3/3 성공)"
                    )
                logger.info(f"Skill verified: {name}")

        logger.info(f"Dynamic skill verification: {len(pending_skills)} skills checked")
    except Exception as e:
        logger.error(f"Dynamic skill verification failed: {e}")


async def task_queue_processor_job():
    """10분마다: task_queue에서 pending 태스크 실행."""
    logger.info("Processing task queue")
    try:
        task = state.ssot.pop_next_task()
        if not task:
            return

        task_id = task["id"]
        task_type = task.get("task_type", "unknown")
        target_service = task.get("target_service", "")
        action = task.get("action", "")
        parameters = json.loads(task.get("parameters", "{}") or "{}")

        logger.info(f"Executing task {task_id}: {task_type}/{action} for {target_service}")

        try:
            if state.capability_engine:
                task_description = f"{action} for {target_service}"
                if parameters:
                    task_description += f" (params: {json.dumps(parameters, ensure_ascii=False)[:100]})"

                plan = await state.capability_engine.plan_capabilities(
                    task_description,
                    context={
                        "task_type": task_type,
                        "target": target_service,
                        "parameters": parameters
                    }
                )

                result = await state.capability_engine.execute_plan(
                    plan,
                    context={
                        "task_id": task_id,
                        "target": target_service,
                        "parameters": parameters
                    }
                )

                state.ssot.complete_task_queue_item(
                    task_id,
                    "done" if result.get("success") else "failed",
                    json.dumps(result, ensure_ascii=False)
                )
            else:
                state.ssot.complete_task_queue_item(task_id, "skipped", "No capability engine")

        except Exception as e:
            state.ssot.complete_task_queue_item(task_id, "failed", str(e))
            logger.error(f"Task {task_id} execution failed: {e}")

    except Exception as e:
        logger.error(f"Task queue processor failed: {e}")
