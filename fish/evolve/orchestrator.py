"""
Evolution Orchestrator — REZE v6.0 SOVEREIGN
진화 모듈 오케스트레이션

모든 진화 모듈의 실행을 조율하고,
에너지 기반 스케줄링과 쿨다운을 관리합니다.

가동 조건: 즉시 (항상 활성)
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Callable
from enum import Enum

logger = logging.getLogger("reze.evolve.orchestrator")


class ModuleState(Enum):
    """모듈 상태"""
    DORMANT = "dormant"     # 휴면 (조건 미충족)
    READY = "ready"         # 실행 가능
    RUNNING = "running"     # 실행 중
    COOLDOWN = "cooldown"   # 쿨다운 중
    ERROR = "error"         # 오류


@dataclass
class ModuleConfig:
    """모듈 설정"""
    name: str
    module_class: Any
    energy_cost: int = 10           # 실행 에너지 비용
    cooldown_minutes: int = 60      # 쿨다운 시간 (분)
    priority: int = 5               # 우선순위 (1-10, 높을수록 먼저)
    max_daily_runs: int = 10        # 일일 최대 실행 횟수
    enabled: bool = True


@dataclass
class ModuleStatus:
    """모듈 상태 정보"""
    name: str
    state: ModuleState
    last_run: Optional[str] = None
    next_available: Optional[str] = None
    daily_runs: int = 0
    total_runs: int = 0
    avg_duration_sec: float = 0
    last_error: Optional[str] = None


class EvolutionOrchestrator:
    """
    진화 모듈 오케스트레이터.
    에너지 관리 + 스케줄링 + 실행 조율.
    """

    # 기본 에너지 설정
    MAX_ENERGY = 100
    ENERGY_REGEN_PER_HOUR = 20

    def __init__(self, ssot, llm_router=None, tavily_client=None):
        """
        Args:
            ssot: SSOT 인스턴스
            llm_router: LLM 라우터
            tavily_client: Tavily 클라이언트
        """
        self.ssot = ssot
        self.conn = ssot.conn if hasattr(ssot, 'conn') else ssot
        self.llm = llm_router
        self.tavily = tavily_client

        # 모듈 인스턴스 캐시
        self._modules: Dict[str, Any] = {}
        self._configs: Dict[str, ModuleConfig] = {}
        self._statuses: Dict[str, ModuleStatus] = {}

        # 에너지
        self._current_energy = self.MAX_ENERGY
        self._last_energy_update = datetime.utcnow()

        # 인프라 컴포넌트 (나중에 주입)
        self.sandbox = None
        self.boss = None
        self.checkpoint = None

    def set_infrastructure(self, sandbox=None, boss=None, checkpoint=None):
        """인프라 컴포넌트 설정"""
        self.sandbox = sandbox
        self.boss = boss
        self.checkpoint = checkpoint

    def register_module(self, config: ModuleConfig):
        """
        모듈 등록.

        Args:
            config: 모듈 설정
        """
        self._configs[config.name] = config

        # 상태 초기화
        self._statuses[config.name] = ModuleStatus(
            name=config.name,
            state=ModuleState.DORMANT
        )

        logger.info("Registered evolution module: %s (energy=%d, cooldown=%dm)",
                    config.name, config.energy_cost, config.cooldown_minutes)

    def register_all_modules(self):
        """모든 진화 모듈 등록"""
        # Phase 3: Core Evolution
        from fish.evolve.metacognition import MetacognitiveMonitor
        from fish.evolve.lifelong import LifelongLearning
        from fish.evolve.self_play import SelfPlay
        from fish.evolve.curiosity import CuriosityEngine
        from fish.evolve.world_model import WorldModel
        from fish.evolve.sub_agent import SubAgentSpawner
        from fish.evolve.self_code import SelfCodeEvolution
        from fish.evolve.tool_discovery import ToolDiscovery

        # Phase 4: Advanced Evolution
        from fish.evolve.evo_coding import EvoCoding
        from fish.evolve.self_healing import SelfHealing

        modules = [
            # Phase 3 Modules
            ModuleConfig(
                name="metacognition",
                module_class=MetacognitiveMonitor,
                energy_cost=5,
                cooldown_minutes=30,
                priority=8
            ),
            ModuleConfig(
                name="lifelong",
                module_class=LifelongLearning,
                energy_cost=5,
                cooldown_minutes=60,
                priority=7
            ),
            ModuleConfig(
                name="self_play",
                module_class=SelfPlay,
                energy_cost=15,
                cooldown_minutes=120,
                priority=6
            ),
            ModuleConfig(
                name="curiosity",
                module_class=CuriosityEngine,
                energy_cost=10,
                cooldown_minutes=60,
                priority=5
            ),
            ModuleConfig(
                name="world_model",
                module_class=WorldModel,
                energy_cost=10,
                cooldown_minutes=60,
                priority=5
            ),
            ModuleConfig(
                name="sub_agent",
                module_class=SubAgentSpawner,
                energy_cost=20,
                cooldown_minutes=30,
                priority=4
            ),
            ModuleConfig(
                name="self_code",
                module_class=SelfCodeEvolution,
                energy_cost=30,
                cooldown_minutes=240,
                priority=3
            ),
            ModuleConfig(
                name="tool_discovery",
                module_class=ToolDiscovery,
                energy_cost=25,
                cooldown_minutes=180,
                priority=4
            ),

            # Phase 4 Modules
            ModuleConfig(
                name="evo_coding",
                module_class=EvoCoding,
                energy_cost=20,
                cooldown_minutes=180,
                priority=3
            ),
            ModuleConfig(
                name="self_healing",
                module_class=SelfHealing,
                energy_cost=5,
                cooldown_minutes=15,
                priority=9  # High priority for error recovery
            ),
        ]

        for config in modules:
            self.register_module(config)

    def _get_module_instance(self, name: str) -> Any:
        """모듈 인스턴스 가져오기 (lazy initialization)"""
        if name not in self._modules:
            config = self._configs.get(name)
            if not config:
                return None

            # 모듈별 초기화
            if name == "metacognition":
                # MetacognitiveMonitor only takes ssot
                self._modules[name] = config.module_class(self.ssot)
            elif name == "self_code":
                self._modules[name] = config.module_class(
                    self.ssot,
                    llm_router=self.llm,
                    sandbox_runner=self.sandbox,
                    boss_approval=self.boss,
                    checkpoint_mgr=self.checkpoint
                )
            elif name == "tool_discovery":
                self._modules[name] = config.module_class(
                    self.ssot,
                    llm_router=self.llm,
                    tavily_client=self.tavily,
                    sandbox_runner=self.sandbox
                )
            elif name == "sub_agent":
                self._modules[name] = config.module_class(
                    self.ssot,
                    llm_router=self.llm,
                    tavily_client=self.tavily
                )
            elif name == "curiosity":
                self._modules[name] = config.module_class(
                    self.ssot,
                    llm_router=self.llm,
                    tavily_client=self.tavily
                )
            else:
                # lifelong, self_play, world_model, evo_coding, self_healing
                self._modules[name] = config.module_class(
                    self.ssot,
                    llm_router=self.llm
                )

        return self._modules.get(name)

    def _update_energy(self):
        """에너지 재생"""
        now = datetime.utcnow()
        elapsed_hours = (now - self._last_energy_update).total_seconds() / 3600

        regen = int(elapsed_hours * self.ENERGY_REGEN_PER_HOUR)
        if regen > 0:
            self._current_energy = min(self.MAX_ENERGY, self._current_energy + regen)
            self._last_energy_update = now

    def get_energy(self) -> int:
        """현재 에너지 반환"""
        self._update_energy()
        return self._current_energy

    def consume_energy(self, amount: int) -> bool:
        """에너지 소비"""
        self._update_energy()
        if self._current_energy >= amount:
            self._current_energy -= amount
            return True
        return False

    async def check_module_state(self, name: str) -> ModuleState:
        """
        모듈 상태 확인.

        Args:
            name: 모듈 이름

        Returns:
            ModuleState
        """
        config = self._configs.get(name)
        status = self._statuses.get(name)

        if not config or not status:
            return ModuleState.ERROR

        if not config.enabled:
            return ModuleState.DORMANT

        # 쿨다운 확인
        if status.last_run:
            last_run_dt = datetime.fromisoformat(status.last_run)
            cooldown_end = last_run_dt + timedelta(minutes=config.cooldown_minutes)

            if datetime.utcnow() < cooldown_end:
                status.state = ModuleState.COOLDOWN
                status.next_available = cooldown_end.isoformat()
                return ModuleState.COOLDOWN

        # 일일 제한 확인
        if status.daily_runs >= config.max_daily_runs:
            return ModuleState.COOLDOWN

        # 에너지 확인
        if self.get_energy() < config.energy_cost:
            return ModuleState.DORMANT

        # 활성화 조건 확인
        module = self._get_module_instance(name)
        if module and hasattr(module, 'is_active'):
            try:
                is_active = await module.is_active()
                if not is_active:
                    status.state = ModuleState.DORMANT
                    return ModuleState.DORMANT
            except Exception as e:
                logger.error("Module %s is_active check failed: %s", name, e)
                status.last_error = str(e)
                return ModuleState.ERROR

        status.state = ModuleState.READY
        return ModuleState.READY

    async def get_runnable_modules(self) -> List[str]:
        """실행 가능한 모듈 목록 (우선순위 순)"""
        runnable = []

        for name in self._configs:
            state = await self.check_module_state(name)
            if state == ModuleState.READY:
                runnable.append(name)

        # 우선순위 순 정렬
        runnable.sort(key=lambda n: self._configs[n].priority, reverse=True)

        return runnable

    async def run_module(self, name: str, **kwargs) -> Dict:
        """
        모듈 실행.

        Args:
            name: 모듈 이름
            **kwargs: 모듈별 추가 인자

        Returns:
            실행 결과
        """
        config = self._configs.get(name)
        status = self._statuses.get(name)

        if not config or not status:
            return {"error": f"Module not found: {name}"}

        # 상태 확인
        state = await self.check_module_state(name)
        if state != ModuleState.READY:
            return {"error": f"Module not ready: {state.value}"}

        # 에너지 소비
        if not self.consume_energy(config.energy_cost):
            return {"error": "Insufficient energy"}

        # 모듈 실행
        module = self._get_module_instance(name)
        if not module:
            return {"error": "Failed to initialize module"}

        status.state = ModuleState.RUNNING
        start_time = datetime.utcnow()

        try:
            # 모듈별 실행 메서드 호출
            if name == "metacognition":
                result = await module.compute_calibration(kwargs.get("domain", "general"))
            elif name == "lifelong":
                if kwargs.get("action") == "consolidate":
                    result = await module.consolidate()
                elif kwargs.get("action") == "recall":
                    result = await module.recall(kwargs.get("situation", ""), kwargs.get("context"))
                else:
                    result = {"advice": await module.get_advice(kwargs.get("situation", ""))}
            elif name == "self_play":
                result = await module.run_self_play_cycle()
            elif name == "curiosity":
                result = {"suggestions": await module.suggest_exploration()}
            elif name == "world_model":
                if kwargs.get("prediction"):
                    result = await module.predict_hunt_outcome(**kwargs["prediction"])
                    result = {"prediction": result.__dict__}
                else:
                    result = {"accuracy": module.get_model_accuracy()}
            elif name == "sub_agent":
                result = await module.run_task(
                    kwargs.get("task", ""),
                    kwargs.get("context")
                )
            elif name == "self_code":
                if kwargs.get("action") == "analyze":
                    result = await module.analyze_file(kwargs.get("filepath", ""))
                elif kwargs.get("action") == "apply_patch":
                    patch_id = kwargs.get("patch_id")
                    patches = module.get_pending_patches()
                    patch = next((p for p in patches if p["patch_id"] == patch_id), None)
                    if patch:
                        # 실제 patch 객체 필요 - 여기서는 단순화
                        result = {"status": "patch_application_requires_patch_object"}
                    else:
                        result = {"error": "Patch not found"}
                else:
                    result = {"pending_patches": module.get_pending_patches()}
            elif name == "tool_discovery":
                result = await module.run_discovery_cycle()
            elif name == "evo_coding":
                # Evolutionary coding
                domain = kwargs.get("domain", "hunt_prompt")
                generations = kwargs.get("generations", 5)
                result = await module.run_evolution(domain, generations)
            elif name == "self_healing":
                # Self-healing stats or heal specific error
                if kwargs.get("action") == "heal":
                    error = kwargs.get("error")
                    if error:
                        action = await module.heal(
                            error,
                            kwargs.get("module", "unknown"),
                            kwargs.get("retry_fn"),
                            kwargs.get("context")
                        )
                        result = {
                            "action_id": action.action_id,
                            "strategy": action.strategy.value,
                            "success": action.success,
                            "result": action.result
                        }
                    else:
                        result = {"error": "No error provided for healing"}
                else:
                    result = {
                        "stats": module.get_healing_stats(),
                        "patterns": module.get_error_patterns(min_count=2)
                    }
            else:
                result = {"error": f"No run method for module: {name}"}

            duration = (datetime.utcnow() - start_time).total_seconds()

            # 상태 업데이트
            status.last_run = datetime.utcnow().isoformat()
            status.daily_runs += 1
            status.total_runs += 1
            status.avg_duration_sec = (
                (status.avg_duration_sec * (status.total_runs - 1) + duration)
                / status.total_runs
            )
            status.state = ModuleState.COOLDOWN
            status.next_available = (
                datetime.utcnow() + timedelta(minutes=config.cooldown_minutes)
            ).isoformat()

            # evolution_log에 기록
            self._log_execution(name, "success", result, duration)

            return {
                "module": name,
                "success": True,
                "result": result,
                "duration_sec": round(duration, 2),
                "energy_remaining": self.get_energy()
            }

        except Exception as e:
            duration = (datetime.utcnow() - start_time).total_seconds()
            status.state = ModuleState.ERROR
            status.last_error = str(e)

            logger.error("Module %s execution failed: %s", name, e)
            self._log_execution(name, "failed", {"error": str(e)}, duration)

            return {
                "module": name,
                "success": False,
                "error": str(e),
                "duration_sec": round(duration, 2)
            }

    def _log_execution(self, module: str, outcome: str, details: Dict, duration: float):
        """실행 로그 기록"""
        try:
            self.conn.execute("""
                INSERT INTO evolution_log
                (module, trigger_source, outcome, details, execution_time_sec, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                module,
                "orchestrator",
                outcome,
                json.dumps(details, default=str)[:2000],
                duration,
                datetime.utcnow().isoformat()
            ))
            self.conn.commit()
        except Exception as e:
            logger.error("Failed to log execution: %s", e)

    async def run_evolution_cycle(self, max_modules: int = 3) -> Dict:
        """
        진화 사이클 실행.
        실행 가능한 모듈을 우선순위 순으로 실행.

        Args:
            max_modules: 최대 실행 모듈 수

        Returns:
            사이클 결과
        """
        result = {
            "cycle_start": datetime.utcnow().isoformat(),
            "energy_start": self.get_energy(),
            "modules_run": [],
            "errors": []
        }

        runnable = await self.get_runnable_modules()

        for module_name in runnable[:max_modules]:
            module_result = await self.run_module(module_name)

            if module_result.get("success"):
                result["modules_run"].append({
                    "name": module_name,
                    "duration": module_result.get("duration_sec"),
                    "result_summary": str(module_result.get("result", {}))[:200]
                })
            else:
                result["errors"].append({
                    "module": module_name,
                    "error": module_result.get("error")
                })

            # 에너지 부족하면 중단
            if self.get_energy() < 10:
                break

        result["cycle_end"] = datetime.utcnow().isoformat()
        result["energy_end"] = self.get_energy()

        return result

    def get_all_statuses(self) -> Dict[str, Dict]:
        """모든 모듈 상태 반환"""
        return {
            name: {
                "state": status.state.value,
                "last_run": status.last_run,
                "next_available": status.next_available,
                "daily_runs": status.daily_runs,
                "total_runs": status.total_runs,
                "avg_duration_sec": round(status.avg_duration_sec, 2),
                "last_error": status.last_error,
                "config": {
                    "energy_cost": self._configs[name].energy_cost,
                    "cooldown_minutes": self._configs[name].cooldown_minutes,
                    "priority": self._configs[name].priority,
                    "enabled": self._configs[name].enabled
                }
            }
            for name, status in self._statuses.items()
        }

    def get_dashboard(self) -> Dict:
        """진화 대시보드 데이터"""
        return {
            "energy": {
                "current": self.get_energy(),
                "max": self.MAX_ENERGY,
                "regen_per_hour": self.ENERGY_REGEN_PER_HOUR
            },
            "modules": self.get_all_statuses(),
            "recent_executions": self._get_recent_executions(10),
            "timestamp": datetime.utcnow().isoformat()
        }

    def _get_recent_executions(self, limit: int = 10) -> List[Dict]:
        """최근 실행 내역"""
        try:
            rows = self.conn.execute("""
                SELECT module, trigger_source, outcome, execution_time_sec, created_at
                FROM evolution_log
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,)).fetchall()

            return [
                {
                    "module": r[0],
                    "trigger": r[1],
                    "outcome": r[2],
                    "duration_sec": r[3],
                    "created_at": r[4]
                }
                for r in rows
            ]
        except:
            return []

    def reset_daily_counts(self):
        """일일 실행 횟수 초기화 (자정에 호출)"""
        for status in self._statuses.values():
            status.daily_runs = 0

    def enable_module(self, name: str):
        """모듈 활성화"""
        if name in self._configs:
            self._configs[name].enabled = True

    def disable_module(self, name: str):
        """모듈 비활성화"""
        if name in self._configs:
            self._configs[name].enabled = False


# 싱글톤 인스턴스 (fish.py에서 사용)
_orchestrator_instance: Optional[EvolutionOrchestrator] = None


def get_orchestrator(ssot=None, llm_router=None, tavily_client=None) -> EvolutionOrchestrator:
    """오케스트레이터 싱글톤 인스턴스 반환"""
    global _orchestrator_instance

    if _orchestrator_instance is None:
        if ssot is None:
            raise ValueError("SSOT required for first initialization")

        _orchestrator_instance = EvolutionOrchestrator(
            ssot,
            llm_router=llm_router,
            tavily_client=tavily_client
        )
        _orchestrator_instance.register_all_modules()

    return _orchestrator_instance
