"""REZE Daemon Orchestrator - lifespan, WebhookNotifier, queue_worker."""
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import aiohttp
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI

import config
from config import (
    WORKER_MAX_CONCURRENT, FEEDBACK_CHECK_INTERVAL_HOURS,
    TASK_PROCESSOR_INTERVAL_MINUTES
)

from daemon.state import (
    state, _call_llm_for_learning, _discord_notify_fn, _tavily_search_fn
)

# Import all scheduler jobs
from daemon.scheduler_jobs import (
    health_check_job,
    judgment_job,
    self_review_job,
    skill_health_check_job,
    daily_report_job,
    trend_scan_job,
    competitor_check_job,
    discovery_scan_job,
    keyword_scan_job,
    strategic_thinking_job,
    weekly_report_job,
    security_scan_job,
    self_assessment_job,
    cost_review_job,
    feedback_processor_job,
    daemon_task_processor_job,
    config_tuner_job,
    memory_cleanup_job,
    stale_task_detector_job,
    saas_daily_check_job,
    gumroad_daily_check_job,
    landing_weekly_review_job,
    launch_check_job,
    feature_monthly_report_job,
    saas_monthly_report_job,
    auto_discovery_job,
    self_improvement_research_job,
    competitor_research_job,
    weekly_skill_evolution_job,
    weekly_goal_review_job,
    autonomous_loop_job,
    agent_supervisor_scan_job,
    agent_discovery_job,
    goal_progress_job,
    portfolio_dashboard_job,
    churn_detection_job,
    meta_review_job,
    prompt_evolution_job,
    saas_ops_daily_job,
    gumroad_ops_daily_job,
    cross_sell_analysis_job,
    dynamic_skill_verification_job,
    task_queue_processor_job,
    # Blog automation jobs
    blog_daily_schedule_job,
    blog_weekly_review_job,
    blog_market_research_job,
    # JARVIS Protocol jobs
    blog_competitor_crawl_job,
    blog_auto_improve_job,
)

logger = logging.getLogger("REZE.daemon")


# ============================================================
# WebhookNotifier - 태스크 완료 알림
# ============================================================

class WebhookNotifier:
    """태스크 완료 시 Webhook으로 알림. 3회 재시도."""

    def __init__(self, url: str = ""):
        self.url = url or config.WEBHOOK_URL

    async def notify(self, task_id: str, result: dict):
        """Webhook 발송."""
        if not self.url:
            return

        payload = {
            "task_id": task_id,
            "success": result.get("status") == "success",
            "answer_preview": str(result.get("answer", ""))[:200],
            "steps": result.get("steps", 0),
            "total_tokens": result.get("total_tokens", 0),
        }

        delays = [1, 5, 15]
        for i, delay in enumerate(delays):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(self.url, json=payload, timeout=10) as resp:
                        if resp.status < 400:
                            return
                        logger.warning(f"Webhook retry {i+1}: HTTP {resp.status}")
            except Exception as e:
                logger.warning(f"Webhook retry {i+1}: {e}")

            if i < len(delays) - 1:
                await asyncio.sleep(delay)

        logger.error(f"Webhook failed after {len(delays)} retries: {task_id}")


# Update state's WebhookNotifier reference
state.__class__.notifier = None  # Will be set in lifespan


# ============================================================
# Queue Worker - pending 태스크 순차 처리
# ============================================================

