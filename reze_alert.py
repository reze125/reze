"""REZE Alert Manager — 알림 + 일일 리포트"""
import json
import logging
from datetime import datetime
from pathlib import Path

import aiohttp

import config

logger = logging.getLogger("REZE.alert")


class AlertManager:
    """severity 기반 알림. Discord 전송 + 선택적 Moltbook 포스트."""

    def __init__(self, ssot, moltbook_key: str = None, enable_moltbook: bool = False):
        self.ssot = ssot
        self._moltbook_key = moltbook_key or self._load_moltbook_key()
        self._enable_moltbook = enable_moltbook  # v6.0: 기본 비활성화

    def _load_moltbook_key(self) -> str:
        """~/moltbook_credentials.json에서 API key 로드."""
        cred_path = Path.home() / "moltbook_credentials.json"
        if cred_path.exists():
            try:
                data = json.loads(cred_path.read_text())
                return data.get("api_key", "")
            except Exception:
                pass
        return ""

    async def send(self, severity: str, source: str, message: str) -> None:
        """알림 기록 → Discord 전송 (critical/warning). Moltbook은 비활성화."""
        self.ssot.save_signal(
            f"alert_{severity}",
            f"[{source}] {message}"
        )
        logger.info(f"Alert [{severity}] {source}: {message[:100]}")

        # v6.0: Discord 전송 (critical, warning)
        if severity in ("critical", "warning"):
            emoji = "🚨" if severity == "critical" else "⚠️"
            await self._post_discord(f"{emoji} **[{source}]** {message[:1800]}")

        # Moltbook은 명시적으로 활성화한 경우만
        if severity == "critical" and self._moltbook_key and self._enable_moltbook:
            await self._post_moltbook(f"🚨 [{source}] {message[:400]}")

    async def _post_discord(self, content: str) -> None:
        """Discord ALERT 웹훅으로 전송."""
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(
                    config.DISCORD_WEBHOOK_ALERT,
                    json={"content": content},
                    timeout=aiohttp.ClientTimeout(total=10),
                )
                logger.info("Discord alert sent")
        except Exception as e:
            logger.warning(f"Discord alert failed: {e}")

    async def _post_moltbook(self, content: str) -> None:
        """Moltbook에 알림 포스트."""
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(
                    "https://www.moltbook.com/api/v1/posts",
                    headers={
                        "Authorization": f"Bearer {self._moltbook_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "submolt": "general",
                        "title": "🚨 REZE Alert",
                        "content": content,
                    },
                    timeout=aiohttp.ClientTimeout(total=10),
                )
                logger.info("Moltbook alert posted")
        except Exception as e:
            logger.warning(f"Moltbook alert failed: {e}")

    def generate_daily_report(self) -> str:
        """일일 텍스트 리포트 생성 → signals에 저장."""
        today = datetime.now(config.KST).strftime("%Y-%m-%d")

        # LLM 프로바이더 통계
        stats = self.ssot.get_provider_stats(hours=24)

        # 예산
        budget = self.ssot.conn.execute(
            "SELECT * FROM daily_budget WHERE date=?", (today,)
        ).fetchone()

        # Self-Healing 건수
        heals = self.ssot.conn.execute(
            "SELECT COUNT(*) FROM signals "
            "WHERE kind LIKE 'self_heal%' AND created_at > datetime('now', '-1 day')"
        ).fetchone()

        # 알림 건수
        alerts = self.ssot.conn.execute(
            "SELECT COUNT(*) FROM signals "
            "WHERE kind LIKE 'alert_%' AND created_at > datetime('now', '-1 day')"
        ).fetchone()

        # 태스크 통계
        tasks = self.ssot.conn.execute(
            "SELECT status, COUNT(*) FROM tasks "
            "WHERE created_at > datetime('now', '-1 day') GROUP BY status"
        ).fetchall()

        # 리포트 조립
        report = f"📊 REZE Daily Report ({today})\n{'='*40}\n\n"

        report += "🤖 LLM Providers:\n"
        for s in stats:
            report += (f"  {s['provider']}: {s['calls']}calls, "
                      f"{s.get('total_tokens',0) or 0:,}tok, "
                      f"{s.get('avg_latency',0) or 0}ms avg, "
                      f"{s.get('errors',0)}err\n")
        if not stats:
            report += "  (no traces today)\n"

        if budget:
            b = dict(budget)
            report += (f"\n💰 Budget: {b.get('total_tokens',0):,} / "
                      f"{config.DAILY_TOKEN_BUDGET:,} tokens "
                      f"({b.get('total_tokens',0)/config.DAILY_TOKEN_BUDGET*100:.1f}%)\n")

        report += f"\n🔧 Self-Healing: {heals[0] if heals else 0}건\n"
        report += f"🔔 Alerts: {alerts[0] if alerts else 0}건\n"

        report += "\n📋 Tasks:\n"
        for t in (tasks or []):
            report += f"  {t[0]}: {t[1]}\n"
        if not tasks:
            report += "  (no tasks today)\n"

        # 저장
        self.ssot.save_signal("daily_report", report)
        logger.info(f"Daily report generated ({len(report)} chars)")
        return report
