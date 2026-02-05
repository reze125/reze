"""REZE Fish — EVENT HORIZON v3.0

물고기는 크론잡으로 숨 쉬지 않는다.
감각이 열려있고, 먹이가 보이면 먹고, 위험이 오면 피한다.

6+1 레벨 본능 시스템:
  L★ Emergency → L0 Survival → L1 Duty → L2 Hunt →
  L3 Devour → L4 Territory → L5 Evolve → L6 Idle

Accretion Disk: 6개 소스에서 콘텐츠 기회 수집
Gravity Well: Pillar-Cluster SEO 구조
"""

from fish.fish import Fish, WorldState, Action, Result, InstinctLevel
from fish.hunt import Hunter, HuntStrategy, Source, Prey, HuntResult
from fish.accretion import AccretionDisk, ContentSignal
from fish.gravity import GravityWell, Pillar, Cluster, InternalLink
from fish.singularity import SingularityProtocol, Crisis, CrisisLevel, CrisisResponse
from fish.hawking import HawkingRadiation, DeadContent, RecycleAction, DeathReason, RecycleResult
from fish.pipeline import ContentPipeline, ContentDraft, ContentStatus, PublishResult
from fish.revenue import RevenueTracker, RevenueType, SourceType, ContentROI
from fish.experiment import ExperimentEngine, Experiment, ExperimentType, ExperimentResult

__all__ = [
    # Core
    "Fish", "WorldState", "Action", "Result", "InstinctLevel",
    # Hunt
    "Hunter", "HuntStrategy", "Source", "Prey", "HuntResult",
    # Accretion Disk
    "AccretionDisk", "ContentSignal",
    # Gravity Well
    "GravityWell", "Pillar", "Cluster", "InternalLink",
    # Singularity Protocol
    "SingularityProtocol", "Crisis", "CrisisLevel", "CrisisResponse",
    # Hawking Radiation
    "HawkingRadiation", "DeadContent", "RecycleAction", "DeathReason", "RecycleResult",
    # Content Pipeline
    "ContentPipeline", "ContentDraft", "ContentStatus", "PublishResult",
    # Revenue Tracking
    "RevenueTracker", "RevenueType", "SourceType", "ContentROI",
    # A/B Experiments
    "ExperimentEngine", "Experiment", "ExperimentType", "ExperimentResult",
]
