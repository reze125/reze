"""
🐟 REZE Fish 엔트리포인트
pm2 start fish/main.py --name reze-fish --interpreter python3
"""

import asyncio
import logging
import sys
import os
import signal

# REZE 루트를 path에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fish.fish import Fish

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
    handlers=[
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger("reze.fish.main")

# 전역 fish 인스턴스 (시그널 핸들러용)
fish_instance = None


def handle_shutdown(signum, frame):
    """Graceful shutdown"""
    logger.info("🐟 Shutdown signal received")
    if fish_instance:
        fish_instance.stop()


async def main():
    global fish_instance

    logger.info("🐟 Starting REZE Fish v1.0...")

    # 시그널 핸들러 등록
    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    # 1. SSOT 연결
    try:
        from ssot import SSOT
        ssot = SSOT()
        logger.info("🐟 SSOT connected: %s", ssot.db_path)
    except Exception as e:
        logger.error("🐟 Failed to connect SSOT: %s", e)
        return

    # 2. 스키마 확인/생성
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    if os.path.exists(schema_path):
        try:
            with open(schema_path) as f:
                ssot.conn.executescript(f.read())
            ssot.conn.commit()
            logger.info("🐟 Schema verified")
        except Exception as e:
            logger.warning("🐟 Schema setup warning: %s", e)

    # 3. ModelRouter 연결
    router = None
    try:
        from reze_core import ModelRouter
        router = ModelRouter(ssot)
        logger.info("🐟 ModelRouter connected")
    except Exception as e:
        logger.warning("🐟 ModelRouter not available: %s", e)

    # 4. REZECore 연결 (선택적)
    core = None
    try:
        from reze_core import REZECore
        from reze_permissions import PermissionSystem
        from reze_tools import ToolExecutor
        from skills_manager import SkillsManager

        permissions = PermissionSystem()
        tools = ToolExecutor(ssot, permissions)
        skills = SkillsManager()

        # CircuitBreaker는 선택적
        try:
            from reze_core import CircuitBreaker
            circuit_breaker = CircuitBreaker(ssot)
        except:
            circuit_breaker = None

        core = REZECore(ssot, tools, permissions, router, skills, circuit_breaker)
        logger.info("🐟 REZECore connected")
    except Exception as e:
        logger.warning("🐟 REZECore not available (limited mode): %s", e)

    # 5. Discord 알림 함수
    async def discord_notify(message: str):
        """Discord 채널에 메시지 전송."""
        try:
            # discord_notify 모듈 사용
            from discord_notify import notify_chat
            await notify_chat(message)
            logger.info("🐟 Discord notified: %s", message[:50])
        except Exception as e:
            # Fallback: signals 테이블에 저장
            logger.warning("🐟 Discord notify fallback: %s", e)
            try:
                import json
                ssot.save_signal("fish_discord_outgoing", json.dumps({
                    "message": message,
                }))
            except:
                pass

    # 6. 물고기 생성 및 시작
    fish_instance = Fish(
        ssot=ssot,
        router=router,
        core=core,
        discord_notifier=discord_notify,
    )

    logger.info("🐟 Fish is born. Beginning life cycle...")
    logger.info("🐟 Core: %s | Router: %s", "✅" if core else "❌", "✅" if router else "❌")

    try:
        await fish_instance.live()
    except asyncio.CancelledError:
        logger.info("🐟 Fish life cancelled")
    finally:
        logger.info("🐟 Fish stopped. Total heartbeats: %d", fish_instance.heartbeat_count)
        ssot.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🐟 Keyboard interrupt")
    except Exception as e:
        logger.error("🐟 Fatal error: %s", e, exc_info=True)
        sys.exit(1)
