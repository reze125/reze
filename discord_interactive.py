"""
REZE Discord 양방향 통신.

보스가 API에서 직접:
- "승인" -> 제안된 행동 실행
- "거부" -> 제안 취소
- "상태" -> 현재 상태 보고

구현: FastAPI 라우터로 구현.
보스가 Moltbook이나 브라우저에서 접근.
"""

from fastapi import APIRouter
from datetime import datetime
import json
import aiohttp

import logging
logger = logging.getLogger("REZE.boss")

router = APIRouter(prefix="/boss", tags=["boss"])

# 승인 대기 큐 (메모리 저장, 재시작 시 초기화)
pending_approvals = []


async def request_boss_approval(action: str, reason: str, analysis: str = "") -> int:
    """
    보스에게 승인을 요청.
    Discord로 알림 보내고, pending_approvals에 추가.
    """
    import config

    approval_id = len(pending_approvals) + 1

    pending_approvals.append({
        "id": approval_id,
        "action": action,
        "reason": reason,
        "analysis": analysis,
        "status": "pending",
        "created_at": datetime.now().isoformat(),
    })

    msg = f"""**REZE 승인 요청 #{approval_id}**

**행동:** {action}
**이유:** {reason}
{f'**분석:** {analysis[:500]}' if analysis else ''}

승인: `curl -X POST http://YOUR_SERVER:8888/boss/approve/{approval_id}`
거부: `curl -X POST http://YOUR_SERVER:8888/boss/deny/{approval_id}`
목록: `curl http://YOUR_SERVER:8888/boss/pending`"""

    try:
        async with aiohttp.ClientSession() as session:
            await session.post(config.DISCORD_WEBHOOK_ALERT, json={"content": msg[:1900]})
    except Exception as e:
        logger.warning(f"Discord notification failed: {e}")

    logger.info(f"Approval requested #{approval_id}: {action}")
    return approval_id


@router.get("/pending")
async def get_pending():
    """대기 중인 승인 목록."""
    pending = [a for a in pending_approvals if a["status"] == "pending"]
    return {"pending": pending, "total": len(pending)}


@router.post("/approve/{approval_id}")
async def approve(approval_id: int):
    """보스가 승인."""
    for a in pending_approvals:
        if a["id"] == approval_id and a["status"] == "pending":
            a["status"] = "approved"
            a["approved_at"] = datetime.now().isoformat()

            # TODO: 행동 유형에 따라 실제 실행 로직 연결
            logger.info(f"Approved #{approval_id}: {a['action']}")

            return {"status": "approved", "action": a["action"]}

    return {"error": "Not found or already processed"}


@router.post("/deny/{approval_id}")
async def deny(approval_id: int):
    """보스가 거부."""
    for a in pending_approvals:
        if a["id"] == approval_id and a["status"] == "pending":
            a["status"] = "denied"
            a["denied_at"] = datetime.now().isoformat()
            logger.info(f"Denied #{approval_id}: {a['action']}")
            return {"status": "denied", "action": a["action"]}

    return {"error": "Not found or already processed"}


@router.get("/status")
async def status():
    """REZE 전체 상태 요약."""
    from pathlib import Path
    from ssot import SSOT

    ssot = SSOT()
    db = ssot.conn

    skills_count = len(list(Path.home().joinpath("reze-agent/skills").iterdir()))

    discoveries_today = db.execute(
        "SELECT COUNT(*) FROM discoveries WHERE created_at > datetime('now', '-1 day')"
    ).fetchone()[0]

    evolutions_today = db.execute(
        "SELECT COUNT(*) FROM evolutions WHERE created_at > datetime('now', '-1 day')"
    ).fetchone()[0]

    lessons_today = db.execute(
        "SELECT COUNT(*) FROM signals WHERE kind='lesson_learned' AND created_at > datetime('now', '-1 day')"
    ).fetchone()[0]

    ssot.close()

    return {
        "skills": skills_count,
        "discoveries_today": discoveries_today,
        "evolutions_today": evolutions_today,
        "lessons_today": lessons_today,
        "pending_approvals": len([a for a in pending_approvals if a["status"] == "pending"]),
        "version": "3.3-p4",
    }


@router.get("/history")
async def history(limit: int = 20):
    """승인/거부 이력."""
    processed = [a for a in pending_approvals if a["status"] != "pending"]
    return {"history": processed[-limit:], "total": len(processed)}
