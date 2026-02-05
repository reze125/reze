#!/usr/bin/env python3
"""
REZE MultiHeart Runner
PM2로 실행: pm2 start run_multiheart.py --name reze-multiheart --interpreter python3
"""

import asyncio
import os
import sys
import logging

# 경로 설정
sys.path.insert(0, os.path.expanduser("~/reze-agent"))
os.chdir(os.path.expanduser("~/reze-agent"))

# .env 로드
from dotenv import load_dotenv
load_dotenv()

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("reze.multiheart.runner")

from fish.predator.multiheart import MultiHeart


async def main():
    logger.info("🚀 Starting REZE MultiHeart...")

    heart = MultiHeart()
    await heart.start()

    logger.info("💓 MultiHeart running: beta(5m) + gamma(10m) + delta(1h)")

    # 상태 모니터링 루프
    try:
        while True:
            await asyncio.sleep(300)  # 5분마다 상태 출력
            stats = heart.get_stats()
            logger.info(
                f"💓 Hearts: beta={stats['beta_runs']} "
                f"gamma={stats['gamma_runs']} delta={stats['delta_runs']} "
                f"errors={stats['errors']}"
            )
    except KeyboardInterrupt:
        logger.info("🛑 Shutdown requested...")
    except Exception as e:
        logger.error(f"❌ Error: {e}")
    finally:
        await heart.stop()
        logger.info("💔 MultiHeart stopped")


if __name__ == "__main__":
    asyncio.run(main())
