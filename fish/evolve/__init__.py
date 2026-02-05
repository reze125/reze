"""
REZE v6.0 SOVEREIGN — Evolution Modules
자기 진화 모듈

Phase 3: Core Evolution
- metacognition: 의사결정 정확도 추적
- lifelong: 평생 학습 (경험 기억)
- self_play: 성공/실패 쌍 학습
- curiosity: 호기심 기반 탐색
- world_model: 예측 시뮬레이션
- sub_agent: 서브에이전트 분할 실행
- self_code: 자기 코드 진화
- tool_discovery: 도구 자동 발견

Phase 4: Advanced Evolution
- evo_coding: 진화적 코딩 (유전 알고리즘)
- self_healing: 자기 치유 (오류 자동 복구)

Orchestration
- orchestrator: 진화 모듈 오케스트레이션
- migrations: DB 스키마 마이그레이션
"""

# Migrations
from fish.evolve.migrations import MIGRATIONS, run_migrations

# Phase 3: Core Evolution Modules
from fish.evolve.metacognition import MetacognitiveMonitor
from fish.evolve.lifelong import LifelongLearning
from fish.evolve.self_play import SelfPlay
from fish.evolve.curiosity import CuriosityEngine
from fish.evolve.world_model import WorldModel, Prediction
from fish.evolve.sub_agent import SubAgentSpawner, AgentType, ExecutionMode, SubTask
from fish.evolve.self_code import SelfCodeEvolution, CodePatch
from fish.evolve.tool_discovery import ToolDiscovery, ToolCategory, DiscoveredTool

# Phase 4: Advanced Evolution Modules
from fish.evolve.evo_coding import EvoCoding, Gene, Individual, Population, GeneType
from fish.evolve.self_healing import SelfHealing, ErrorCategory, HealingStrategy, ErrorPattern, HealingAction

# Orchestration
from fish.evolve.orchestrator import (
    EvolutionOrchestrator,
    ModuleConfig,
    ModuleState,
    ModuleStatus,
    get_orchestrator
)

__all__ = [
    # Migrations
    "MIGRATIONS",
    "run_migrations",

    # Phase 3 Modules
    "MetacognitiveMonitor",
    "LifelongLearning",
    "SelfPlay",
    "CuriosityEngine",
    "WorldModel",
    "Prediction",
    "SubAgentSpawner",
    "AgentType",
    "ExecutionMode",
    "SubTask",
    "SelfCodeEvolution",
    "CodePatch",
    "ToolDiscovery",
    "ToolCategory",
    "DiscoveredTool",

    # Phase 4 Modules
    "EvoCoding",
    "Gene",
    "Individual",
    "Population",
    "GeneType",
    "SelfHealing",
    "ErrorCategory",
    "HealingStrategy",
    "ErrorPattern",
    "HealingAction",

    # Orchestration
    "EvolutionOrchestrator",
    "ModuleConfig",
    "ModuleState",
    "ModuleStatus",
    "get_orchestrator",
]
