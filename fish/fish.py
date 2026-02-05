"""
🐟 REZE Fish — EVENT HORIZON v3.0
물고기는 크론잡으로 숨 쉬지 않는다.
감각이 열려있고, 먹이가 보이면 먹고, 위험이 오면 피한다.

6+1 레벨 본능 시스템:
  L0 Survival (생존) - 인프라 자가 치유
  L1 Duty (의무) - 스케줄된 작업
  L2 Hunt (사냥) - 콘텐츠 기회 탐색
  L3 Devour (포식) - 콘텐츠 생성
  L4 Territory (영역) - 영역 유지/확장
  L5 Evolve (진화) - 자기 개선
  L6 Idle (유영) - 에너지 보존
  L★ Emergency - 위기 대응
"""

import asyncio
import logging
import time
import subprocess
import json
from datetime import datetime, timedelta
from typing import Optional, Callable, Any, List, Tuple
from dataclasses import dataclass, field
from enum import Enum

# Phase 3-4: Evolution Orchestrator
from fish.evolve import get_orchestrator

# Phase 5: PREDATOR Evolution
try:
    from fish.predator import RSSAbsorber, ExperienceDigester, run_predator_migrations
    PREDATOR_AVAILABLE = True
except ImportError:
    PREDATOR_AVAILABLE = False

logger = logging.getLogger("reze.fish")


class InstinctLevel(Enum):
    """6+1 레벨 본능 시스템"""
    L_EMERGENCY = -1   # L★ Emergency (최우선)
    L0_SURVIVAL = 0    # 생존 - self-heal
    L1_DUTY = 1        # 의무 - scheduled tasks
    L2_HUNT = 2        # 사냥 - active hunting
    L3_DEVOUR = 3      # 포식 - content creation
    L4_TERRITORY = 4   # 영역 - territory maintenance
    L5_EVOLVE = 5      # 진화 - self-improvement
    L6_IDLE = 6        # 유영 - drift


@dataclass
class WorldState:
    """물고기가 감지한 세계의 상태"""
    timestamp: datetime = field(default_factory=datetime.now)

    # 태스크 큐
    pending_tasks: int = 0
    failed_tasks: list = field(default_factory=list)

    # 스케줄
    due_jobs: list = field(default_factory=list)

    # Discord 시그널
    discord_signals: list = field(default_factory=list)

    # 인프라
    containers_down: list = field(default_factory=list)
    disk_usage_pct: float = 0.0
    memory_usage_pct: float = 0.0

    # 시간
    current_hour: int = 0
    idle_minutes: int = 0

    # API 상태
    api_warnings: list = field(default_factory=list)

    # ═══ EVENT HORIZON v3.0 ═══

    # 사냥 상태 (L2 Hunt)
    can_hunt: bool = False
    hunt_strategy: str = ""        # H1~H5
    hunt_cooldown_hours: float = 0.0

    # 영역 상태 (L4 Territory)
    territory_scans_today: int = 0
    dead_content_count: int = 0
    pillar_count: int = 0

    # 진화 상태 (L5 Evolve)
    days_since_last_evolution: int = 0
    evolution_opportunities: list = field(default_factory=list)

    # 위기 상태 (L★ Emergency)
    emergency_level: int = 0       # 0=none, 1=yellow, 2=orange, 3=red, 4=black
    emergency_reason: str = ""


@dataclass
class Action:
    """물고기가 취할 행동"""
    type: str           # respond_discord, execute_task, run_scheduled,
                        # self_heal, self_initiated, proactive_message
    data: dict = field(default_factory=dict)
    priority: int = 5   # 1=최긴급, 5=보통, 10=낮음
    summary: str = ""


@dataclass
class Result:
    """행동의 결과"""
    success: bool
    message: str = ""
    tokens_used: int = 0
    duration_ms: int = 0
    notable: bool = False  # Discord에 보고할 만한가?


