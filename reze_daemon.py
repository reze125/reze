"""REZE Daemon — FastAPI 서버 엔트리포인트 (v6.0 Phase 2B-1 분리 완료)."""
import logging

from fastapi import FastAPI

from daemon.orchestrator import lifespan
from daemon.api_routes import router as main_router

# 외부 라우터들
from discord_interactive import router as boss_router
from saas_marketing import router as ls_webhook_router
from gumroad_manager import router as gr_webhook_router
from feature_prioritizer import router as feedback_router

# === 로깅 설정 ===
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("REZE.daemon")

# ============================================================
# FastAPI App
# ============================================================
app = FastAPI(
    title="REZE Agent",
    version="4.0-ultimate",
    lifespan=lifespan,
)

# 메인 라우터 등록
app.include_router(main_router)

# 외부 라우터 등록
app.include_router(boss_router)
app.include_router(ls_webhook_router)
app.include_router(gr_webhook_router)
app.include_router(feedback_router)

# ============================================================
# 직접 실행 시
# ============================================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8888)