async def queue_worker():
    """pending 태스크를 순차적으로 처리 (worker=1)."""
    logger.info("Queue worker started")
    while True:
        try:
            task = state.ssot.pop_next_pending()
            if not task:
                await asyncio.sleep(5)
                continue

            task_id = task["id"]
            task_text = task.get("task_spec", task.get("task", ""))
            source = task.get("source", "queue")
            logger.info(f"Processing queued task: {task_id} (source={source})")

            try:
                # Blog tasks get special handling
                if "[BLOG:" in task_text or source == "blog_scheduler":
                    result = await _process_blog_task(task_id, task_text)
                else:
                    result = await state.core.run(task_text, source=source)

                # Mark task as complete
                status = "success" if result.get("success") or result.get("status") in ("success", "completed") else "failed"
                result_str = json.dumps(result, ensure_ascii=False, default=str)[:2000]
                state.ssot.complete_daemon_task(task_id, status, result_str)

                # Webhook 알림
                if state.notifier:
                    await state.notifier.notify(task_id, result)

                logger.info(f"Task {task_id} completed: {status}")

            except Exception as e:
                logger.error(f"Task {task_id} failed: {e}")
                state.ssot.complete_daemon_task(task_id, "failed", str(e))

        except asyncio.CancelledError:
            logger.info("Queue worker cancelled")
            break
        except Exception as e:
            logger.error(f"Queue worker error: {e}")
            await asyncio.sleep(10)


