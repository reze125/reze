"""
REZE v6.0 SOVEREIGN — Phase 5: PREDATOR EVOLUTION 완전체
포식자 진화 모듈

5단계 파이프라인:
1. 흡수 (Absorb): RSS 피드에서 콘텐츠 수집 ($0 API cost)
2. 소화 (Digest): LLM으로 인사이트 추출
3. 학습 (Learn): 패턴 발견 및 전략 생성
4. 적용 (Apply): 학습된 전략 실행
5. 검증 (Verify): 결과 평가 및 피드백 루프

+ 시뮬레이션 (ScenarioGenerator, ArenaBattle, DreamSynthesis)
+ MultiHeart (beta 5분, gamma 10분, delta 1시간)

Wave 1: 흡수 + 소화
Wave 2: 학습 + 적용 + 검증
Wave 3: 시뮬레이션 + MultiHeart
"""

# Schema and Migrations
from fish.predator.schema import (
    PREDATOR_TABLES,
    run_predator_migrations,
    verify_schema
)

# Stage 1: Absorb
from fish.predator.absorber import (
    RSSAbsorber,
    AbsorbResult,
    AbsorbCycleResult,
    DEFAULT_RSS_SOURCES
)

# Stage 2: Digest
from fish.predator.digester import (
    ExperienceDigester,
    DigestResult,
    DigestCycleResult,
    INSIGHT_TYPES
)

# Stage 3: Learn
from fish.predator.learner import (
    ExperienceLearner,
    LearnResult
)

# Stage 4: Apply
from fish.predator.applier import (
    StrategyApplier,
    ApplyResult
)

# Stage 5: Verify
from fish.predator.verifier import (
    StrategyVerifier,
    VerifyResult
)

# Wave 3: Simulation
from fish.predator.simulator import (
    ScenarioGenerator,
    ArenaBattle,
    DreamSynthesis,
    CATEGORIES,
    ADVERSARIAL_SCENARIOS
)

# Wave 3: MultiHeart
from fish.predator.multiheart import (
    MultiHeart,
    CATEGORIES_ROTATION
)

__all__ = [
    # Schema
    "PREDATOR_TABLES",
    "run_predator_migrations",
    "verify_schema",

    # Stage 1: Absorb
    "RSSAbsorber",
    "AbsorbResult",
    "AbsorbCycleResult",
    "DEFAULT_RSS_SOURCES",

    # Stage 2: Digest
    "ExperienceDigester",
    "DigestResult",
    "DigestCycleResult",
    "INSIGHT_TYPES",

    # Stage 3: Learn
    "ExperienceLearner",
    "LearnResult",

    # Stage 4: Apply
    "StrategyApplier",
    "ApplyResult",

    # Stage 5: Verify
    "StrategyVerifier",
    "VerifyResult",

    # Wave 3: Simulation
    "ScenarioGenerator",
    "ArenaBattle",
    "DreamSynthesis",
    "CATEGORIES",
    "ADVERSARIAL_SCENARIOS",

    # Wave 3: MultiHeart
    "MultiHeart",
    "CATEGORIES_ROTATION",

    # Convenience
    "run_predator_cycle",
    "run_full_predator_cycle",
]


async def run_predator_cycle(
    db_path: str = None,
    absorb: bool = True,
    digest: bool = True,
    max_absorb_sources: int = 5,
    max_digest_items: int = 10
) -> dict:
    """PREDATOR Wave 1 사이클 (흡수 → 소화)"""
    result = {}

    if absorb:
        absorber = RSSAbsorber(db_path=db_path)
        absorber.init_default_sources()
        result["absorb"] = await absorber.run_absorb_cycle(
            max_sources=max_absorb_sources
        )

    if digest:
        digester = ExperienceDigester(db_path=db_path)
        result["digest"] = await digester.run_digest_cycle(
            max_items=max_digest_items
        )

    return result


async def run_full_predator_cycle(
    db_path: str = None,
    absorb: bool = True,
    digest: bool = True,
    learn: bool = True,
    apply: bool = True,
    verify: bool = True,
    simulate: bool = False,
    dream: bool = False,
    max_absorb_sources: int = 5,
    max_digest_items: int = 10
) -> dict:
    """
    PREDATOR 전체 사이클 (흡수 → 소화 → 학습 → 적용 → 검증 + 시뮬/꿈)
    """
    import logging
    logger = logging.getLogger("reze.predator")
    result = {}

    # Stage 1: 흡수
    if absorb:
        try:
            absorber = RSSAbsorber(db_path=db_path)
            absorber.init_default_sources()
            absorb_result = await absorber.run_absorb_cycle(max_sources=max_absorb_sources)
            result["absorb"] = {
                "new": absorb_result.total_new,
                "fetched": absorb_result.total_fetched,
                "sources": absorb_result.sources_processed
            }
            logger.info(f"🦈 Absorb: {absorb_result.total_new} new items")
        except Exception as e:
            logger.error(f"Absorb error: {e}")
            result["absorb"] = {"error": str(e)}

    # Stage 2: 소화
    if digest:
        try:
            digester = ExperienceDigester(db_path=db_path)
            digest_result = await digester.run_digest_cycle(max_items=max_digest_items)
            result["digest"] = {
                "digested": digest_result.items_digested,
                "high_value": digest_result.high_value_count,
                "errors": digest_result.items_error
            }
            logger.info(f"🧠 Digest: {digest_result.items_digested} insights")
        except Exception as e:
            logger.error(f"Digest error: {e}")
            result["digest"] = {"error": str(e)}

    # Stage 3: 학습
    if learn:
        try:
            learner = ExperienceLearner(db_path=db_path)
            learn_result = await learner.learn_batch()
            result["learn"] = learn_result
            logger.info(f"📚 Learn: {learn_result.get('new_strategies', 0)} strategies")
        except Exception as e:
            logger.error(f"Learn error: {e}")
            result["learn"] = {"error": str(e)}

    # Stage 4: 적용
    if apply:
        try:
            applier = StrategyApplier(db_path=db_path)
            apply_result = await applier.apply_batch()
            result["apply"] = apply_result
            logger.info(f"⚡ Apply: {len(apply_result.get('applied', []))} applied")
        except Exception as e:
            logger.error(f"Apply error: {e}")
            result["apply"] = {"error": str(e)}

    # Stage 5: 검증
    if verify:
        try:
            verifier = StrategyVerifier(db_path=db_path)
            verify_result = await verifier.verify_batch()
            result["verify"] = verify_result
            logger.info(f"✅ Verify: {verify_result.get('verified', 0)} checked")
        except Exception as e:
            logger.error(f"Verify error: {e}")
            result["verify"] = {"error": str(e)}

    # Wave 3: 시뮬레이션
    if simulate:
        try:
            battle = ArenaBattle(db_path=db_path)
            sim_result = await battle.tournament("hunt", rounds=2)
            result["simulate"] = {
                "rounds": sim_result.get("rounds", 0),
                "winners": sim_result.get("winners", [])
            }
            logger.info(f"🎮 Simulate: {sim_result.get('rounds', 0)} rounds")
        except Exception as e:
            logger.error(f"Simulate error: {e}")
            result["simulate"] = {"error": str(e)}

    # Wave 3: 꿈
    if dream:
        try:
            dream_engine = DreamSynthesis(db_path=db_path)
            dream_result = await dream_engine.dream()
            result["dream"] = dream_result
            logger.info(f"💭 Dream: {dream_result.get('insights', 0)} insights")
        except Exception as e:
            logger.error(f"Dream error: {e}")
            result["dream"] = {"error": str(e)}

    return result
