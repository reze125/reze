"""
Phase 5 Wave 3: PREDATOR MultiHeart
REZE v6.0 SOVEREIGN - 4개 심장 동시 가동

- alpha: 30초 — Fish 본능 (L0-L6) [Fish가 담당]
- beta:  5분  — RSS 흡수 + 소화
- gamma: 10분 — 시뮬레이션
- delta: 1시간 — 학습 + 적용 + 검증

alpha는 Fish 메인 루프가 담당하므로 여기서는 beta/gamma/delta만 관리.
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any

logger = logging.getLogger("reze.predator.multiheart")

CATEGORIES_ROTATION = ["hunt", "crisis", "growth", "evolution", "survival", "independence"]


class MultiHeart:
    """REZE의 다중 심장 시스템."""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or str(
            Path.home() / "reze-agent" / "reze_data" / "ssot.sqlite"
        )
        self._running = False
        self._tasks = {}
        self._stats = {
            "beta_runs": 0,
            "gamma_runs": 0,
            "delta_runs": 0,
            "errors": 0,
            "started_at": None
        }

    async def start(self):
        """3개 심장 시작 (alpha는 Fish가 담당)."""
        if self._running:
            logger.warning("MultiHeart already running")
            return

        self._running = True
        self._stats["started_at"] = datetime.now(timezone.utc).isoformat()
        logger.info("💓 MultiHeart starting: beta(5m) + gamma(10m) + delta(1h)")

        self._tasks = {
            "beta": asyncio.create_task(self._beta_heart()),
            "gamma": asyncio.create_task(self._gamma_heart()),
            "delta": asyncio.create_task(self._delta_heart()),
        }

        for name, task in self._tasks.items():
            task.add_done_callback(lambda t, n=name: self._on_heart_stop(n, t))

    async def stop(self):
        """모든 심장 정지."""
        self._running = False
        for name, task in self._tasks.items():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        logger.info("💔 MultiHeart stopped")

    def _on_heart_stop(self, name: str, task):
        """심장 정지 시 재시작."""
        if not self._running:
            return
        try:
            exc = task.exception()
            if exc:
                logger.error(f"💔 {name} heart crashed: {exc}")
                self._stats["errors"] += 1
                # 자동 재시작
                if name == "beta":
                    self._tasks["beta"] = asyncio.create_task(self._beta_heart())
                elif name == "gamma":
                    self._tasks["gamma"] = asyncio.create_task(self._gamma_heart())
                elif name == "delta":
                    self._tasks["delta"] = asyncio.create_task(self._delta_heart())
                logger.info(f"💓 {name} heart restarted")
        except asyncio.CancelledError:
            pass

    async def _beta_heart(self):
        """5분 심장 — RSS 흡수 + 소화."""
        from .absorber import RSSAbsorber
        from .digester import ExperienceDigester

        while self._running:
            try:
                start = time.time()

                # RSS 흡수
                absorber = RSSAbsorber(db_path=self.db_path)
                absorb_result = await absorber.run_absorb_cycle(max_sources=3)

                # 소화
                digester = ExperienceDigester(db_path=self.db_path)
                digest_result = await digester.run_digest_cycle(max_items=5)

                self._stats["beta_runs"] += 1
                elapsed = time.time() - start

                new_items = absorb_result.total_new
                digested = digest_result.items_digested

                if new_items > 0 or digested > 0:
                    logger.info(
                        f"💓β [{self._stats['beta_runs']}] "
                        f"+{new_items} absorbed, {digested} digested ({elapsed:.1f}s)"
                    )

            except Exception as e:
                logger.error(f"💔β error: {e}")
                self._stats["errors"] += 1

            await asyncio.sleep(300)  # 5분

    async def _gamma_heart(self):
        """10분 심장 — 시뮬레이션."""
        from .simulator import ArenaBattle, ScenarioGenerator

        cat_index = 0

        while self._running:
            try:
                start = time.time()
                category = CATEGORIES_ROTATION[cat_index % len(CATEGORIES_ROTATION)]
                cat_index += 1

                battle = ArenaBattle(self.db_path)
                generator = ScenarioGenerator(self.db_path)
                scenarios = await generator.generate(category, count=2, depth="shallow")

                wins = 0
                for s in scenarios:
                    result = await battle.run_battle(s)
                    if result.get("winner"):
                        wins += 1

                self._stats["gamma_runs"] += 1
                elapsed = time.time() - start

                logger.info(
                    f"💓γ [{self._stats['gamma_runs']}] "
                    f"{category}: {len(scenarios)} scenarios, {wins} decisive ({elapsed:.1f}s)"
                )

            except Exception as e:
                logger.error(f"💔γ error: {e}")
                self._stats["errors"] += 1

            await asyncio.sleep(600)  # 10분

    async def _delta_heart(self):
        """1시간 심장 — 학습 + 적용 + 검증."""
        from .learner import ExperienceLearner
        from .applier import StrategyApplier
        from .verifier import StrategyVerifier

        while self._running:
            try:
                start = time.time()

                # 학습
                learner = ExperienceLearner(db_path=self.db_path)
                learn_result = await learner.learn_batch()

                # 적용
                applier = StrategyApplier(db_path=self.db_path)
                apply_result = await applier.apply_batch()

                # 검증
                verifier = StrategyVerifier(db_path=self.db_path)
                verify_result = await verifier.verify_batch()

                self._stats["delta_runs"] += 1
                elapsed = time.time() - start

                new_strats = learn_result.get("new_strategies", 0)
                applied = len(apply_result.get("applied", []))
                verified = verify_result.get("verified", 0)

                logger.info(
                    f"💓δ [{self._stats['delta_runs']}] "
                    f"Learn:{new_strats} Apply:{applied} Verify:{verified} ({elapsed:.1f}s)"
                )

            except Exception as e:
                logger.error(f"💔δ error: {e}")
                self._stats["errors"] += 1

            await asyncio.sleep(3600)  # 1시간

    async def run_once(self) -> Dict[str, Any]:
        """모든 심장 1회 실행 (테스트용)."""
        results = {}

        # Beta
        try:
            from .absorber import RSSAbsorber
            from .digester import ExperienceDigester

            absorber = RSSAbsorber(db_path=self.db_path)
            absorb_result = await absorber.run_absorb_cycle(max_sources=2)
            digester = ExperienceDigester(db_path=self.db_path)
            digest_result = await digester.run_digest_cycle(max_items=3)

            results["beta"] = {
                "absorbed": absorb_result.total_new,
                "digested": digest_result.items_digested
            }
        except Exception as e:
            results["beta"] = {"error": str(e)}

        # Gamma
        try:
            from .simulator import ArenaBattle, ScenarioGenerator

            generator = ScenarioGenerator(self.db_path)
            scenarios = await generator.generate("hunt", count=2)
            battle = ArenaBattle(self.db_path)

            wins = 0
            for s in scenarios:
                r = await battle.run_battle(s)
                if r.get("winner"):
                    wins += 1

            results["gamma"] = {
                "scenarios": len(scenarios),
                "wins": wins
            }
        except Exception as e:
            results["gamma"] = {"error": str(e)}

        # Delta
        try:
            from .learner import ExperienceLearner
            from .applier import StrategyApplier
            from .verifier import StrategyVerifier

            learner = ExperienceLearner(db_path=self.db_path)
            learn_result = await learner.learn_batch()

            applier = StrategyApplier(db_path=self.db_path)
            apply_result = await applier.apply_batch()

            verifier = StrategyVerifier(db_path=self.db_path)
            verify_result = await verifier.verify_batch()

            results["delta"] = {
                "learned": learn_result.get("new_strategies", 0),
                "applied": len(apply_result.get("applied", [])),
                "verified": verify_result.get("verified", 0)
            }
        except Exception as e:
            results["delta"] = {"error": str(e)}

        return results

    def get_stats(self) -> Dict[str, Any]:
        """심장 상태."""
        return {
            **self._stats,
            "running": self._running,
            "hearts": {
                name: not task.done() if task else False
                for name, task in self._tasks.items()
            }
        }
