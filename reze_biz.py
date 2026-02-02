"""REZE Biz Tracker — LemonSqueezy 매출 자동 수집"""
import json
import logging

import aiohttp

logger = logging.getLogger("REZE.biz")


class BizTracker:
    """LemonSqueezy API로 매출 지표 수집."""

    def __init__(self, ssot, ls_api_key: str = None):
        self.ssot = ssot
        self.ls_key = ls_api_key or ""

    async def collect(self) -> None:
        """모든 비즈니스 지표 수집."""
        if self.ls_key:
            await self._collect_lemon_squeezy()

    async def _collect_lemon_squeezy(self) -> None:
        """LemonSqueezy 주문/매출 수집."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://api.lemonsqueezy.com/v1/orders",
                    headers={
                        "Authorization": f"Bearer {self.ls_key}",
                        "Accept": "application/vnd.api+json",
                    },
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status != 200:
                        logger.warning(f"LemonSqueezy API {resp.status}")
                        return

                    data = await resp.json()
                    orders = data.get("data", [])
                    total_revenue = sum(
                        float(o.get("attributes", {}).get("total", 0)) / 100
                        for o in orders
                    )
                    self.ssot.log_biz_metric(
                        "lemon_squeezy", "total_revenue",
                        total_revenue, "USD",
                        json.dumps({"order_count": len(orders)})
                    )
                    logger.info(f"LemonSqueezy: ${total_revenue:.2f} ({len(orders)} orders)")

        except Exception as e:
            logger.error(f"LemonSqueezy collection failed: {e}")
            self.ssot.save_signal("biz_error", f"LemonSqueezy: {e}")
