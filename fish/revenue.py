"""
EVENT HORIZON v3.0 — Revenue Attribution
수익 귀속 추적 시스템

모든 수익을 원천(블로그 글, 이메일, 어필리에이트)으로 추적.
ROI 기반 콘텐츠 우선순위 결정.
"""

import logging
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from enum import Enum

logger = logging.getLogger("reze.fish.revenue")


class RevenueType(Enum):
    """수익 유형"""
    AFFILIATE_CLICK = "affiliate_click"
    AFFILIATE_SALE = "affiliate_sale"
    SAAS_SIGNUP = "saas_signup"
    SAAS_UPGRADE = "saas_upgrade"
    SAAS_RENEWAL = "saas_renewal"
    AD_REVENUE = "ad_revenue"
    GUMROAD_SALE = "gumroad_sale"


class SourceType(Enum):
    """수익 원천 유형"""
    BLOG_POST = "blog_post"
    EMAIL_CAMPAIGN = "email"
    AFFILIATE_LINK = "affiliate"
    DIRECT = "direct"
    ORGANIC = "organic"
    PAID_AD = "paid"


class AttributionModel(Enum):
    """귀속 모델"""
    LAST_CLICK = "last_click"       # 마지막 클릭
    FIRST_CLICK = "first_click"     # 첫 클릭
    LINEAR = "linear"               # 균등 배분
    TIME_DECAY = "time_decay"       # 시간 가중치


@dataclass
class RevenueEvent:
    """수익 이벤트"""
    id: int = 0
    revenue_type: RevenueType = RevenueType.AFFILIATE_CLICK
    amount: float = 0.0
    currency: str = "USD"
    source_type: SourceType = SourceType.BLOG_POST
    source_id: str = ""             # 블로그 슬러그 또는 캠페인 ID
    attribution_model: AttributionModel = AttributionModel.LAST_CLICK
    metadata: dict = field(default_factory=dict)
    created_at: str = ""


@dataclass
class ContentROI:
    """콘텐츠 ROI"""
    blog: str = ""
    slug: str = ""
    title: str = ""
    total_revenue: float = 0.0
    affiliate_revenue: float = 0.0
    saas_revenue: float = 0.0
    page_views: int = 0
    conversions: int = 0
    roi_score: float = 0.0          # revenue / effort (추정)
    hunt_id: int = 0