async def _process_blog_task(task_id: str, task_spec: str) -> dict:
    """
    블로그 태스크 전용 처리기 (품질 게이트 포함).
    task_spec에서 정보 추출 → Tavily 리서치 → 글 작성 → 품질 검사 → 재작성(최대3회) → 발행
    """
    import re
    from pathlib import Path
    from datetime import datetime
    import config
    from blog_quality_gate import (
        run_quality_gate, get_rewrite_prompt,
        get_llm_quality_prompt, parse_llm_quality_response
    )

    logger.info(f"[BLOG] Processing blog task: {task_id}")

    MAX_REWRITE_ATTEMPTS = 3

    try:
        # 1. task_spec에서 정보 추출
        post_type = "news"
        category = "Chatbot"
        target_length = 1200  # 최소 1000단어 맞추려면 목표는 더 높게

        type_match = re.search(r'\[BLOG:aitoolslab\]\s*(\w+)', task_spec)
        if type_match:
            type_label = type_match.group(1).lower()
            type_map = {"news": "news", "top": "top", "picks": "top", "review": "review",
                       "compare": "compare", "discovery": "discovery"}
            post_type = type_map.get(type_label, "news")

        cat_match = re.search(r'카테고리:\s*(\w+)', task_spec)
        if cat_match:
            category = cat_match.group(1)

        length_match = re.search(r'목표 길이:\s*(\d+)', task_spec)
        if length_match:
            target_length = max(int(length_match.group(1)), 1200)

        # 2. Tavily 리서치
        from daemon.state import _tavily_search_fn
        search_query = f"AI {category} tools 2026 {post_type} guide pricing features"
        search_results = await _tavily_search_fn(search_query)

        research_context = ""
        if search_results:
            for r in search_results[:5]:
                research_context += f"- {r.get('title', '')}: {r.get('content', '')[:300]}\n"

        # 3. 초기 글 작성
        article_content = await _generate_blog_article(
            post_type, category, target_length, research_context
        )

        # 4. 품질 게이트 + 재작성 루프 (Hard Check + LLM Score)
        quality_passed = False
        final_score = 0
        llm_result = None
        rewrite_count = 0
        MIN_COMBINED_SCORE = 7.0  # Hard(10) + LLM(10) → combined threshold

        for attempt in range(MAX_REWRITE_ATTEMPTS + 1):
            # Hard check
            quality_result = run_quality_gate(article_content, post_type)
            hard_score = quality_result["score"]

            # LLM quality check (using reflection model for cost efficiency)
            llm_prompt = get_llm_quality_prompt(article_content, post_type)
            llm_response = await state.router.call(
                "reflection",  # Gemini Flash for cost efficiency
                [{"role": "user", "content": llm_prompt}],
                system="You are a strict tech journalism editor. Rate honestly."
            )
            llm_result = parse_llm_quality_response(llm_response.text)
            llm_score = llm_result.get("score", 5.0)

            # Combined score (hard 40% + LLM 60%)
            final_score = round(hard_score * 0.4 + llm_score * 0.6, 1)

            logger.info(f"[BLOG] Quality #{attempt}: hard={hard_score}, llm={llm_score}, combined={final_score}")

            # Pass if: hard check passed AND combined score >= threshold
            if quality_result["passed"] and final_score >= MIN_COMBINED_SCORE:
                quality_passed = True
                break

            if attempt < MAX_REWRITE_ATTEMPTS:
                # 재작성 시도
                rewrite_count += 1
                logger.info(f"[BLOG] Rewriting (attempt {rewrite_count}/{MAX_REWRITE_ATTEMPTS}): {quality_result['issues']}")

                rewrite_prompt = get_rewrite_prompt(article_content, quality_result, llm_result)
                response = await state.router.call(
                    "reflection",  # Gemini Flash for self-refine
                    [{"role": "user", "content": rewrite_prompt}],
                    system="You are an expert tech blogger. Fix all quality issues while maintaining the article's core information."
                )
                article_content = response.text.strip()

        # 5. 슬러그 생성
        title_match = re.search(r'title:\s*["\']([^"\']+)["\']', article_content)
        if title_match:
            title = title_match.group(1)
            slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')[:50]
        else:
            slug = f"{category.lower()}-{post_type}-{datetime.now().strftime('%Y%m%d%H%M')}"

        content_dir = Path.home() / "ai-tools-lab" / "src" / "content" / "blog"
        file_path = content_dir / f"{slug}.md"

        # 6. 품질 미달 시 draft로 저장
        if not quality_passed:
            logger.warning(f"[BLOG] Quality gate failed after {MAX_REWRITE_ATTEMPTS} attempts. Saving as draft.")
            # draft: true로 변경
            article_content = re.sub(
                r'draft:\s*false',
                'draft: true',
                article_content
            )
            file_path.write_text(article_content)

            state.ssot.save_signal("blog_draft_saved", json.dumps({
                "slug": slug,
                "reason": "quality_gate_failed",
                "score": final_score,
                "llm_feedback": llm_result.get("feedback", "") if llm_result else "",
                "issues": quality_result.get("issues", [])
            }))

            return {
                "success": False,
                "status": "draft",
                "slug": slug,
                "score": final_score,
                "issues": quality_result.get("issues", []),
                "message": f"품질 미달 (점수: {final_score}/10). draft로 저장됨."
            }

        # 7. 품질 통과 → 파일 저장
        file_path.write_text(article_content)
        logger.info(f"[BLOG] Article saved: {file_path} (score: {final_score})")

        # 8. publish-blog.sh 실행
        import subprocess
        publish_script = Path.home() / "reze-agent" / "scripts" / "publish-blog.sh"
        if publish_script.exists():
            result = subprocess.run(
                ["bash", str(publish_script), f"{slug}.md"],
                capture_output=True, text=True, timeout=120
            )
            if result.returncode == 0:
                logger.info(f"[BLOG] Published: {slug}")
            else:
                logger.warning(f"[BLOG] Publish script warning: {result.stderr[:200]}")

        # 9. Signal 저장 (품질 상세 포함)
        state.ssot.save_signal("blog_published", json.dumps({
            "slug": slug,
            "title": title_match.group(1) if title_match else slug,
            "post_type": post_type,
            "category": category,
            "task_id": task_id,
            "quality_score": final_score,
            "llm_breakdown": llm_result if llm_result else {},
            "rewrite_count": rewrite_count
        }))

        # 10. Discord 선톡 알림
        try:
            from discord_notify import notify_blog_published
            await notify_blog_published(
                title_match.group(1) if title_match else slug,
                category,
                f"https://aitoolslab.runstate.dev/blog/{slug}"
            )
        except Exception as e:
            logger.warning(f"[BLOG] Discord notification failed: {e}")

        return {
            "success": True,
            "status": "completed",
            "slug": slug,
            "post_type": post_type,
            "category": category,
            "quality_score": final_score,
            "rewrite_count": rewrite_count
        }

    except Exception as e:
        logger.error(f"[BLOG] Task processing failed: {e}")
        return {
            "success": False,
            "status": "failed",
            "error": str(e)
        }