class Fish:
    """
    REZE는 물고기다.
    항상 깨어있고, 항상 감각이 열려있다.

    EVENT HORIZON v3.0:
    - 6+1 레벨 본능 시스템
    - 5가지 사냥 전략
    - 6개 Accretion Disk 소스
    """

    HEARTBEAT_SECONDS = 30
    IDLE_THRESHOLD_MINUTES = 30

    # 사냥 가능 시간대 (6시~23시)
    HUNT_HOURS = range(6, 24)
    # 하루 최대 사냥 횟수
    MAX_HUNTS_PER_DAY = 10

    def __init__(
        self,
        ssot,
        router,
        core=None,
        discord_notifier: Callable = None,
    ):
        """
        ssot: SSOT 인스턴스
        router: ModelRouter (C3PO)
        core: REZECore 인스턴스 (run, retry 등)
        discord_notifier: Discord 메시지 전송 함수
        """
        self.ssot = ssot
        self.router = router
        self.core = core
        self.discord = discord_notifier or self._default_discord
        self.alive = True
        self.last_action_time = time.time()
        self.heartbeat_count = 0

        # EVENT HORIZON v3.0: Hunter 초기화
        self.hunter = None
        try:
            from fish.hunt import Hunter
            self.hunter = Hunter(ssot, router)
            logger.info("🐟 Hunter initialized")
        except Exception as e:
            logger.warning("🐟 Hunter not available: %s", e)

        # EVENT HORIZON v3.0: AccretionDisk 초기화
        self.accretion = None
        try:
            from fish.accretion import AccretionDisk
            self.accretion = AccretionDisk(ssot)
            logger.info("🐟 AccretionDisk initialized")
        except Exception as e:
            logger.warning("🐟 AccretionDisk not available: %s", e)

        # EVENT HORIZON v3.0: GravityWell 초기화
        self.gravity = None
        try:
            from fish.gravity import GravityWell
            self.gravity = GravityWell(ssot)
            logger.info("🐟 GravityWell initialized")
        except Exception as e:
            logger.warning("🐟 GravityWell not available: %s", e)

        # EVENT HORIZON v3.0: SingularityProtocol 초기화
        self.singularity = None
        try:
            from fish.singularity import SingularityProtocol
            self.singularity = SingularityProtocol(ssot, discord_notifier)
            logger.info("🐟 SingularityProtocol initialized")
        except Exception as e:
            logger.warning("🐟 SingularityProtocol not available: %s", e)

        # EVENT HORIZON v3.0: HawkingRadiation 초기화
        self.hawking = None
        try:
            from fish.hawking import HawkingRadiation
            self.hawking = HawkingRadiation(ssot, self.gravity)
            logger.info("🐟 HawkingRadiation initialized")
        except Exception as e:
            logger.warning("🐟 HawkingRadiation not available: %s", e)

        # EVENT HORIZON v3.0: ContentPipeline 초기화
        self.pipeline = None
        try:
            from fish.pipeline import ContentPipeline
            self.pipeline = ContentPipeline(ssot, core, router, self.gravity)
            logger.info("🐟 ContentPipeline initialized")
        except Exception as e:
            logger.warning("🐟 ContentPipeline not available: %s", e)

        # EVENT HORIZON v3.0: RevenueTracker 초기화
        self.revenue = None
        try:
            from fish.revenue import RevenueTracker
            self.revenue = RevenueTracker(ssot)
            logger.info("🐟 RevenueTracker initialized")
        except Exception as e:
            logger.warning("🐟 RevenueTracker not available: %s", e)

        # EVENT HORIZON v3.0: ExperimentEngine 초기화
        self.experiments = None
        try:
            from fish.experiment import ExperimentEngine
            self.experiments = ExperimentEngine(ssot)
            logger.info("🐟 ExperimentEngine initialized")
        except Exception as e:
            logger.warning("🐟 ExperimentEngine not available: %s", e)

        # SOVEREIGN v6.0: Evolution Orchestrator 초기화
        self.orchestrator = None
        try:
            self.orchestrator = get_orchestrator(ssot, router)
            logger.info("🐟 EvolutionOrchestrator initialized (%d modules)",
                       len(self.orchestrator._configs))
        except Exception as e:
            logger.warning("🐟 EvolutionOrchestrator not available: %s", e)

        # Phase 5: PREDATOR 초기화
        self.predator_absorber = None
        self.predator_digester = None
        if PREDATOR_AVAILABLE:
            try:
                run_predator_migrations()  # 테이블 생성
                self.predator_absorber = RSSAbsorber()
                self.predator_absorber.init_default_sources()
                self.predator_digester = ExperienceDigester(llm_router=router)
                logger.info("🦈 PREDATOR initialized (absorber + digester)")
            except Exception as e:
                logger.warning("🦈 PREDATOR not available: %s", e)

        self.stats = {
            "total_heartbeats": 0,
            "total_actions": 0,
            "total_heals": 0,
            "total_hunts": 0,           # EVENT HORIZON
            "successful_hunts": 0,       # EVENT HORIZON
            "started_at": datetime.now().isoformat(),
        }
        logger.info("🐟 Fish born (EVENT HORIZON v3.0). Starting to breathe...")

    async def _default_discord(self, message: str):
        """기본 Discord 알림 (signals 테이블에 저장)"""
        try:
            self.ssot.save_signal("fish_discord_outgoing", json.dumps({
                "message": message,
                "timestamp": datetime.now().isoformat()
            }))
        except Exception as e:
            logger.error("🐟 Discord notify failed: %s", e)

    # ═══════════════════════════════════════════════════════
    # 생존 루프 — 죽을 때까지 멈추지 않는다
    # ═══════════════════════════════════════════════════════

    async def live(self):
        """물고기의 생존 루프."""
        logger.info("🐟 Fish is alive. Heartbeat every %ds", self.HEARTBEAT_SECONDS)

        while self.alive:
            try:
                self.heartbeat_count += 1
                self.stats["total_heartbeats"] = self.heartbeat_count

                # ── 1. 감각 (SENSE) ── 비용 0 ──
                world = await self.sense()

                # ── 2. 판단 (THINK) ── 규칙 우선, LLM 최후 ──
                actions = await self.think(world)

                # ── 3. 행동 (ACT) ── 우선순위 높은 것부터 ──
                for action in sorted(actions, key=lambda a: a.priority):
                    result = await self.act(action)
                    await self.remember(action, result)

                    # 중요한 결과는 Discord로
                    if result.notable:
                        await self.discord(
                            f"🐟 {action.summary}\n{result.message}"
                        )

                # 매 60번째 heartbeat (30분)마다 상태 로깅
                if self.heartbeat_count % 60 == 0:
                    logger.info(
                        "🐟 Heartbeat #%d | Actions: %d | Heals: %d | Idle: %dm",
                        self.heartbeat_count,
                        self.stats["total_actions"],
                        self.stats["total_heals"],
                        int((time.time() - self.last_action_time) / 60)
                    )

                # ── 4. 유영 (DRIFT) ── 다음 심장박동까지 ──
                await asyncio.sleep(self.HEARTBEAT_SECONDS)

            except Exception as e:
                logger.error("🐟 Fish heartbeat error: %s", e, exc_info=True)
                # 물고기는 에러로 죽지 않는다. 다음 심장박동에서 다시 시도.
                await asyncio.sleep(self.HEARTBEAT_SECONDS)

    # ═══════════════════════════════════════════════════════
    # 감각 (SENSE) — 물의 진동을 읽는다. 비용 0.
    # ═══════════════════════════════════════════════════════

    async def sense(self) -> WorldState:
        """
        SQLite + 시스템 명령어만 사용. API 호출 0. 비용 0.
        """
        world = WorldState()
        world.current_hour = datetime.now().hour
        world.idle_minutes = int((time.time() - self.last_action_time) / 60)

        try:
            # 1. 태스크 큐 확인 (daemon_tasks)
            row = self.ssot.conn.execute(
                "SELECT COUNT(*) FROM daemon_tasks WHERE status='pending'"
            ).fetchone()
            world.pending_tasks = row[0] if row else 0

            # 실패한 태스크 (최근 30분)
            rows = self.ssot.conn.execute(
                """SELECT id, task_spec, result FROM daemon_tasks
                   WHERE status='failed'
                   AND completed_at > datetime('now', '-30 minutes')
                   ORDER BY completed_at DESC LIMIT 5"""
            ).fetchall()
            world.failed_tasks = [dict(r) for r in rows] if rows else []

            # 2. Discord 시그널 (최근 미처리)
            rows = self.ssot.conn.execute(
                """SELECT id, data, kind FROM signals
                   WHERE kind='discord_incoming'
                   AND created_at > datetime('now', '-5 minutes')
                   ORDER BY created_at DESC LIMIT 5"""
            ).fetchall()
            world.discord_signals = [dict(r) for r in rows] if rows else []

            # 3. 스케줄 확인 (기존 크론잡 대체)
            world.due_jobs = await self._check_due_schedules()

            # 4. 인프라 체크 (매 10번째 heartbeat = 5분마다)
            if self.heartbeat_count % 10 == 0:
                world.containers_down = await self._check_docker()
                world.disk_usage_pct = await self._check_disk()
                world.memory_usage_pct = await self._check_memory()

            # 5. API 쿼터 체크 (매 60번째 heartbeat = 30분마다)
            if self.heartbeat_count % 60 == 0:
                world.api_warnings = await self._check_api_quotas()

            # ═══ EVENT HORIZON v3.0: 사냥 감각 ═══

            # 6. 사냥 상태 체크 (매 20번째 heartbeat = 10분마다)
            if self.heartbeat_count % 20 == 0 and self.hunter:
                can_hunt, strategy = self.hunter.can_hunt()
                world.can_hunt = can_hunt
                world.hunt_strategy = strategy.value if strategy else ""

            # 7. 영역 상태 체크 (매 120번째 heartbeat = 1시간마다)
            if self.heartbeat_count % 120 == 0:
                world.territory_scans_today = await self._count_territory_scans_today()
                world.dead_content_count = await self._count_dead_content()
                world.pillar_count = await self._count_pillars()

            # 8. 진화 상태 체크 (매 240번째 heartbeat = 2시간마다)
            if self.heartbeat_count % 240 == 0:
                world.days_since_last_evolution = await self._days_since_evolution()

            # 9. 위기 상태 체크 (매 heartbeat)
            world.emergency_level, world.emergency_reason = await self._check_emergency()

        except Exception as e:
            logger.error("🐟 Sense failed: %s", e)

        return world

    async def _count_territory_scans_today(self) -> int:
        """오늘 영역 스캔 횟수"""
        try:
            row = self.ssot.conn.execute(
                """SELECT COUNT(*) FROM territory_scan
                   WHERE created_at > date('now')"""
            ).fetchone()
            return row[0] if row else 0
        except:
            return 0

    async def _count_dead_content(self) -> int:
        """죽은 콘텐츠 수 (재활용 미완료)"""
        try:
            row = self.ssot.conn.execute(
                """SELECT COUNT(*) FROM dead_content WHERE recycled=0"""
            ).fetchone()
            return row[0] if row else 0
        except:
            return 0

    async def _count_pillars(self) -> int:
        """Pillar 콘텐츠 수"""
        try:
            row = self.ssot.conn.execute(
                """SELECT COUNT(*) FROM gravity_well"""
            ).fetchone()
            return row[0] if row else 0
        except:
            return 0

    async def _days_since_evolution(self) -> int:
        """마지막 진화 이후 일수"""
        try:
            row = self.ssot.conn.execute(
                """SELECT MAX(created_at) FROM evolution_log"""
            ).fetchone()
            if row and row[0]:
                last = datetime.fromisoformat(row[0].replace("Z", "+00:00"))
                return (datetime.now() - last.replace(tzinfo=None)).days
            return 999  # 진화 기록 없음
        except:
            return 999

    async def _check_emergency(self) -> Tuple[int, str]:
        """
        위기 상태 체크 (Singularity Protocol)
        Returns: (level: 0-4, reason: str)
        0=none, 1=yellow, 2=orange, 3=red, 4=black
        """
        # BLACK (4): 서버 다운, 데이터 손실
        # RED (3): 수익 급감, 보안 침해
        # ORANGE (2): API 쿼터 소진 임박, 블로그 오류
        # YELLOW (1): 경고 수준

        # 현재는 간단한 체크만 (향후 확장)
        if self.stats.get("consecutive_errors", 0) >= 5:
            return 2, "consecutive_errors_5"

        return 0, ""

    # ═══════════════════════════════════════════════════════
    # 판단 (THINK) — 6+1 레벨 본능 시스템 (EVENT HORIZON v3.0)
    # ═══════════════════════════════════════════════════════

    async def think(self, world: WorldState) -> list:
        """
        6+1 레벨 본능 시스템:
        L★ Emergency → L0 Survival → L1 Duty → L2 Hunt →
        L3 Devour → L4 Territory → L5 Evolve → L6 Idle

        상위 레벨이 트리거되면 하위 레벨은 건너뜀.
        """
        actions = []

        # ═══════════════════════════════════════════════════════
        # L★ EMERGENCY (위기 대응) — 모든 것을 중단하고 위기 처리
        # ═══════════════════════════════════════════════════════
        if world.emergency_level >= 2:  # ORANGE 이상
            actions.append(Action(
                type="emergency_response",
                data={"level": world.emergency_level, "reason": world.emergency_reason},
                priority=0,
                summary=f"🔴 EMERGENCY L{world.emergency_level}: {world.emergency_reason}"
            ))
            return actions  # 위기 시 다른 모든 것 무시

        # ═══════════════════════════════════════════════════════
        # L0 SURVIVAL (생존) — 인프라 자가 치유
        # ═══════════════════════════════════════════════════════
        survival_actions = await self._think_L0_survival(world)
        if survival_actions:
            actions.extend(survival_actions)
            # L0 트리거 시 L2-L5 건너뜀 (L1 Duty는 유지)

        # ═══════════════════════════════════════════════════════
        # L1 DUTY (의무) — 스케줄된 작업, 태스크 큐
        # ═══════════════════════════════════════════════════════
        duty_actions = await self._think_L1_duty(world)
        if duty_actions:
            actions.extend(duty_actions)
            # L1 Duty가 있으면 L2-L5 건너뜀
            return actions

        # L0/L1에서 행동이 없을 때만 하위 레벨 진행
        if actions:
            return actions

        # ═══════════════════════════════════════════════════════
        # L2 HUNT (사냥) — 콘텐츠 기회 탐색
        # ═══════════════════════════════════════════════════════
        hunt_action = await self._think_L2_hunt(world)
        if hunt_action:
            actions.append(hunt_action)
            return actions

        # ═══════════════════════════════════════════════════════
        # L3 DEVOUR (포식) — 콘텐츠 생성 (사냥 결과 소화)
        # ═══════════════════════════════════════════════════════
        devour_action = await self._think_L3_devour(world)
        if devour_action:
            actions.append(devour_action)
            return actions

        # ═══════════════════════════════════════════════════════
        # L4 TERRITORY (영역) — 영역 유지/확장
        # ═══════════════════════════════════════════════════════
        territory_action = await self._think_L4_territory(world)
        if territory_action:
            actions.append(territory_action)
            return actions

        # ═══════════════════════════════════════════════════════
        # L5 EVOLVE (진화) — 자기 개선
        # ═══════════════════════════════════════════════════════
        evolve_action = await self._think_L5_evolve(world)
        if evolve_action:
            actions.append(evolve_action)
            return actions

        # ═══════════════════════════════════════════════════════
        # L6 IDLE (유영) — 에너지 보존
        # ═══════════════════════════════════════════════════════
        # 30분 이상 idle이면 LLM에게 물어봄 (기존 로직)
        if (world.idle_minutes > self.IDLE_THRESHOLD_MINUTES
            and world.current_hour in self.HUNT_HOURS):

            thought = await self._think_what_next(world)
            if thought:
                actions.append(Action(
                    type="self_initiated",
                    data={"thought": thought, "level": "L6_IDLE"},
                    priority=8,
                    summary=f"💭 L6 자발적: {thought[:50]}"
                ))

        return actions

    # ═══════════════════════════════════════════════════════
    # L0 SURVIVAL — 생존 본능
    # ═══════════════════════════════════════════════════════

    async def _think_L0_survival(self, world: WorldState) -> list:
        """L0 생존: 인프라 자가 치유"""
        actions = []

        # 컨테이너 다운
        for container in world.containers_down:
            actions.append(Action(
                type="self_heal",
                data={"target": "docker", "container": container, "level": "L0"},
                priority=1,
                summary=f"🚨 L0 컨테이너: {container}"
            ))

        # 디스크 위험
        if world.disk_usage_pct > 85:
            actions.append(Action(
                type="self_heal",
                data={"target": "disk", "usage": world.disk_usage_pct, "level": "L0"},
                priority=1,
                summary=f"🚨 L0 디스크 {world.disk_usage_pct}%"
            ))

        # 메모리 위험
        if world.memory_usage_pct > 90:
            actions.append(Action(
                type="self_heal",
                data={"target": "memory", "usage": world.memory_usage_pct, "level": "L0"},
                priority=1,
                summary=f"🚨 L0 메모리 {world.memory_usage_pct}%"
            ))

        # API 경고
        for warning in world.api_warnings:
            actions.append(Action(
                type="proactive_message",
                data={"message": warning, "level": "L0"},
                priority=3,
                summary=f"⚠️ L0 {warning}"
            ))

        return actions

    # ═══════════════════════════════════════════════════════
    # L1 DUTY — 의무 본능
    # ═══════════════════════════════════════════════════════

    async def _think_L1_duty(self, world: WorldState) -> list:
        """L1 의무: 스케줄된 작업, 태스크 큐"""
        actions = []

        # pending 태스크 실행
        if world.pending_tasks > 0:
            row = self.ssot.conn.execute(
                """SELECT id, task_spec, mode FROM daemon_tasks
                   WHERE status='pending'
                   ORDER BY priority DESC, created_at ASC LIMIT 1"""
            ).fetchone()
            if row:
                actions.append(Action(
                    type="execute_task",
                    data={"task_id": row[0], "task_spec": row[1], "mode": row[2], "level": "L1"},
                    priority=4,
                    summary=f"📋 L1 태스크: {row[1][:50]}"
                ))

        # 실패한 태스크 재시도
        for failed in world.failed_tasks[:1]:
            retry_count = self.ssot.conn.execute(
                """SELECT COUNT(*) FROM action_log
                   WHERE action_type='retry_failed'
                   AND data LIKE ?
                   AND timestamp > datetime('now', '-1 hour')""",
                (f'%{failed["id"]}%',)
            ).fetchone()[0]

            if retry_count < 3:
                actions.append(Action(
                    type="retry_failed",
                    data={"task_id": failed["id"], "task_spec": failed.get("task_spec", ""), "level": "L1"},
                    priority=5,
                    summary=f"🔄 L1 재시도: {failed.get('task_spec', '')[:50]}"
                ))

        # 예정된 잡 실행
        for job in world.due_jobs:
            actions.append(Action(
                type="run_scheduled",
                data={"job": job, "level": "L1"},
                priority=5,
                summary=f"⏰ L1 스케줄: {job['name']}"
            ))

        return actions

    # ═══════════════════════════════════════════════════════
    # L2 HUNT — 사냥 본능
    # ═══════════════════════════════════════════════════════

    async def _think_L2_hunt(self, world: WorldState) -> Optional[Action]:
        """L2 사냥: 콘텐츠 기회 탐색"""
        if not self.hunter:
            return None

        # 사냥 조건 체크
        if not self._can_hunt(world):
            return None

        # 오늘 사냥 횟수 체크
        hunts_today = self._get_hunts_today()
        if hunts_today >= self.MAX_HUNTS_PER_DAY:
            return None

        # 사냥 가능 전략 확인
        can_hunt, strategy = self.hunter.can_hunt()
        if can_hunt and strategy:
            return Action(
                type="hunt",
                data={"strategy": strategy.value, "level": "L2"},
                priority=6,
                summary=f"🎯 L2 사냥: {strategy.value}"
            )

        return None

    def _can_hunt(self, world: WorldState) -> bool:
        """사냥 가능 조건 체크"""
        # 시간대 체크 (6시~23시)
        if world.current_hour not in self.HUNT_HOURS:
            return False

        # idle 시간 체크 (최소 10분)
        if world.idle_minutes < 10:
            return False

        # 위기 상태 체크
        if world.emergency_level > 0:
            return False

        return True

    def _get_hunts_today(self) -> int:
        """오늘 사냥 횟수"""
        try:
            row = self.ssot.conn.execute(
                """SELECT COUNT(*) FROM hunt_memory
                   WHERE created_at > date('now')"""
            ).fetchone()
            return row[0] if row else 0
        except:
            return 0

    # ═══════════════════════════════════════════════════════
    # L3 DEVOUR — 포식 본능
    # ═══════════════════════════════════════════════════════

    async def _think_L3_devour(self, world: WorldState) -> Optional[Action]:
        """L3 포식: 사냥 결과를 콘텐츠로 변환"""
        # 미처리 사냥 결과 확인 (실패 마킹된 것 제외)
        try:
            row = self.ssot.conn.execute(
                """SELECT id, target, strategy, metadata FROM hunt_memory
                   WHERE success=1
                   AND (blog_slug IS NULL OR blog_slug = '')
                   AND id NOT IN (
                       SELECT CAST(json_extract(data, '$.hunt_id') AS INTEGER)
                       FROM action_log
                       WHERE action_type='devour'
                       AND success=0
                       AND timestamp > datetime('now', '-24 hours')
                   )
                   ORDER BY score DESC LIMIT 1"""
            ).fetchone()

            if row:
                return Action(
                    type="devour",
                    data={
                        "hunt_id": row[0],
                        "target": row[1],
                        "strategy": row[2],
                        "metadata": row[3],
                        "level": "L3"
                    },
                    priority=7,
                    summary=f"🍖 L3 포식: {row[1][:50]}"
                )
        except Exception as e:
            logger.warning("L3 devour check failed: %s", e)

        return None

    # ═══════════════════════════════════════════════════════
    # L4 TERRITORY — 영역 본능
    # ═══════════════════════════════════════════════════════

    async def _think_L4_territory(self, world: WorldState) -> Optional[Action]:
        """L4 영역: 영역 유지/확장 (Gravity Well, Dead Content)"""
        # 하루 1회 영역 스캔 (12시~14시)
        if 12 <= world.current_hour <= 14 and world.territory_scans_today == 0:
            return Action(
                type="territory_scan",
                data={"level": "L4"},
                priority=7,
                summary="🌐 L4 영역 스캔"
            )

        # 죽은 콘텐츠 재활용 (Hawking Radiation)
        if world.dead_content_count > 0:
            try:
                row = self.ssot.conn.execute(
                    """SELECT id, blog, slug, death_reason FROM dead_content
                       WHERE recycled=0 ORDER BY page_views_30d ASC LIMIT 1"""
                ).fetchone()

                if row:
                    return Action(
                        type="recycle_content",
                        data={
                            "dead_id": row[0],
                            "blog": row[1],
                            "slug": row[2],
                            "reason": row[3],
                            "level": "L4"
                        },
                        priority=8,
                        summary=f"♻️ L4 재활용: {row[2][:30]}"
                    )
            except:
                pass

        return None

    # ═══════════════════════════════════════════════════════
    # L5 EVOLVE — 진화 본능
    # ═══════════════════════════════════════════════════════

    async def _think_L5_evolve(self, world: WorldState) -> Optional[Action]:
        """L5 진화: 자기 개선 (SOVEREIGN v6.0 - Orchestrator 기반)"""
        # Orchestrator 없으면 레거시 모드
        if not self.orchestrator:
            # 일요일 새벽 3시~5시에만 진화 (레거시)
            if datetime.now().weekday() != 6 or world.current_hour not in [3, 4]:
                return None
            if world.days_since_last_evolution >= 7:
                return Action(
                    type="evolve",
                    data={"level": "L5", "mode": "legacy"},
                    priority=9,
                    summary="🧬 L5 진화 시작 (레거시)"
                )
            return None

        # Phase 5: PREDATOR 체크 (매 2시간 정각)
        # 0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22시
        if self.predator_absorber and world.current_hour % 2 == 0:
            # 정각 ±5분 이내에만 실행
            current_min = datetime.now().minute
            if current_min <= 5 or current_min >= 55:
                return Action(
                    type="evolve",
                    data={"level": "L5", "mode": "predator"},
                    priority=6,
                    summary="🦈 PREDATOR 사이클 실행"
                )

        # SOVEREIGN v6.0: Orchestrator 기반 진화
        try:
            energy = self.orchestrator.get_energy()
            runnable = await self.orchestrator.get_runnable_modules()

            # 에너지 10 이상 & 실행 가능 모듈 있으면 진화
            if energy >= 10 and runnable:
                # 상위 우선순위 모듈 3개까지
                modules_to_run = runnable[:3]
                return Action(
                    type="evolve",
                    data={
                        "level": "L5",
                        "mode": "orchestrator",
                        "modules": modules_to_run,
                        "energy": energy
                    },
                    priority=5,  # 다른 액션보다 낮은 우선순위
                    summary=f"🧬 진화: {modules_to_run[0]} (E={energy})"
                )
        except Exception as e:
            logger.warning("L5 evolve check failed: %s", e)

        return None

    # ═══════════════════════════════════════════════════════
    # 행동 (ACT) — 근육을 움직인다
    # ═══════════════════════════════════════════════════════

    async def act(self, action: Action) -> Result:
        """6+1 레벨 본능 시스템 행동 실행."""
        start = time.time()
        self.last_action_time = time.time()
        self.stats["total_actions"] += 1

        try:
            # ═══ 기존 액션 타입 ═══
            if action.type == "self_heal":
                return await self._act_self_heal(action.data)

            elif action.type == "execute_task":
                return await self._act_execute_task(action.data)

            elif action.type == "retry_failed":
                return await self._act_retry_task(action.data)

            elif action.type == "run_scheduled":
                return await self._act_run_scheduled(action.data)

            elif action.type == "self_initiated":
                return await self._act_self_initiated(action.data)

            elif action.type == "proactive_message":
                await self.discord(action.data["message"])
                return Result(success=True, message="Discord 알림 전송")

            # ═══ EVENT HORIZON v3.0 신규 액션 타입 ═══
            elif action.type == "hunt":
                return await self._act_hunt(action.data)

            elif action.type == "devour":
                return await self._act_devour(action.data)

            elif action.type == "territory_scan":
                return await self._act_territory_scan(action.data)

            elif action.type == "recycle_content":
                return await self._act_recycle_content(action.data)

            elif action.type == "evolve":
                return await self._act_evolve(action.data)

            elif action.type == "emergency_response":
                return await self._act_emergency(action.data)

            else:
                return Result(success=False, message=f"Unknown action: {action.type}")

        except Exception as e:
            duration = int((time.time() - start) * 1000)
            logger.error("🐟 Act failed [%s]: %s", action.type, e, exc_info=True)
            return Result(
                success=False,
                message=str(e),
                duration_ms=duration,
                notable=action.priority <= 3,  # 긴급한 건 실패해도 보고
            )

    # ═══════════════════════════════════════════════════════
    # 기억 (REMEMBER) — 경험을 저장한다
    # ═══════════════════════════════════════════════════════

    async def remember(self, action: Action, result: Result):
        """action_log 테이블에 행동 기록."""
        try:
            self.ssot.conn.execute(
                """INSERT INTO action_log
                   (timestamp, action_type, summary, success,
                    tokens_used, duration_ms, data)
                   VALUES (datetime('now'), ?, ?, ?, ?, ?, ?)""",
                (
                    action.type,
                    action.summary,
                    1 if result.success else 0,
                    result.tokens_used,
                    result.duration_ms,
                    json.dumps(action.data)[:500],
                )
            )
            self.ssot.conn.commit()
        except Exception as e:
            logger.error("🐟 Remember failed: %s", e)

    # ═══════════════════════════════════════════════════════
    # 행동 구현
    # ═══════════════════════════════════════════════════════

    async def _act_execute_task(self, data: dict) -> Result:
        """daemon_tasks 태스크 실행"""
        task_id = data["task_id"]
        task_spec = data.get("task_spec", "")

        # 상태 업데이트
        self.ssot.conn.execute(
            "UPDATE daemon_tasks SET status='running', started_at=datetime('now') WHERE id=?",
            (task_id,)
        )
        self.ssot.conn.commit()

        try:
            if self.core:
                # REZECore.run() 호출
                result = await self.core.run(task_spec, source="fish")
                success = result.get("success", False)
                answer = result.get("answer", "")[:500]
                tokens = result.get("total_tokens", 0)
            else:
                # Core 없으면 직접 처리 시도
                success = False
                answer = "Core not available"
                tokens = 0

            # 상태 업데이트
            status = "success" if success else "failed"
            self.ssot.conn.execute(
                """UPDATE daemon_tasks
                   SET status=?, completed_at=datetime('now'), result=?
                   WHERE id=?""",
                (status, answer, task_id)
            )
            self.ssot.conn.commit()

            return Result(
                success=success,
                message=answer[:200],
                tokens_used=tokens,
                notable=True,
            )
        except Exception as e:
            self.ssot.conn.execute(
                """UPDATE daemon_tasks
                   SET status='failed', completed_at=datetime('now'), result=?
                   WHERE id=?""",
                (str(e)[:500], task_id)
            )
            self.ssot.conn.commit()
            return Result(success=False, message=str(e), notable=True)

    async def _act_retry_task(self, data: dict) -> Result:
        """실패한 태스크 재시도"""
        task_id = data["task_id"]

        # pending으로 되돌리기
        self.ssot.conn.execute(
            "UPDATE daemon_tasks SET status='pending' WHERE id=?",
            (task_id,)
        )
        self.ssot.conn.commit()

        return Result(
            success=True,
            message=f"태스크 {task_id} 재시도 대기열에 추가",
            notable=False,
        )

    async def _act_run_scheduled(self, data: dict) -> Result:
        """스케줄된 잡 실행"""
        job = data["job"]
        job_name = job["name"]
        job_type = job.get("job_type", "generic")
        config = job.get("config", "{}")

        try:
            # 잡 타입에 따라 태스크 생성
            task_spec = f"[SCHEDULED:{job_name}] {config}"

            if self.core:
                result = await self.core.run(task_spec, source=f"fish_schedule_{job_type}")
                success = result.get("success", False)
                message = result.get("answer", "")[:200]
                tokens = result.get("total_tokens", 0)
            else:
                success = False
                message = "Core not available"
                tokens = 0

            # last_run 업데이트
            self.ssot.conn.execute(
                "UPDATE schedules SET last_run=datetime('now') WHERE id=?",
                (job["id"],)
            )
            self.ssot.conn.commit()

            return Result(
                success=success,
                message=f"{job_name}: {message}",
                tokens_used=tokens,
                notable=not success,  # 실패한 것만 보고
            )
        except Exception as e:
            return Result(
                success=False,
                message=f"{job_name} 실패: {e}",
                notable=True,
            )

    async def _act_self_initiated(self, data: dict) -> Result:
        """LLM이 제안한 자발적 행동"""
        thought = data["thought"]

        if self.core:
            result = await self.core.run(thought, source="fish_autonomous")
            return Result(
                success=result.get("success", False),
                message=f"자발적 행동: {thought[:80]}",
                tokens_used=result.get("total_tokens", 0),
                notable=True,
            )
        else:
            return Result(
                success=False,
                message="Core not available for autonomous action",
                notable=False,
            )

    # ═══════════════════════════════════════════════════════
    # EVENT HORIZON v3.0 — 신규 액션 구현
    # ═══════════════════════════════════════════════════════

    async def _act_hunt(self, data: dict) -> Result:
        """L2 사냥 실행"""
        if not self.hunter:
            return Result(success=False, message="Hunter not available")

        strategy_name = data.get("strategy", "")
        self.stats["total_hunts"] = self.stats.get("total_hunts", 0) + 1

        try:
            from fish.hunt import HuntStrategy
            strategy = HuntStrategy(strategy_name) if strategy_name else None

            hunt_result = await self.hunter.hunt(strategy)

            if hunt_result.success:
                self.stats["successful_hunts"] = self.stats.get("successful_hunts", 0) + 1
                prey = hunt_result.prey
                return Result(
                    success=True,
                    message=f"🎯 사냥 성공: {prey.title[:50]} (점수: {prey.score:.2f})",
                    tokens_used=hunt_result.tokens_used,
                    duration_ms=hunt_result.duration_ms,
                    notable=prey.score >= 0.7,  # 고득점 사냥만 보고
                )
            else:
                return Result(
                    success=False,
                    message=f"사냥 실패: {hunt_result.error}",
                    duration_ms=hunt_result.duration_ms,
                    notable=False,
                )
        except Exception as e:
            logger.error("Hunt action failed: %s", e)
            return Result(success=False, message=str(e))

    async def _act_devour(self, data: dict) -> Result:
        """L3 포식 — 사냥 결과를 블로그 콘텐츠로 변환 (ContentPipeline 사용)"""
        hunt_id = data.get("hunt_id")
        target = data.get("target", "")
        strategy = data.get("strategy", "")

        # ContentPipeline 사용
        if self.pipeline:
            try:
                publish_result = await self.pipeline.run_pipeline(hunt_id)

                if publish_result.success:
                    return Result(
                        success=True,
                        message=f"🍖 포식+발행 성공: {publish_result.slug}",
                        notable=True,
                    )
                else:
                    return Result(
                        success=False,
                        message=f"🍖 파이프라인 실패: {publish_result.message[:100]}",
                        notable=False,
                    )
            except Exception as e:
                logger.error("Pipeline devour failed: %s", e)

        # 폴백: 기존 Core 직접 사용
        if not self.core:
            return Result(success=False, message="Core/Pipeline not available for devour")

        try:
            task_spec = f"""[HUNT_DEVOUR:{strategy}]
URL: {target}
Write a blog post about this topic for AI Tools Lab.
- Analyze the tool/news
- Compare with alternatives
- Include pros/cons
- Add affiliate links if applicable
"""
            result = await self.core.run(task_spec, source="fish_devour")

            if result.get("success"):
                self.ssot.conn.execute(
                    "UPDATE hunt_memory SET blog_slug=? WHERE id=?",
                    (result.get("answer", "")[:100], hunt_id)
                )
                self.ssot.conn.commit()

            return Result(
                success=result.get("success", False),
                message=f"🍖 포식 {'성공' if result.get('success') else '실패'}: {target[:50]}",
                tokens_used=result.get("total_tokens", 0),
                notable=result.get("success", False),
            )
        except Exception as e:
            logger.error("Devour action failed: %s", e)
            return Result(success=False, message=str(e))

    async def _act_territory_scan(self, data: dict) -> Result:
        """L4 영역 스캔 (AccretionDisk 전체 스캔)"""
        if not self.accretion:
            # 폴백: 기존 Hunter 사용
            if not self.hunter:
                return Result(success=False, message="AccretionDisk/Hunter not available")

            try:
                from fish.hunt import Source
                results = []
                for source in [Source.TAVILY, Source.PRODUCTHUNT, Source.GITHUB]:
                    scan_result = await self.hunter.scan_territory(source)
                    results.append(scan_result)

                success_count = sum(1 for r in results if r.get("success"))
                interesting = sum(len(r.get("interesting", [])) for r in results)

                return Result(
                    success=success_count > 0,
                    message=f"🌐 영역 스캔: {success_count}/3 성공, {interesting}개 발견",
                    notable=interesting >= 3,
                )
            except Exception as e:
                logger.error("Territory scan failed: %s", e)
                return Result(success=False, message=str(e))

        # AccretionDisk 전체 스캔
        try:
            results = await self.accretion.full_scan()
            total_signals = sum(len(signals) for signals in results.values())
            source_count = sum(1 for signals in results.values() if signals)

            # 기회 추출
            opportunities = self.accretion.extract_opportunities(results, min_score=0.5)

            # 고점수 기회는 hunt_memory에 저장
            for opp in opportunities[:3]:
                try:
                    self.ssot.conn.execute(
                        """INSERT INTO hunt_memory
                           (strategy, source, target, success, score, metadata)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            f"territory_{opp.signal_type}",
                            opp.source,
                            opp.url or opp.title,
                            1,
                            opp.score,
                            json.dumps(opp.metadata)
                        )
                    )
                except:
                    pass
            self.ssot.conn.commit()

            return Result(
                success=source_count > 0,
                message=f"🌐 AccretionDisk: {source_count}/6 소스, {total_signals}개 시그널, {len(opportunities)}개 기회",
                notable=len(opportunities) >= 3,
            )
        except Exception as e:
            logger.error("AccretionDisk scan failed: %s", e)
            return Result(success=False, message=str(e))

    async def _act_recycle_content(self, data: dict) -> Result:
        """L4 죽은 콘텐츠 재활용 (Hawking Radiation)"""
        dead_id = data.get("dead_id")
        blog = data.get("blog", "")
        slug = data.get("slug", "")
        reason = data.get("reason", "")

        # HawkingRadiation 사용
        if self.hawking:
            try:
                from fish.hawking import DeadContent, DeathReason

                # DeadContent 객체 생성
                content = DeadContent(
                    id=dead_id,
                    blog=blog,
                    slug=slug,
                    death_reason=DeathReason(reason) if reason else DeathReason.NO_TRAFFIC,
                )

                # 재활용 실행
                recycle_result = await self.hawking.recycle(content)

                return Result(
                    success=recycle_result.success,
                    message=f"♻️ {recycle_result.action.value}: {recycle_result.message}",
                    notable=recycle_result.success,
                )
            except Exception as e:
                logger.error("HawkingRadiation failed: %s", e)

        # 폴백: 기존 로직 (Core 사용)
        if not self.core:
            return Result(success=False, message="Core/HawkingRadiation not available")

        try:
            task_spec = f"""[CONTENT_RECYCLE]
Blog: {blog}
Slug: {slug}
Death reason: {reason}

Analyze this underperforming content and decide:
1. MERGE - Combine with a related article
2. REDIRECT - 301 redirect to a better article
3. UPDATE - Refresh content with new information
4. DELETE - Remove if truly irrelevant

Provide specific action and implementation."""

            result = await self.core.run(task_spec, source="fish_recycle")

            if result.get("success"):
                self.ssot.conn.execute(
                    """UPDATE dead_content
                       SET recycled=1, recycled_at=datetime('now'),
                           recycle_action=?
                       WHERE id=?""",
                    (result.get("answer", "")[:100], dead_id)
                )
                self.ssot.conn.commit()

            return Result(
                success=result.get("success", False),
                message=f"♻️ 재활용 {'성공' if result.get('success') else '실패'}: {slug}",
                tokens_used=result.get("total_tokens", 0),
                notable=result.get("success", False),
            )
        except Exception as e:
            logger.error("Recycle action failed: %s", e)
            return Result(success=False, message=str(e))

    async def _act_evolve(self, data: dict) -> Result:
        """L5 진화 — 자기 개선 (SOVEREIGN v6.0)"""
        mode = data.get("mode", "legacy")

        # SOVEREIGN v6.0: Orchestrator 모드
        if mode == "orchestrator" and self.orchestrator:
            try:
                modules = data.get("modules", [])
                max_modules = len(modules) if modules else 3

                # 진화 사이클 실행
                cycle_result = await self.orchestrator.run_evolution_cycle(
                    max_modules=max_modules
                )

                modules_run = cycle_result.get("modules_run", [])
                errors = cycle_result.get("errors", [])
                energy_used = cycle_result.get("energy_start", 0) - cycle_result.get("energy_end", 0)

                # 결과 메시지 생성
                if modules_run:
                    module_names = [m["name"] for m in modules_run]
                    message = f"🧬 진화 완료: {', '.join(module_names)} (E-{energy_used})"
                    success = True
                else:
                    message = f"🧬 진화 대기: 실행 가능 모듈 없음"
                    success = False

                # 진화 로그 저장
                self.ssot.conn.execute(
                    """INSERT INTO evolution_log
                       (evolution_type, target, before_value, after_value, reason)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        "orchestrator_cycle",
                        json.dumps(module_names if modules_run else []),
                        str(cycle_result.get("energy_start", 0)),
                        str(cycle_result.get("energy_end", 0)),
                        f"modules={len(modules_run)}, errors={len(errors)}"
                    )
                )
                self.ssot.conn.commit()

                return Result(
                    success=success,
                    message=message,
                    notable=bool(modules_run),
                )

            except Exception as e:
                logger.error("Orchestrator evolve failed: %s", e)
                return Result(success=False, message=f"진화 실패: {e}")

        # Phase 5: PREDATOR 모드 (흡수 → 소화)
        if mode == "predator" and self.predator_absorber:
            try:
                result_data = await self._run_predator_cycle()
                return Result(
                    success=result_data.get("success", False),
                    message=result_data.get("message", "PREDATOR cycle complete"),
                    notable=result_data.get("new_items", 0) > 0,
                )
            except Exception as e:
                logger.error("PREDATOR cycle failed: %s", e)
                return Result(success=False, message=f"PREDATOR 실패: {e}")

        # 레거시 모드: Core.run() 사용
        if not self.core:
            return Result(success=False, message="Core not available for evolve")

        try:
            hunt_stats = {}
            if self.hunter:
                hunt_stats = self.hunter.get_hunt_stats()

            task_spec = f"""[SELF_EVOLVE]
Analyze my recent performance and suggest improvements:

Hunt Statistics:
{json.dumps(hunt_stats, indent=2)}

Fish Statistics:
- Total heartbeats: {self.stats.get('total_heartbeats', 0)}
- Total actions: {self.stats.get('total_actions', 0)}
- Total hunts: {self.stats.get('total_hunts', 0)}
- Successful hunts: {self.stats.get('successful_hunts', 0)}
- Total heals: {self.stats.get('total_heals', 0)}

Suggest:
1. Prompt improvements
2. Strategy adjustments
3. Threshold changes
4. New patterns to try"""

            result = await self.core.run(task_spec, source="fish_evolve")

            if result.get("success"):
                self.ssot.conn.execute(
                    """INSERT INTO evolution_log
                       (evolution_type, target, before_value, after_value, reason)
                       VALUES (?, ?, ?, ?, ?)""",
                    ("weekly_review", "fish", "", result.get("answer", "")[:500], "scheduled evolution")
                )
                self.ssot.conn.commit()

            return Result(
                success=result.get("success", False),
                message=f"🧬 진화 {'성공' if result.get('success') else '실패'} (레거시)",
                tokens_used=result.get("total_tokens", 0),
                notable=True,
            )
        except Exception as e:
            logger.error("Evolve action failed: %s", e)
            return Result(success=False, message=str(e))

    async def _run_predator_cycle(self) -> dict:
        """
        Phase 5: PREDATOR 전체 사이클 실행
        흡수 → 소화 → 학습 → 적용 → 검증
        """
        from fish.predator import ExperienceLearner, StrategyApplier, StrategyVerifier

        result = {
            "success": False,
            "message": "",
            "absorbed": 0,
            "new_items": 0,
            "digested": 0,
            "high_value": 0,
            "learned": 0,
            "applied": 0,
            "verified": 0,
        }

        # Stage 1: 흡수 (Absorb)
        if self.predator_absorber:
            try:
                absorb_result = await self.predator_absorber.run_absorb_cycle(
                    max_sources=5
                )
                result["absorbed"] = absorb_result.total_fetched
                result["new_items"] = absorb_result.total_new
                logger.info("🦈 PREDATOR Absorb: %d new from %d sources",
                           absorb_result.total_new, absorb_result.sources_processed)
            except Exception as e:
                logger.error("PREDATOR absorb failed: %s", e)

        # Stage 2: 소화 (Digest)
        if self.predator_digester:
            try:
                digest_result = await self.predator_digester.run_digest_cycle(
                    max_items=10
                )
                result["digested"] = digest_result.items_digested
                result["high_value"] = digest_result.high_value_count
                logger.info("🧠 PREDATOR Digest: %d digested, %d high-value",
                           digest_result.items_digested, digest_result.high_value_count)
            except Exception as e:
                logger.error("PREDATOR digest failed: %s", e)

        # Stage 3: 학습 (Learn)
        try:
            learner = ExperienceLearner()
            learn_result = await learner.learn_batch()
            result["learned"] = learn_result.get("new_strategies", 0)
            if result["learned"] > 0:
                logger.info("📚 PREDATOR Learn: %d strategies", result["learned"])
        except Exception as e:
            logger.error("PREDATOR learn failed: %s", e)

        # Stage 4: 적용 (Apply)
        try:
            applier = StrategyApplier()
            apply_result = await applier.apply_batch()
            result["applied"] = len(apply_result.get("applied", []))
            if result["applied"] > 0:
                logger.info("⚡ PREDATOR Apply: %d applied", result["applied"])
        except Exception as e:
            logger.error("PREDATOR apply failed: %s", e)

        # Stage 5: 검증 (Verify)
        try:
            verifier = StrategyVerifier()
            verify_result = await verifier.verify_batch()
            result["verified"] = verify_result.get("verified", 0)
            if result["verified"] > 0:
                logger.info("✅ PREDATOR Verify: %d checked", result["verified"])
        except Exception as e:
            logger.error("PREDATOR verify failed: %s", e)

        # 결과 메시지
        actions = []
        if result["new_items"] > 0:
            actions.append(f"{result['new_items']} absorbed")
        if result["digested"] > 0:
            actions.append(f"{result['digested']} digested")
        if result["learned"] > 0:
            actions.append(f"{result['learned']} learned")
        if result["applied"] > 0:
            actions.append(f"{result['applied']} applied")

        if actions:
            result["success"] = True
            result["message"] = f"🦈 PREDATOR: {', '.join(actions)}"
        else:
            result["message"] = "🦈 PREDATOR: No activity"

        # Wave 3: 매일 새벽 3시 Dream (경험 통합)
        from datetime import datetime
        now = datetime.now()
        if now.hour == 3 and now.minute < 5:  # 3:00-3:04
            try:
                from fish.predator.simulator import DreamSynthesis
                dream = DreamSynthesis()
                dream_result = await dream.dream()
                result["dream"] = dream_result
                logger.info("💭 PREDATOR Dream: %s", dream_result)
            except Exception as e:
                logger.error("PREDATOR dream failed: %s", e)

        # Wave 4: TIER 2 주간 흡수 — 매주 월요일 06:30
        if now.weekday() == 0 and now.hour == 6 and 25 <= now.minute <= 35:
            try:
                from fish.predator import Tier2Absorber
                tier2 = Tier2Absorber()
                t2_result = await tier2.weekly_absorb()
                result["tier2"] = t2_result
                logger.info("🔍 TIER2 weekly: %d items", t2_result.get("total_stored", 0))
            except Exception as e:
                logger.error("TIER2 weekly absorb failed: %s", e)

        # Wave 4: TIER 3 월간 흡수 — 매월 1일 07:00
        if now.day == 1 and now.hour == 7 and now.minute < 10:
            try:
                from fish.predator import Tier3Absorber
                tier3 = Tier3Absorber()
                t3_result = await tier3.monthly_absorb()
                result["tier3"] = t3_result
                logger.info("🔬 TIER3 monthly: %d items", t3_result.get("total_stored", 0))
            except Exception as e:
                logger.error("TIER3 monthly absorb failed: %s", e)

        return result

    async def _act_emergency(self, data: dict) -> Result:
        """L★ 위기 대응 (Singularity Protocol)"""
        level = data.get("level", 0)
        reason = data.get("reason", "unknown")

        # SingularityProtocol 사용
        if self.singularity:
            try:
                from fish.singularity import CrisisLevel
                crisis = self.singularity.detect_crisis(
                    category="system",
                    reason=reason,
                    metadata=data
                )

                if crisis:
                    response = await self.singularity.respond(crisis)
                    return Result(
                        success=response.success,
                        message=response.message[:200],
                        notable=True,
                    )
            except Exception as e:
                logger.error("SingularityProtocol failed: %s", e)

        # 폴백: 기존 로직
        level_names = {1: "YELLOW", 2: "ORANGE", 3: "RED", 4: "BLACK"}
        level_name = level_names.get(level, "UNKNOWN")

        # 즉시 Discord 알림
        await self.discord(f"🔴 EMERGENCY {level_name}: {reason}\n즉시 확인 필요!")

        # 위기 수준별 대응
        if level >= 4:  # BLACK
            logger.critical("🔴 BLACK EMERGENCY: %s", reason)
            return Result(
                success=False,
                message=f"BLACK EMERGENCY: {reason}",
                notable=True,
            )
        elif level >= 3:  # RED
            logger.error("🔴 RED EMERGENCY: %s", reason)
            return Result(
                success=False,
                message=f"RED EMERGENCY: {reason}",
                notable=True,
            )
        elif level >= 2:  # ORANGE
            logger.warning("🟠 ORANGE EMERGENCY: %s", reason)
            if "consecutive_errors" in reason:
                self.stats["consecutive_errors"] = 0
            return Result(
                success=True,
                message=f"ORANGE EMERGENCY handled: {reason}",
                notable=True,
            )

        return Result(success=True, message=f"Emergency handled: {reason}")

    # ═══════════════════════════════════════════════════════
    # 내부 감각 기관들
    # ═══════════════════════════════════════════════════════

    async def _check_due_schedules(self) -> list:
        """schedules 테이블에서 실행 시점 도래한 잡 확인"""
        try:
            rows = self.ssot.conn.execute(
                """SELECT id, name, cron_expr, last_run, job_type, config
                   FROM schedules
                   WHERE enabled=1"""
            ).fetchall()
        except:
            return []

        now = datetime.now()
        due = []

        for row in rows:
            job = dict(row)
            if self._is_cron_due(job["cron_expr"], job["last_run"], now):
                due.append(job)

        return due

    def _is_cron_due(self, cron_expr: str, last_run: str, now: datetime) -> bool:
        """
        간단한 크론 매칭. 형식: "HH:MM" 또는 "HH:MM DOW" (DOW=0-6, 0=월)
        """
        try:
            parts = cron_expr.strip().split()
            time_part = parts[0]
            hour, minute = int(time_part.split(":")[0]), int(time_part.split(":")[1])

            # 요일 체크 (있으면)
            if len(parts) > 1:
                allowed_days = [int(d) for d in parts[1].split(",")]
                if now.weekday() not in allowed_days:
                    return False

            # 시간 체크: 현재 시각이 스케줄 시간 ±5분 이내
            scheduled_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            diff = abs((now - scheduled_time).total_seconds())
            if diff > 300:  # 5분 이상 차이
                return False

            # 이미 실행했는지 체크
            if last_run:
                try:
                    last = datetime.fromisoformat(last_run.replace("Z", "+00:00"))
                    if last.date() == now.date() and last.hour >= hour:
                        return False
                except:
                    pass

            return True
        except Exception as e:
            logger.error("🐟 Cron parse error [%s]: %s", cron_expr, e)
            return False

    async def _check_docker(self) -> list:
        """Docker 컨테이너 상태 확인"""
        try:
            result = subprocess.run(
                ["docker", "ps", "-a", "--format", "{{.Names}}|{{.Status}}"],
                capture_output=True, text=True, timeout=10
            )
            down = []
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split("|")
                if len(parts) == 2:
                    name, status = parts
                    if "Exited" in status or "Dead" in status:
                        down.append(name)
            return down
        except Exception as e:
            logger.error("🐟 Docker check failed: %s", e)
            return []

    async def _check_disk(self) -> float:
        """디스크 사용량 % 반환"""
        try:
            result = subprocess.run(
                ["df", "-h", "/"],
                capture_output=True, text=True, timeout=5
            )
            lines = result.stdout.strip().split("\n")
            if len(lines) >= 2:
                parts = lines[1].split()
                for p in parts:
                    if p.endswith("%"):
                        return float(p.replace("%", ""))
            return 0.0
        except:
            return 0.0

    async def _check_memory(self) -> float:
        """메모리 사용량 % 반환"""
        try:
            with open("/proc/meminfo") as f:
                lines = f.readlines()
            total = available = 0
            for line in lines:
                if line.startswith("MemTotal:"):
                    total = int(line.split()[1])
                elif line.startswith("MemAvailable:"):
                    available = int(line.split()[1])
            if total > 0:
                return round((1 - available / total) * 100, 1)
            return 0.0
        except:
            return 0.0

    async def _check_api_quotas(self) -> list:
        """API 쿼터 경고 확인"""
        warnings = []

        try:
            # traces 테이블에서 오늘 사용량 확인
            rows = self.ssot.conn.execute(
                """SELECT provider, COUNT(*) as cnt, SUM(input_tokens + output_tokens) as tokens
                   FROM traces
                   WHERE created_at > date('now')
                   GROUP BY provider"""
            ).fetchall()

            for row in rows:
                provider = row[0]
                count = row[1]
                tokens = row[2] or 0

                # Groq: 일 14,400 요청 제한
                if provider == "groq" and count > 12000:
                    warnings.append(f"Groq 쿼터 {count}/14400 ({count*100//14400}%)")

                # Cerebras: 일 1000 요청 제한
                if provider == "cerebras" and count > 800:
                    warnings.append(f"Cerebras 쿼터 {count}/1000 ({count*100//1000}%)")

        except Exception as e:
            logger.error("🐟 API quota check failed: %s", e)

        return warnings

    # ═══════════════════════════════════════════════════════
    # 자가 치유
    # ═══════════════════════════════════════════════════════

    async def _act_self_heal(self, data: dict) -> Result:
        """MAPE-K 패턴 기반 자가 치유"""
        target = data["target"]
        self.stats["total_heals"] += 1

        if target == "docker":
            container = data["container"]
            logger.warning("🐟 Self-healing: restarting %s", container)

            # 과거 복구 이력 확인
            past_heals = self.ssot.conn.execute(
                """SELECT COUNT(*) FROM action_log
                   WHERE action_type='self_heal' AND data LIKE ?
                   AND timestamp > datetime('now', '-1 hour')""",
                (f'%{container}%',)
            ).fetchone()[0]

            if past_heals >= 3:
                return Result(
                    success=False,
                    message=f"{container} 1시간 내 3번 재시작 실패. 수동 확인 필요.",
                    notable=True,
                )

            try:
                result = subprocess.run(
                    ["docker", "restart", container],
                    capture_output=True, text=True, timeout=30
                )
                success = result.returncode == 0
                return Result(
                    success=success,
                    message=f"docker restart {container}: {'성공' if success else result.stderr}",
                    notable=True,
                )
            except Exception as e:
                return Result(success=False, message=str(e), notable=True)

        elif target == "disk":
            logger.warning("🐟 Self-healing: disk cleanup (%.1f%%)", data["usage"])
            try:
                subprocess.run(
                    ["docker", "system", "prune", "-f"],
                    capture_output=True, timeout=60
                )
                # PM2 로그 정리
                subprocess.run(
                    ["pm2", "flush"],
                    capture_output=True, timeout=30
                )
                new_usage = await self._check_disk()
                return Result(
                    success=new_usage < data["usage"],
                    message=f"디스크 정리: {data['usage']}% → {new_usage}%",
                    notable=True,
                )
            except Exception as e:
                return Result(success=False, message=str(e), notable=True)

        elif target == "memory":
            logger.warning("🐟 Self-healing: memory pressure (%.1f%%)", data["usage"])
            return Result(
                success=False,
                message=f"메모리 {data['usage']}% — 수동 확인 필요",
                notable=True,
            )

        return Result(success=False, message=f"Unknown heal target: {target}")

    # ═══════════════════════════════════════════════════════
    # 자율적 사고 (LLM 호출 — 하루 5-10회)
    # ═══════════════════════════════════════════════════════

    async def _think_what_next(self, world: WorldState) -> Optional[str]:
        """
        30분 이상 idle일 때 LLM에게 "뭐 할까?" 물어봄.
        """
        if not self.router:
            return None

        try:
            # 최근 행동 이력
            recent_actions = self.ssot.conn.execute(
                """SELECT action_type, summary, success
                   FROM action_log
                   ORDER BY timestamp DESC LIMIT 10"""
            ).fetchall()

            recent_str = "\n".join(
                f"- {'✅' if a[2] else '❌'} {a[1]}" for a in recent_actions
            ) if recent_actions else "No recent actions"

            # 블로그 상태
            blog_stats = self.ssot.conn.execute(
                """SELECT COUNT(*) FROM signals
                   WHERE kind='blog_published'
                   AND created_at > date('now', '-7 days')"""
            ).fetchone()[0]

            prompt = f"""You are REZE, an autonomous AI agent managing SaaS products and blogs.

Current time: {datetime.now().strftime('%Y-%m-%d %H:%M')}
Idle for: {world.idle_minutes} minutes
Blogs published this week: {blog_stats}
Recent actions:
{recent_str}

What should you do next? Pick ONE from:
1. write_blog - Write a blog post for AI Tools Lab
2. check_analytics - Analyze blog traffic patterns
3. optimize_content - Update underperforming content
4. competitor_check - Check competitor blogs for new content
5. rest - Nothing useful to do right now

Respond with just the action name and a brief reason. Example: "write_blog: AI Tools Lab hasn't had a news article in 3 days"
If nothing useful, say "rest"."""

            response = await self.router.call("reasoning", [{"role": "user", "content": prompt}])
            text = response.text.strip() if hasattr(response, 'text') else str(response).strip()

            if text.startswith("rest"):
                return None

            return text

        except Exception as e:
            logger.error("🐟 Think failed: %s", e)
            return None

    # ═══════════════════════════════════════════════════════
    # 상태 조회 (Discord /status 명령어용)
    # ═══════════════════════════════════════════════════════

    def get_status(self) -> dict:
        """현재 물고기 상태 반환."""
        try:
            uptime = (datetime.now() - datetime.fromisoformat(self.stats["started_at"])).total_seconds() / 3600
        except:
            uptime = 0

        return {
            "alive": self.alive,
            "heartbeats": self.heartbeat_count,
            "uptime_hours": round(uptime, 1),
            "total_actions": self.stats["total_actions"],
            "total_heals": self.stats["total_heals"],
            "idle_minutes": int((time.time() - self.last_action_time) / 60),
            "last_heartbeat": datetime.now().isoformat(),
        }

    def stop(self):
        """물고기 중지"""
        self.alive = False
        logger.info("🐟 Fish stopping...")