class RevenueTracker:
    """
    수익 귀속 추적 시스템.
    모든 수익을 원천으로 추적하여 ROI 기반 의사결정 지원.
    """

    def __init__(self, ssot):
        self.ssot = ssot

    # ═══════════════════════════════════════════════════════════════════════
    # 수익 기록
    # ═══════════════════════════════════════════════════════════════════════

    def record_revenue(
        self,
        revenue_type: RevenueType,
        amount: float,
        source_type: SourceType,
        source_id: str,
        currency: str = "USD",
        attribution_model: AttributionModel = AttributionModel.LAST_CLICK,
        metadata: dict = None
    ) -> Optional[int]:
        """수익 이벤트 기록"""
        try:
            cursor = self.ssot.conn.execute("""
                INSERT INTO revenue_attribution
                (source_type, source_id, revenue_type, amount, currency,
                 attribution_model, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                source_type.value,
                source_id,
                revenue_type.value,
                amount,
                currency,
                attribution_model.value,
                json.dumps(metadata or {})
            ))
            self.ssot.conn.commit()

            logger.info("Revenue: Recorded $%.2f %s from %s/%s",
                       amount, revenue_type.value, source_type.value, source_id)

            return cursor.lastrowid
        except Exception as e:
            logger.error("Failed to record revenue: %s", e)
            return None

    def record_affiliate_click(self, blog_slug: str, affiliate_id: str,
                              metadata: dict = None):
        """어필리에이트 클릭 기록"""
        return self.record_revenue(
            revenue_type=RevenueType.AFFILIATE_CLICK,
            amount=0.0,  # 클릭은 금액 없음
            source_type=SourceType.BLOG_POST,
            source_id=blog_slug,
            metadata={**(metadata or {}), "affiliate_id": affiliate_id}
        )

    def record_affiliate_sale(self, blog_slug: str, amount: float,
                             affiliate_id: str, metadata: dict = None):
        """어필리에이트 판매 기록"""
        return self.record_revenue(
            revenue_type=RevenueType.AFFILIATE_SALE,
            amount=amount,
            source_type=SourceType.BLOG_POST,
            source_id=blog_slug,
            metadata={**(metadata or {}), "affiliate_id": affiliate_id}
        )

    def record_saas_signup(self, source_type: SourceType, source_id: str,
                          product: str, plan: str, amount: float):
        """SaaS 가입 기록"""
        return self.record_revenue(
            revenue_type=RevenueType.SAAS_SIGNUP,
            amount=amount,
            source_type=source_type,
            source_id=source_id,
            metadata={"product": product, "plan": plan}
        )

    # ═══════════════════════════════════════════════════════════════════════
    # 수익 조회
    # ═══════════════════════════════════════════════════════════════════════

    def get_revenue_by_source(self, source_id: str) -> Dict:
        """특정 소스의 수익 합계"""
        try:
            rows = self.ssot.conn.execute("""
                SELECT revenue_type, SUM(amount) as total, COUNT(*) as count
                FROM revenue_attribution
                WHERE source_id = ?
                GROUP BY revenue_type
            """, (source_id,)).fetchall()

            result = {
                "source_id": source_id,
                "total": 0.0,
                "by_type": {},
            }

            for row in rows:
                result["by_type"][row[0]] = {
                    "amount": row[1] or 0,
                    "count": row[2] or 0,
                }
                result["total"] += row[1] or 0

            return result
        except Exception as e:
            logger.error("Failed to get revenue by source: %s", e)
            return {}

    def get_top_revenue_content(self, blog: str = None,
                               days: int = 30, limit: int = 10) -> List[ContentROI]:
        """수익 상위 콘텐츠"""
        try:
            query = """
                SELECT source_id, SUM(amount) as total,
                       SUM(CASE WHEN revenue_type LIKE 'affiliate%' THEN amount ELSE 0 END) as affiliate,
                       SUM(CASE WHEN revenue_type LIKE 'saas%' THEN amount ELSE 0 END) as saas,
                       COUNT(*) as conversions
                FROM revenue_attribution
                WHERE source_type = 'blog_post'
                AND created_at > datetime('now', ?)
            """
            params = [f'-{days} days']

            if blog:
                query += " AND source_id LIKE ?"
                params.append(f'{blog}%')

            query += " GROUP BY source_id ORDER BY total DESC LIMIT ?"
            params.append(limit)

            rows = self.ssot.conn.execute(query, params).fetchall()

            return [
                ContentROI(
                    slug=r[0],
                    total_revenue=r[1] or 0,
                    affiliate_revenue=r[2] or 0,
                    saas_revenue=r[3] or 0,
                    conversions=r[4] or 0,
                )
                for r in rows
            ]
        except Exception as e:
            logger.error("Failed to get top revenue content: %s", e)
            return []

    def get_daily_revenue(self, days: int = 30) -> List[Dict]:
        """일별 수익"""
        try:
            rows = self.ssot.conn.execute("""
                SELECT date(created_at) as day, SUM(amount) as total,
                       COUNT(*) as events
                FROM revenue_attribution
                WHERE created_at > datetime('now', ?)
                GROUP BY date(created_at)
                ORDER BY day DESC
            """, (f'-{days} days',)).fetchall()

            return [
                {"date": r[0], "revenue": r[1] or 0, "events": r[2] or 0}
                for r in rows
            ]
        except Exception as e:
            logger.error("Failed to get daily revenue: %s", e)
            return []

    # ═══════════════════════════════════════════════════════════════════════
    # ROI 분석
    # ═══════════════════════════════════════════════════════════════════════

    def calculate_content_roi(self, slug: str) -> ContentROI:
        """콘텐츠 ROI 계산"""
        revenue_data = self.get_revenue_by_source(slug)

        # 트래픽 데이터 (signals에서)
        page_views = 0
        try:
            row = self.ssot.conn.execute("""
                SELECT SUM(json_extract(data, '$.page_views'))
                FROM signals
                WHERE kind = 'page_analytics'
                AND data LIKE ?
            """, (f'%{slug}%',)).fetchone()
            page_views = row[0] or 0
        except:
            pass

        # 사냥 정보 (hunt_memory에서)
        hunt_id = 0
        try:
            row = self.ssot.conn.execute("""
                SELECT id FROM hunt_memory WHERE blog_slug = ?
            """, (slug,)).fetchone()
            hunt_id = row[0] if row else 0
        except:
            pass

        total_revenue = revenue_data.get("total", 0)
        conversions = sum(
            v.get("count", 0)
            for v in revenue_data.get("by_type", {}).values()
        )

        # ROI Score = revenue / (estimated effort)
        # 추정 노력: 기본 1.0, 트래픽 기반 조정
        effort = 1.0
        roi_score = total_revenue / max(effort, 0.1)

        return ContentROI(
            slug=slug,
            total_revenue=total_revenue,
            affiliate_revenue=revenue_data.get("by_type", {}).get(
                "affiliate_sale", {}).get("amount", 0),
            saas_revenue=revenue_data.get("by_type", {}).get(
                "saas_signup", {}).get("amount", 0),
            page_views=page_views,
            conversions=conversions,
            roi_score=roi_score,
            hunt_id=hunt_id,
        )

    def identify_high_roi_patterns(self) -> List[Dict]:
        """고 ROI 패턴 식별"""
        patterns = []

        try:
            # 전략별 수익
            rows = self.ssot.conn.execute("""
                SELECT h.strategy, SUM(r.amount) as revenue, COUNT(DISTINCT h.id) as hunts
                FROM hunt_memory h
                JOIN revenue_attribution r ON r.source_id = h.blog_slug
                WHERE h.success = 1 AND h.blog_slug IS NOT NULL
                GROUP BY h.strategy
                ORDER BY revenue DESC
            """).fetchall()

            for row in rows:
                if row[2] > 0:  # hunts > 0
                    patterns.append({
                        "pattern": "strategy",
                        "value": row[0],
                        "revenue": row[1] or 0,
                        "count": row[2],
                        "avg_revenue": (row[1] or 0) / row[2],
                    })

        except Exception as e:
            logger.error("Failed to identify patterns: %s", e)

        return patterns

    # ═══════════════════════════════════════════════════════════════════════
    # 리포트
    # ═══════════════════════════════════════════════════════════════════════

    def generate_revenue_report(self, days: int = 30) -> Dict:
        """수익 리포트 생성"""
        daily = self.get_daily_revenue(days)
        top_content = self.get_top_revenue_content(days=days, limit=10)
        patterns = self.identify_high_roi_patterns()

        total_revenue = sum(d["revenue"] for d in daily)
        total_events = sum(d["events"] for d in daily)

        return {
            "period_days": days,
            "total_revenue": total_revenue,
            "total_events": total_events,
            "avg_daily_revenue": total_revenue / max(days, 1),
            "top_content": [
                {"slug": c.slug, "revenue": c.total_revenue}
                for c in top_content[:5]
            ],
            "patterns": patterns,
            "daily_trend": daily[:7],  # 최근 7일
            "generated_at": datetime.now().isoformat(),
        }