async def _generate_blog_article(post_type: str, category: str, target_length: int, research_context: str) -> str:
    """품질 게이트를 통과할 수 있는 블로그 글 생성 (TechRadar/Verge/CNET 수준)"""
    from datetime import datetime
    from blog_quality_gate import (
        get_writing_system_prompt,
        get_type_specific_prompt,
        load_few_shot_example,
        BANNED_PHRASES
    )

    # 시스템 프롬프트 조합
    system_prompt = get_writing_system_prompt()
    type_prompt = get_type_specific_prompt(post_type)

    # Few-shot 예시 로드
    few_shot = load_few_shot_example(post_type)
    few_shot_section = ""
    if few_shot:
        few_shot_section = f"""
## Reference Example (follow this style):
{few_shot[:2000]}
"""

    # 사용자 프롬프트
    prompt = f"""Write a high-quality {post_type} blog post for AI Tools Lab.

## Task Specifications
- Type: {post_type}
- Category: {category}
- Minimum length: {target_length} words (MUST exceed 800 words)
- Date: {datetime.now().strftime('%Y-%m-%d')}

{type_prompt}
{few_shot_section}
## Research Context (use this data, don't make up facts):
{research_context[:2500]}

## Output Format
Output the complete article in markdown with frontmatter:

```markdown
---
title: "Specific, Compelling Title"
description: "Value proposition in one sentence"
type: "{post_type}"
category: "{category}"
date: {datetime.now().strftime('%Y-%m-%d')}
readTime: "X min"
featured: false
draft: false
---

[Article content following all quality requirements]
```

Remember:
- Start with a HOOK (specific fact or question, not generic statement)
- Every claim needs a number
- Use markdown tables for any comparison
- End with "The Verdict" not "Conclusion"
- Include "Best for:" and "Skip if:" recommendations

Write the complete article now:"""

    response = await state.router.call(
        "writing",  # Gemini Pro for high-quality content
        [{"role": "user", "content": prompt}],
        system=system_prompt
    )

    return response.text.strip()


