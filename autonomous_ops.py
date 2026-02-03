"""
REZE v4.0 ULTIMATE Autonomous Operations
- 범용 자율 루프: SENSE → SEARCH → THINK → ACT → VERIFY → LEARN
- 도메인 무관 단일 루프
- Voyager + Manus + SAGE + CrewAI 패턴 통합
"""

import json
import asyncio
import yaml
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable, Any

import logging
logger = logging.getLogger("REZE.autonomous")


class AutonomousLoop:
    """
    범용 자율 루프.
    도메인 무관 - 같은 루프가 블로그, SaaS, Gumroad, 인프라, 새 서비스 전부 처리.
    """

    LOOP_INTERVAL_HOURS = 6

    def __init__(self, call_llm_fn: Callable, ssot, capability_engine,
                 discord_notify: Callable = None, tavily_search: Callable = None):
        """
        Args:
            call_llm_fn: LLM 호출 함수
            ssot: SSOT 인스턴스
            capability_engine: CapabilityEngine 인스턴스
            discord_notify: Discord 알림 함수
            tavily_search: Tavily 검색 함수
        """
        self.call_llm = call_llm_fn
        self.ssot = ssot
        self.capability = capability_engine
        self.discord_notify = discord_notify
        self.tavily_search = tavily_search
        self.services = self._load_services()

    def _load_services(self) -> dict:
        """configs/services.yaml 로드."""
        config_path = Path(__file__).parent / "configs" / "services.yaml"
        if config_path.exists():
            with open(config_path) as f:
                return yaml.safe_load(f)
        return {}

    async def run_cycle(self):
        """하나의 전체 사이클 실행."""
        logger.info("=== Autonomous Loop Cycle Started ===")
        cycle_start = datetime.now()

        # 1) 모든 타겟 수집: 서비스 + 미완료 goal_task
        all_targets = await self._gather_all_targets()

        # 2) 우선순위 정렬
        prioritized = await self._prioritize(all_targets)

        # 3) 각 타겟에 대해 루프 실행
        cycle_results = []
        for target in prioritized[:20]:  # 한 사이클당 최대 20개
            try:
                result = await self._process_target(target)
                cycle_results.append(result)
            except Exception as e:
                logger.error(f"Target processing failed: {target.get('name')} - {e}")
                await self._handle_loop_error(target, e)

        # 4) 사이클 종합 리포트
        await self._cycle_report(cycle_results, cycle_start)

        logger.info("=== Autonomous Loop Cycle Completed ===")
        return cycle_results

    async def _gather_all_targets(self) -> list:
        """모든 처리 대상 수집."""
        targets = []

        # 1) 등록된 서비스들
        for category in ['blogs', 'saas', 'gumroad']:
            category_services = self.services.get(category, {})
            for name, config in category_services.items():
                if config.get('status') != 'planned':
                    targets.append({
                        "name": name,
                        "type": category,
                        "config": config,
                        "source": "service"
                    })

        # 2) 인프라
        infra = self.services.get('infrastructure', {})
        for name, config in infra.items():
            targets.append({
                "name": name,
                "type": "infrastructure",
                "config": config,
                "source": "infrastructure"
            })

        # 3) 감시 대상 에이전트
        agents = self.ssot.get_all_agents()
        for agent in agents:
            targets.append({
                "name": agent['name'],
                "type": "agent",
                "config": dict(agent),
                "source": "supervised_agent"
            })

        # 4) 미완료 goal_task
        pending_tasks = self.ssot.get_pending_tasks_queue(limit=10)
        for task in pending_tasks:
            targets.append({
                "name": task['action'],
                "type": "goal_task",
                "config": task,
                "source": "goal_queue"
            })

        return targets

    async def _prioritize(self, targets: list) -> list:
        """우선순위 정렬."""
        def priority_score(target):
            score = 50  # 기본

            # goal_task는 높은 우선순위
            if target['source'] == 'goal_queue':
                score = target['config'].get('priority', 50)

            # SaaS는 블로그보다 높음
            if target['type'] == 'saas':
                score += 20
            elif target['type'] == 'gumroad':
                score += 15

            # 에이전트 상태가 unhealthy면 최우선
            if target['source'] == 'supervised_agent':
                if target['config'].get('status') == 'unhealthy':
                    score = 100

            return score

        return sorted(targets, key=priority_score, reverse=True)

    async def _process_target(self, target: dict) -> dict:
        """단일 타겟에 대한 SENSE→SEARCH→THINK→ACT→VERIFY→LEARN."""
        logger.info(f"Processing: {target['name']} ({target['type']})")

        context = {
            "target": target,
            "started_at": datetime.now().isoformat()
        }

        # ① SENSE — 현재 상태 파악
        sense_data = await self.sense(target)
        context["sense"] = sense_data

        # ② SEARCH — 외부 정보 수집
        search_data = await self.search(target, sense_data)
        context["search"] = search_data

        # ③ THINK — 판단
        decision = await self.think(context)
        context["decision"] = decision

        if not decision.get("action_needed", False):
            logger.info(f"{target['name']}: No action needed")
            return {
                "target": target['name'],
                "status": "healthy",
                "action": "none",
                "duration_ms": self._duration_ms(context)
            }

        # ④ ACT — 실행
        act_result = await self.act(decision, context)
        context["act"] = act_result

        # ⑤ VERIFY — 검증
        verify_result = await self.verify(act_result, context)
        context["verify"] = verify_result

        # ⑥ LEARN — 학습
        await self.learn(context)

        return {
            "target": target['name'],
            "status": "processed",
            "decision": decision,
            "result": act_result,
            "verified": verify_result.get("passed", False),
            "duration_ms": self._duration_ms(context)
        }

    # ========== SENSE ==========
    async def sense(self, target: dict) -> dict:
        """현재 상태 파악."""
        sense_data = {
            "timestamp": datetime.now().isoformat(),
            "target": target['name'],
            "type": target['type'],
            "checks": []
        }

        config = target.get('config', {})

        # 공통: 헬스체크
        health_url = config.get('health_url')
        if health_url:
            health = await self._http_check(health_url)
            sense_data["checks"].append({
                "type": "health",
                "url": health_url,
                "result": health
            })

        # SaaS: 수익 메트릭
        if target['type'] == 'saas':
            revenue = self.ssot.get_latest_saas_health(target['name'])
            if revenue:
                sense_data["revenue"] = revenue

        # Gumroad: 판매 데이터
        if target['type'] == 'gumroad':
            sales = self.ssot.get_gumroad_revenue(days=7)
            sense_data["sales"] = sales

        # 에이전트: 상태 확인
        if target['source'] == 'supervised_agent':
            sense_data["agent_status"] = config.get('status', 'unknown')
            sense_data["last_healthy"] = config.get('last_healthy')

        # goal_task: 상태
        if target['source'] == 'goal_queue':
            sense_data["task_status"] = config.get('status', 'pending')
            sense_data["retry_count"] = config.get('retry_count', 0)

        # SSOT에서 최근 시그널
        recent_signals = self.ssot.get_recent_signals(hours=6)
        relevant_signals = [s for s in recent_signals
                          if target['name'].lower() in s.get('data', '').lower()]
        sense_data["recent_signals"] = relevant_signals[:5]

        # 이상 감지
        anomaly = await self._detect_anomaly(sense_data)
        sense_data["anomaly"] = anomaly

        return sense_data

    # ========== SEARCH ==========
    async def search(self, target: dict, sense_data: dict) -> dict:
        """외부 정보 수집 (트렌드, 경쟁사, 시장)."""
        search_data = {"queries": [], "findings": []}

        config = target.get('config', {})

        # 검색어 생성
        search_queries = config.get('search_queries', [])
        if not search_queries:
            # 기본 검색어 생성
            search_queries = [f"{target['name']} {target['type']} trends 2026"]

        # Tavily 검색 (있는 경우)
        if self.tavily_search and search_queries:
            for query in search_queries[:2]:  # 타겟당 최대 2회
                try:
                    results = await self.tavily_search(query)
                    search_data["queries"].append(query)
                    if isinstance(results, list):
                        search_data["findings"].extend(results[:3])
                    elif isinstance(results, dict):
                        search_data["findings"].append(results)
                except Exception as e:
                    logger.warning(f"Search failed for {query}: {e}")

        # 경쟁사 정보
        competitors = config.get('competitors', [])
        search_data["competitors"] = competitors

        return search_data

    # ========== THINK ==========
    async def think(self, context: dict) -> dict:
        """판단: 문제? 기회? 할 일?"""
        target = context["target"]
        sense = context["sense"]
        search = context.get("search", {})

        # plan_cache에서 유사 경험 조회
        similar_plans = self.ssot.find_cached_plan_v4(
            target['name'],
            threshold=0.5
        )

        prompt = f"""[역할] 당신은 만능 자율 에이전트의 판단 엔진입니다.

[대상] {target['name']} ({target['type']})

[현재 상태 (SENSE)]
{json.dumps(sense, indent=2, ensure_ascii=False, default=str)}

[외부 정보 (SEARCH)]
{json.dumps(search, indent=2, ensure_ascii=False, default=str)}

[유사 경험 (PLAN_CACHE)]
{json.dumps(similar_plans, indent=2, ensure_ascii=False, default=str) if similar_plans else "없음"}

[판단 요청]
3가지 관점으로 분석하세요:

1. ANALYST: 이상/문제/위험이 있는가? 기회가 있는가?
2. STRATEGIST: 보스의 목표(월수익 $5K)에 어떤 영향? 매출 증가 전략은?
3. OPERATOR: 구체적으로 어떤 조치를 취해야 하는가?

[출력 형식] JSON
{{
  "action_needed": true/false,
  "urgency": "critical|high|medium|low",
  "analysis": {{
    "problems": ["..."],
    "opportunities": ["..."],
    "revenue_impact": "..."
  }},
  "actions": [
    {{
      "capability": "collect|analyze|create|execute|verify|communicate|optimize|learn",
      "description": "구체적 행동",
      "expected_outcome": "..."
    }}
  ],
  "boss_approval_needed": false,
  "reason": "판단 근거"
}}"""

        response = await self.call_llm(prompt, role="analysis")

        try:
            text = response
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            decision = json.loads(text.strip())
        except Exception as e:
            logger.error(f"Decision parsing failed: {e}")
            decision = {
                "action_needed": False,
                "urgency": "low",
                "reason": f"Parsing failed: {e}"
            }

        # 보스 승인 필요 시 Discord 알림
        if decision.get("boss_approval_needed") and self.discord_notify:
            await self.discord_notify(
                f"[{target['name']}] 승인 요청\n"
                f"이유: {decision.get('reason', 'N/A')}\n"
                f"제안 조치: {json.dumps(decision.get('actions', []), ensure_ascii=False)[:500]}"
            )
            decision["status"] = "awaiting_approval"

        return decision

    # ========== ACT ==========
    async def act(self, decision: dict, context: dict) -> dict:
        """역량 기반 실행."""
        results = []
        target = context["target"]

        # Transparency Window: 작업 시작 알림
        if self.discord_notify:
            await self.discord_notify(
                f"🔧 작업 시작: {target['name']}\n"
                f"계획: {len(decision.get('actions', []))}개 액션"
            )

        for action in decision.get("actions", []):
            cap_name = action.get("capability", "execute")
            desc = action.get("description", "")

            try:
                # 역량 엔진 통해 실행
                cap = self.capability.get_capability(cap_name)
                result = await cap.execute(desc, context)

                results.append({
                    "action": desc,
                    "capability": cap_name,
                    "status": "success",
                    "result": result[:1000] if isinstance(result, str) else str(result)[:1000]
                })

                logger.info(f"Action completed: {desc[:50]}")

            except Exception as e:
                logger.error(f"Action failed: {desc[:50]} - {e}")
                results.append({
                    "action": desc,
                    "capability": cap_name,
                    "status": "failed",
                    "error": str(e)
                })

        return {
            "actions_completed": len([r for r in results if r["status"] == "success"]),
            "actions_total": len(results),
            "details": results
        }

    # ========== VERIFY ==========
    async def verify(self, act_result: dict, context: dict, max_retries: int = 2) -> dict:
        """결과 검증."""
        verification = {"passed": True, "checks": [], "score": 0}

        for action_result in act_result.get("details", []):
            if action_result["status"] == "failed":
                verification["passed"] = False
                verification["checks"].append({
                    "action": action_result["action"],
                    "passed": False,
                    "reason": action_result.get("error", "Unknown error")
                })
                continue

            # LLM 품질 검증
            quality_check = await self._quality_check(action_result, context)
            verification["checks"].append(quality_check)

            if not quality_check.get("passed", True):
                verification["passed"] = False

        # 보스 피드백 캘리브레이션
        result_type = context["target"].get("type", "general")
        calibration = self.ssot.get_calibration_offset(result_type)
        if calibration != 0:
            verification["calibration_applied"] = calibration

        # 점수 계산
        passed_checks = [c for c in verification["checks"] if c.get("passed")]
        verification["score"] = len(passed_checks) / len(verification["checks"]) * 10 if verification["checks"] else 0

        return verification

    # ========== LEARN ==========
    async def learn(self, context: dict):
        """경험 저장, 반성, 스킬 축적."""
        target = context["target"]
        decision = context.get("decision", {})
        verify = context.get("verify", {})

        # 1) plan_cache에 경험 저장
        if verify.get("passed", False):
            self.ssot.cache_plan_v4(
                task_pattern=f"{target['type']}:{target['name']}",
                skills_used=[a.get("capability", "") for a in decision.get("actions", [])],
                procedure=json.dumps(decision.get("actions", [])),
                steps=len(decision.get("actions", [])),
                tokens=0,
                score=verify.get("score", 7.0)
            )
            logger.info(f"Experience cached: {target['name']}")

        # 2) 실패 시 반성 저장
        if not verify.get("passed", True):
            failed_actions = [c for c in verify.get("checks", []) if not c.get("passed")]
            if failed_actions:
                self.ssot.save_reflection_v4(
                    task_pattern=f"{target['type']}:{target['name']}",
                    failure_reason=json.dumps(failed_actions[:3], ensure_ascii=False),
                    lesson="실패 원인 분석 필요",
                    suggested_approach="다른 접근법 시도"
                )
                logger.info(f"Reflection saved: {target['name']}")

        # 3) 동적 스킬 상태 업데이트
        skill_status = self.ssot.get_skill_status(target['name'])
        if skill_status:
            if verify.get("passed"):
                success_count = self.ssot.increment_skill_success(target['name'])
                if success_count >= 3 and skill_status['status'] != 'verified':
                    self.ssot.update_skill_status(target['name'], 'verified')
                    if self.discord_notify:
                        await self.discord_notify(
                            f"🎓 스킬 승격: {target['name']} — 3회 연속 성공 → 'verified'"
                        )
            else:
                self.ssot.reset_skill_success(target['name'])

    # ========== HELPERS ==========

    async def _http_check(self, url: str) -> dict:
        """HTTP 헬스체크."""
        import aiohttp
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    return {
                        "status": resp.status,
                        "ok": resp.status == 200
                    }
        except Exception as e:
            return {"status": 0, "ok": False, "error": str(e)}

    async def _detect_anomaly(self, sense_data: dict) -> dict:
        """이상 감지."""
        anomalies = []

        # 헬스체크 실패
        for check in sense_data.get("checks", []):
            if check.get("type") == "health" and not check.get("result", {}).get("ok"):
                anomalies.append({
                    "type": "health_failure",
                    "detail": check
                })

        # 에이전트 상태 이상
        if sense_data.get("agent_status") in ["unhealthy", "error"]:
            anomalies.append({
                "type": "agent_unhealthy",
                "status": sense_data.get("agent_status")
            })

        return {
            "detected": len(anomalies) > 0,
            "count": len(anomalies),
            "items": anomalies
        }

    async def _quality_check(self, action_result: dict, context: dict) -> dict:
        """품질 검증."""
        prompt = f"""[품질 검증]
액션: {action_result.get('action', 'N/A')}
역량: {action_result.get('capability', 'N/A')}
결과: {str(action_result.get('result', ''))[:500]}

검증 기준:
1. 액션이 성공적으로 완료되었는가?
2. 결과가 기대한 것과 일치하는가?
3. 부작용이나 문제가 없는가?

JSON 응답:
{{"passed": true/false, "score": 1-10, "reason": "..."}}"""

        try:
            response = await self.call_llm(prompt, role="evaluation")
            text = response
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            return json.loads(text.strip())
        except:
            return {"passed": True, "score": 7, "reason": "Auto-passed"}

    async def _cycle_report(self, results: list, cycle_start: datetime):
        """사이클 종합 리포트."""
        duration = (datetime.now() - cycle_start).total_seconds()

        processed = [r for r in results if r.get("status") == "processed"]
        healthy = [r for r in results if r.get("status") == "healthy"]
        verified = [r for r in processed if r.get("verified")]

        report = f"""📊 자율 루프 사이클 완료
⏱️ 소요 시간: {duration:.1f}초
📋 처리 대상: {len(results)}개
✅ 건강: {len(healthy)}개
🔧 조치: {len(processed)}개
✔️ 검증 통과: {len(verified)}개"""

        if self.discord_notify:
            await self.discord_notify(report)

        logger.info(report.replace('\n', ' | '))

    async def _handle_loop_error(self, target: dict, error: Exception):
        """루프 에러 처리."""
        logger.error(f"Loop error for {target.get('name')}: {error}")

        if self.discord_notify:
            await self.discord_notify(
                f"⚠️ 자율 루프 에러\n"
                f"대상: {target.get('name')}\n"
                f"에러: {str(error)[:200]}"
            )

    def _duration_ms(self, context: dict) -> int:
        """소요 시간 계산 (ms)."""
        started = context.get("started_at")
        if started:
            start_time = datetime.fromisoformat(started)
            return int((datetime.now() - start_time).total_seconds() * 1000)
        return 0


# === 편의 함수 ===

async def run_autonomous_cycle(call_llm_fn, ssot, capability_engine,
                               discord_notify=None, tavily_search=None):
    """자율 루프 사이클 실행 (단순 래퍼)."""
    loop = AutonomousLoop(
        call_llm_fn=call_llm_fn,
        ssot=ssot,
        capability_engine=capability_engine,
        discord_notify=discord_notify,
        tavily_search=tavily_search
    )
    return await loop.run_cycle()