# ============================================================
# Lifespan - 초기화 + 스케줄러 등록 + 종료
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """서버 시작/종료 관리."""
    logger.info("=== REZE Agent v4.0 ULTIMATE Starting ===")

    # === Core 초기화 ===
    from ssot import SSOT
    from reze_permissions import PermissionSystem
    from reze_tools import ToolExecutor
    from reze_core import REZECore, ModelRouter, CircuitBreaker
    from skills_manager import SkillsManager

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

    # === v3.3 신규 모듈 ===
    from reze_self_healing import SelfHealing
    from reze_alert import AlertManager
    from reze_biz import BizTracker

    state.self_healing = SelfHealing(
        state.tools, state.ssot, state.router, dry_run=False
    )
    state.alert_manager = AlertManager(state.ssot)
    state.biz_tracker = BizTracker(state.ssot)

    # === Phase 4 Part D+E 초기화 ===
    from saas_monitor import SaaSMonitor
    from saas_marketing import init_marketing
    from gumroad_manager import init_gumroad
    from feature_prioritizer import init_prioritizer
    from landing_optimizer import LandingOptimizer
    from launch_sequence import LaunchSequence

    state.saas_monitor = SaaSMonitor(
        state.ssot,
        alert_fn=state.alert_manager.send if state.alert_manager else None,
        call_llm_fn=_call_llm_for_learning,
    )
    init_marketing(state.ssot, alert_fn=state.alert_manager.send if state.alert_manager else None)
    init_gumroad(
        state.ssot,
        alert_fn=state.alert_manager.send if state.alert_manager else None,
        call_llm_fn=_call_llm_for_learning,
    )
    init_prioritizer(state.ssot, call_llm_fn=_call_llm_for_learning)
    state.landing_optimizer = LandingOptimizer(
        state.ssot,
        call_llm_fn=_call_llm_for_learning,
        alert_fn=state.alert_manager.send if state.alert_manager else None,
    )
    state.launch_sequence = LaunchSequence(
        state.ssot,
        alert_fn=state.alert_manager.send if state.alert_manager else None,
        call_llm_fn=_call_llm_for_learning,
    )

    # === v4.0 ULTIMATE 초기화 ===
    from capability_engine import CapabilityEngine
    from autonomous_ops import AutonomousLoop
    from goal_execution_bridge import GoalExecutionBridge
    from agent_supervisor import AgentSupervisor
    from saas_operations import SaaSOperations
    from gumroad_operations import GumroadOperations
    from growth_engine import CrossPortfolioGrowth
    from meta_cognition import MetaCognitionReview
    from prompt_evolver import PromptEvolver

    state.capability_engine = CapabilityEngine(
        call_llm_fn=_call_llm_for_learning,
        ssot=state.ssot,
        tools=state.tools,
        discord_notify=_discord_notify_fn,
        tavily_search=_tavily_search_fn,
    )
    state.autonomous_loop = AutonomousLoop(
        call_llm_fn=_call_llm_for_learning,
        ssot=state.ssot,
        capability_engine=state.capability_engine,
        discord_notify=_discord_notify_fn,
        tavily_search=_tavily_search_fn,
    )
    state.goal_bridge = GoalExecutionBridge(
        call_llm_fn=_call_llm_for_learning,
        ssot=state.ssot,
        discord_notify=_discord_notify_fn,
    )
    state.agent_supervisor = AgentSupervisor(
        ssot=state.ssot,
        discord_notify=_discord_notify_fn,
    )
    state.saas_ops = SaaSOperations(
        call_llm_fn=_call_llm_for_learning,
        ssot=state.ssot,
        capability_engine=state.capability_engine,
        discord_notify=_discord_notify_fn,
        tavily_search=_tavily_search_fn,
    )
    state.gumroad_ops = GumroadOperations(
        call_llm_fn=_call_llm_for_learning,
        ssot=state.ssot,
        capability_engine=state.capability_engine,
        discord_notify=_discord_notify_fn,
        tavily_search=_tavily_search_fn,
    )
    state.growth_engine = CrossPortfolioGrowth(
        call_llm_fn=_call_llm_for_learning,
        ssot=state.ssot,
        discord_notify=_discord_notify_fn,
        tavily_search=_tavily_search_fn,
    )
    state.meta_cognition = MetaCognitionReview(
        call_llm_fn=_call_llm_for_learning,
        ssot=state.ssot,
        discord_notify=_discord_notify_fn,
    )
    state.prompt_evolver = PromptEvolver(
        call_llm_fn=_call_llm_for_learning,
        ssot=state.ssot,
        discord_notify=_discord_notify_fn,
    )

    # === v5.0 SOVEREIGN Phase 2 ===
    from discovery_engine import DiscoveryEngine

    state.discovery = DiscoveryEngine(
        ssot=state.ssot,
        tools=state.tools,
        call_llm_fn=_call_llm_for_learning,
        discord_notify=_discord_notify_fn,
    )

    # === v5.0 Phase 4: PlanMemory + ConfigTuner ===
    from plan_memory import PlanMemory
    from config_tuner import ConfigTuner

    state.plan_memory = PlanMemory(ssot=state.ssot, llm_fn=_call_llm_for_learning)
    state.config_tuner = ConfigTuner(ssot=state.ssot, llm_fn=_call_llm_for_learning)

    # === v5.0 Phase 3: Planner + Feedback + WorkerPool ===
    from universal_planner import UniversalPlanner, TaskExecutor as PlanExecutor
    from feedback_engine import FeedbackEngine
    from worker_pool import WorkerPool

    state.planner = UniversalPlanner(
        ssot=state.ssot,
        tools=state.tools,
        call_llm_fn=_call_llm_for_learning,
        plan_memory=state.plan_memory,
    )
    state.feedback = FeedbackEngine(ssot=state.ssot, tools=state.tools)
    state.worker_pool = WorkerPool(ssot=state.ssot)

    state.plan_executor = PlanExecutor(
        ssot=state.ssot,
        tools=state.tools,
        planner=state.planner,
        call_llm_fn=_call_llm_for_learning,
        feedback=state.feedback,
        plan_memory=state.plan_memory,
    )
    logger.info("v5.0 SOVEREIGN: Discovery + Planner + Feedback + WorkerPool + ConfigTuner + PlanMemory initialized")

    # === 스케줄러 설정 ===
    state.scheduler = AsyncIOScheduler(timezone="Asia/Seoul")

    # 기본 Jobs
    state.scheduler.add_job(health_check_job, "interval", hours=1, id="health_check")
    state.scheduler.add_job(judgment_job, "interval", hours=6, id="judgment")
    state.scheduler.add_job(discovery_scan_job, "interval", minutes=30, id="discovery_scan")
    state.scheduler.add_job(feedback_processor_job, "interval",
                            hours=FEEDBACK_CHECK_INTERVAL_HOURS,
                            id="feedback_processor")
    state.scheduler.add_job(daemon_task_processor_job, "interval",
                            minutes=TASK_PROCESSOR_INTERVAL_MINUTES,
                            id="daemon_task_processor")

    # v5.0 Phase 4 Jobs
    state.scheduler.add_job(config_tuner_job, 'interval', hours=168,
                            id='config_tuner', next_run_time=None)
    state.scheduler.add_job(memory_cleanup_job, 'interval', hours=720,
                            id='memory_cleanup')

    # v6.0 Phase 2A: Zombie task detector
    state.scheduler.add_job(stale_task_detector_job, 'interval', minutes=10,
                            id='stale_task_detector')
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
    )
    state.scheduler.add_job(
        competitor_check_job, "cron", day_of_week="mon", hour=9, minute=0, id="competitor_check"
    )
    state.scheduler.add_job(
        keyword_scan_job, "cron", day_of_week="wed", hour=9, minute=0, id="keyword_scan"
    )
    state.scheduler.add_job(
        strategic_thinking_job, "cron", day_of_week="sun", hour=20, minute=0, id="strategic_thinking"
    )
    state.scheduler.add_job(
        weekly_report_job, "cron", day_of_week="sun", hour=21, minute=0, id="weekly_report"
    )
    state.scheduler.add_job(
        security_scan_job, "cron", day_of_week="sat", hour=3, minute=0, id="security_scan"
    )

    # Phase 3: Self-Evolution & Learning Jobs
    state.scheduler.add_job(
        self_assessment_job, "cron", day_of_week="fri", hour=15, minute=0, id="self_assessment"
    )
    state.scheduler.add_job(
        cost_review_job, "cron", day=1, hour=9, minute=0, id="cost_review"
    )

    # Phase 4 Part D+E 스케줄러
    state.scheduler.add_job(
        saas_daily_check_job, "cron", hour=7, minute=30, id="saas_daily_check"
    )
    state.scheduler.add_job(
        gumroad_daily_check_job, "cron", hour=7, minute=45, id="gumroad_daily_check"
    )
    state.scheduler.add_job(
        landing_weekly_review_job, "cron", day_of_week="mon", hour=10, minute=0,
        id="landing_weekly_review"
    )
    state.scheduler.add_job(
        launch_check_job, "cron", hour=8, minute=30, id="launch_check"
    )
    state.scheduler.add_job(
        feature_monthly_report_job, "cron", day=1, hour=10, minute=0,
        id="feature_monthly_report"
    )
    state.scheduler.add_job(
        saas_monthly_report_job, "cron", day=1, hour=10, minute=30,
        id="saas_monthly_report"
    )

    # v4.0 신규 스케줄
    state.scheduler.add_job(
        auto_discovery_job, "interval", hours=1, id="auto_discovery"
    )
    state.scheduler.add_job(
        self_improvement_research_job, "cron", day_of_week="mon", hour=3, minute=0,
        id="self_improvement_research"
    )
    state.scheduler.add_job(
        competitor_research_job, "cron", day_of_week="wed,sat", hour=6, minute=0,
        id="competitor_research"
    )
    state.scheduler.add_job(
        weekly_skill_evolution_job, "cron", day_of_week="sun", hour=4, minute=0,
        id="weekly_skill_evolution"
    )
    state.scheduler.add_job(
        weekly_goal_review_job, "cron", day_of_week="mon", hour=9, minute=30,
        id="weekly_goal_review"
    )

    # v4.0 ULTIMATE 스케줄
    state.scheduler.add_job(
        autonomous_loop_job, "interval", hours=6, id="autonomous_loop"
    )
    state.scheduler.add_job(
        agent_supervisor_scan_job, "interval", minutes=30, id="agent_supervisor_scan"
    )
    state.scheduler.add_job(
        agent_discovery_job, "interval", hours=12, id="agent_discovery"
    )
    state.scheduler.add_job(
        goal_progress_job, "cron", hour=21, minute=0, id="goal_progress"
    )
    state.scheduler.add_job(
        portfolio_dashboard_job, "cron", hour=9, minute=0, id="portfolio_dashboard"
    )
    state.scheduler.add_job(
        churn_detection_job, "cron", hour=10, minute=0, id="churn_detection"
    )
    state.scheduler.add_job(
        meta_review_job, "cron", day_of_week="sun", hour=22, minute=0, id="meta_review"
    )
    state.scheduler.add_job(
        prompt_evolution_job, "cron", day_of_week="sun", hour=23, minute=0, id="prompt_evolution"
    )
    state.scheduler.add_job(
        saas_ops_daily_job, "cron", hour=8, minute=0, id="saas_ops_daily"
    )
    state.scheduler.add_job(
        gumroad_ops_daily_job, "cron", hour=8, minute=15, id="gumroad_ops_daily"
    )
    state.scheduler.add_job(
        cross_sell_analysis_job, "cron", day_of_week="wed", hour=11, minute=0,
        id="cross_sell_analysis"
    )
    state.scheduler.add_job(
        dynamic_skill_verification_job, "cron", hour=14, minute=0,
        id="dynamic_skill_verification"
    )
    state.scheduler.add_job(
        task_queue_processor_job, "interval", minutes=10, id="task_queue_processor"
    )

    # Blog automation jobs (AI Tools Lab)
    state.scheduler.add_job(
        blog_daily_schedule_job, "cron", hour=0, minute=5, id="blog_daily_schedule"
    )
    state.scheduler.add_job(
        blog_weekly_review_job, "cron", day_of_week="sun", hour=9, minute=0,
        id="blog_weekly_review"
    )
    state.scheduler.add_job(
        blog_market_research_job, "cron", day_of_week="mon", hour=8, minute=0,
        id="blog_market_research"
    )

    # JARVIS Protocol jobs
    state.scheduler.add_job(
        blog_competitor_crawl_job, "cron", hour=6, minute=0,
        id="blog_competitor_crawl"
    )
    state.scheduler.add_job(
        blog_auto_improve_job, "cron", hour=22, minute=0,
        id="blog_auto_improve"
    )

    state.scheduler.start()

    # 큐 워커
    state.queue_worker_task = asyncio.create_task(queue_worker())

    providers = list(state.router.providers.keys())
    skills_count = len(state.skills.catalog)
    logger.info(f"Providers: {providers}")
    logger.info(f"Skills: {skills_count}")
    logger.info(f"Scheduler jobs: {[j.id for j in state.scheduler.get_jobs()]}")
    logger.info("=== REZE Agent v4.0 ULTIMATE Ready ===")

    yield

    # === 종료 ===
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
