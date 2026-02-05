"""
EVENT HORIZON v3.0 — Hawking Radiation
실패한 콘텐츠를 재활용하는 시스템

블랙홀도 복사(Hawking Radiation)를 방출한다.
실패한 콘텐츠도 완전히 사라지지 않고, 다른 형태로 재활용된다.

재활용 전략:
1. MERGE - 관련 글과 병합
2. REDIRECT - 더 좋은 글로 301 리다이렉트
3. UPDATE - 콘텐츠 새로고침
4. REPURPOSE - 다른 형식으로 변환 (글→영상 스크립트)
5. DELETE - 완전 삭제 (최후의 수단)
"""

import logging
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from enum import Enum

logger = logging.getLogger("reze.fish.hawking")


class RecycleAction(Enum):
    """재활용 액션"""
    MERGE = "merge"           # 다른 글과 병합
    REDIRECT = "redirect"     # 301 리다이렉트
    UPDATE = "update"         # 콘텐츠 업데이트
    REPURPOSE = "repurpose"   # 형식 변환
    DELETE = "delete"         # 삭제


class DeathReason(Enum):
    """콘텐츠 사망 이유"""
    NO_TRAFFIC = "no_traffic"           # 30일간 트래픽 없음
    HIGH_BOUNCE = "high_bounce"         # 이탈률 90% 이상
    NO_CONVERSION = "no_conversion"     # 전환 없음
    OUTDATED = "outdated"               # 오래된 정보
    DUPLICATE = "duplicate"             # 중복 콘텐츠
    LOW_QUALITY = "low_quality"         # 품질 미달
    CANNIBALIZATION = "cannibalization" # 키워드 카니발라이제이션


@dataclass
class DeadContent:
    """죽은 콘텐츠"""
    id: int = 0
    blog: str = ""
    slug: str = ""
    title: str = ""
    death_reason: DeathReason = DeathReason.NO_TRAFFIC
    page_views_30d: int = 0
    bounce_rate: float = 0.0
    days_since_publish: int = 0
    recycled: bool = False
    recycle_action: RecycleAction = None
    recycle_target: str = ""        # 병합/리다이렉트 대상
    created_at: str = ""
    recycled_at: str = ""


@dataclass
class RecycleResult:
    """재활용 결과"""
    content: DeadContent
    action: RecycleAction
    success: bool
    message: str
    new_slug: str = ""              # 병합/업데이트 후 새 슬러그
    redirect_to: str = ""           # 리다이렉트 대상


class HawkingRadiation:
    """
    실패한 콘텐츠 재활용 시스템.
    블랙홀의 Hawking Radiation처럼,
    죽은 콘텐츠도 에너지(가치)를 방출할 수 있다.
    """

    # 죽음 판정 기준
    DEATH_THRESHOLDS = {
        "min_page_views_30d": 10,       # 30일 최소 조회수
        "max_bounce_rate": 0.90,        # 최대 이탈률
        "min_time_on_page": 30,         # 최소 체류 시간 (초)
        "max_age_days_without_update": 365,  # 업데이트 없이 최대 일수
    }

    # 재활용 전략 결정 규칙
    RECYCLE_RULES = {
        DeathReason.NO_TRAFFIC: RecycleAction.MERGE,
        DeathReason.HIGH_BOUNCE: RecycleAction.UPDATE,
        DeathReason.NO_CONVERSION: RecycleAction.UPDATE,
        DeathReason.OUTDATED: RecycleAction.UPDATE,
        DeathReason.DUPLICATE: RecycleAction.REDIRECT,
        DeathReason.LOW_QUALITY: RecycleAction.DELETE,
        DeathReason.CANNIBALIZATION: RecycleAction.MERGE,
    }

    def __init__(self, ssot, gravity_well=None):
        self.ssot = ssot
        self.gravity = gravity_well

    # ═══════════════════════════════════════════════════════════════════════
    # 죽은 콘텐츠 식별
    # ═══════════════════════════════════════════════════════════════════════

    def scan_for_dead_content(self, blog: str = None) -> List[DeadContent]:
        """죽은 콘텐츠 스캔"""
        dead_list = []

        try:
            # 기존 dead_content 테이블에서 미처리 항목
            query = """
                SELECT id, blog, slug, title, death_reason,
                       page_views_30d, bounce_rate, days_since_publish,
                       recycled, recycle_action, recycle_target,
                       created_at, recycled_at
                FROM dead_content
                WHERE recycled = 0
            """
            params = []

            if blog:
                query += " AND blog = ?"
                params.append(blog)

            query += " ORDER BY page_views_30d ASC LIMIT 20"

            rows = self.ssot.conn.execute(query, params).fetchall()

            for r in rows:
                dead_list.append(DeadContent(
                    id=r[0],
                    blog=r[1],
                    slug=r[2],
                    title=r[3] or "",
                    death_reason=DeathReason(r[4]) if r[4] else DeathReason.NO_TRAFFIC,
                    page_views_30d=r[5] or 0,
                    bounce_rate=r[6] or 0.0,
                    days_since_publish=r[7] or 0,
                    recycled=bool(r[8]),
                    recycle_action=RecycleAction(r[9]) if r[9] else None,
                    recycle_target=r[10] or "",
                    created_at=r[11] or "",
                    recycled_at=r[12] or "",
                ))

        except Exception as e:
            logger.error("Failed to scan dead content: %s", e)

        return dead_list

    def add_dead_content(
        self,
        blog: str,
        slug: str,
        title: str,
        death_reason: DeathReason,
        page_views_30d: int = 0,
        bounce_rate: float = 0.0,
        days_since_publish: int = 0
    ) -> Optional[int]:
        """죽은 콘텐츠 등록"""
        try:
            cursor = self.ssot.conn.execute("""
                INSERT OR REPLACE INTO dead_content
                (blog, slug, title, death_reason, page_views_30d,
                 bounce_rate, days_since_publish)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                blog, slug, title, death_reason.value,
                page_views_30d, bounce_rate, days_since_publish
            ))
            self.ssot.conn.commit()
            logger.info("HawkingRadiation: Added dead content %s/%s (%s)",
                       blog, slug, death_reason.value)
            return cursor.lastrowid
        except Exception as e:
            logger.error("Failed to add dead content: %s", e)
            return None

    # ═══════════════════════════════════════════════════════════════════════
    # 재활용 전략 결정
    # ═══════════════════════════════════════════════════════════════════════

    def decide_recycle_action(self, content: DeadContent) -> RecycleAction:
        """재활용 전략 결정"""
        # 기본 규칙 적용
        action = self.RECYCLE_RULES.get(content.death_reason, RecycleAction.UPDATE)

        # 추가 규칙
        # 1. 매우 오래된 콘텐츠 → 삭제 검토
        if content.days_since_publish > 730 and content.page_views_30d == 0:
            action = RecycleAction.DELETE

        # 2. 약간의 트래픽이 있으면 업데이트 시도
        if content.page_views_30d > 0:
            action = RecycleAction.UPDATE

        # 3. Gravity Well 클러스터면 Pillar로 병합 검토
        if self.gravity and self._is_cluster_content(content):
            action = RecycleAction.MERGE

        return action

    def _is_cluster_content(self, content: DeadContent) -> bool:
        """Gravity Well 클러스터 여부 확인"""
        try:
            row = self.ssot.conn.execute("""
                SELECT COUNT(*) FROM gravity_well_cluster
                WHERE cluster_slug = ?
            """, (content.slug,)).fetchone()
            return row[0] > 0
        except:
            return False

    def find_merge_target(self, content: DeadContent) -> Optional[str]:
        """병합 대상 찾기"""
        try:
            # 1. 같은 Pillar의 다른 클러스터
            if self.gravity:
                row = self.ssot.conn.execute("""
                    SELECT p.pillar_slug FROM gravity_well p
                    JOIN gravity_well_cluster c ON c.pillar_id = p.id
                    WHERE c.cluster_slug = ?
                """, (content.slug,)).fetchone()

                if row:
                    return row[0]

            # 2. 비슷한 키워드의 고트래픽 글
            # (실제 구현 시 키워드 매칭 필요)

            # 3. 같은 카테고리의 Pillar
            row = self.ssot.conn.execute("""
                SELECT pillar_slug FROM gravity_well
                WHERE blog = ?
                ORDER BY total_traffic DESC LIMIT 1
            """, (content.blog,)).fetchone()

            if row:
                return row[0]

        except Exception as e:
            logger.error("Failed to find merge target: %s", e)

        return None

    # ═══════════════════════════════════════════════════════════════════════
    # 재활용 실행
    # ═══════════════════════════════════════════════════════════════════════

    async def recycle(self, content: DeadContent,
                     action: RecycleAction = None) -> RecycleResult:
        """콘텐츠 재활용 실행"""
        if not action:
            action = self.decide_recycle_action(content)

        logger.info("HawkingRadiation: Recycling %s/%s with action %s",
                   content.blog, content.slug, action.value)

        try:
            if action == RecycleAction.MERGE:
                return await self._execute_merge(content)
            elif action == RecycleAction.REDIRECT:
                return await self._execute_redirect(content)
            elif action == RecycleAction.UPDATE:
                return await self._execute_update(content)
            elif action == RecycleAction.REPURPOSE:
                return await self._execute_repurpose(content)
            elif action == RecycleAction.DELETE:
                return await self._execute_delete(content)
            else:
                return RecycleResult(
                    content=content,
                    action=action,
                    success=False,
                    message=f"Unknown action: {action}"
                )
        except Exception as e:
            logger.error("Recycle failed: %s", e)
            return RecycleResult(
                content=content,
                action=action,
                success=False,
                message=str(e)
            )

    async def _execute_merge(self, content: DeadContent) -> RecycleResult:
        """병합 실행"""
        target = self.find_merge_target(content)
        if not target:
            return RecycleResult(
                content=content,
                action=RecycleAction.MERGE,
                success=False,
                message="No merge target found"
            )

        # 실제 병합은 블로그 시스템에서 처리
        # 여기서는 상태만 업데이트
        self._mark_recycled(content, RecycleAction.MERGE, target)

        return RecycleResult(
            content=content,
            action=RecycleAction.MERGE,
            success=True,
            message=f"Marked for merge into {target}",
            redirect_to=target,
        )

    async def _execute_redirect(self, content: DeadContent) -> RecycleResult:
        """리다이렉트 설정"""
        target = self.find_merge_target(content)
        if not target:
            return RecycleResult(
                content=content,
                action=RecycleAction.REDIRECT,
                success=False,
                message="No redirect target found"
            )

        # 리다이렉트 기록
        self._mark_recycled(content, RecycleAction.REDIRECT, target)

        return RecycleResult(
            content=content,
            action=RecycleAction.REDIRECT,
            success=True,
            message=f"Redirect to {target}",
            redirect_to=target,
        )

    async def _execute_update(self, content: DeadContent) -> RecycleResult:
        """콘텐츠 업데이트 예약"""
        # 업데이트 태스크 생성
        task_spec = f"""[CONTENT_UPDATE]
Blog: {content.blog}
Slug: {content.slug}
Death Reason: {content.death_reason.value}
Current Views: {content.page_views_30d}

Update this article:
1. Refresh outdated information
2. Improve SEO (title, meta, headers)
3. Add internal links to pillars
4. Update images if needed
"""

        try:
            self.ssot.conn.execute("""
                INSERT INTO daemon_tasks (task_spec, mode, priority, status)
                VALUES (?, 'write', 5, 'pending')
            """, (task_spec,))
            self.ssot.conn.commit()

            self._mark_recycled(content, RecycleAction.UPDATE, content.slug)

            return RecycleResult(
                content=content,
                action=RecycleAction.UPDATE,
                success=True,
                message="Update task created",
                new_slug=content.slug,
            )
        except Exception as e:
            return RecycleResult(
                content=content,
                action=RecycleAction.UPDATE,
                success=False,
                message=str(e),
            )

    async def _execute_repurpose(self, content: DeadContent) -> RecycleResult:
        """형식 변환 (예: 블로그 → 비디오 스크립트)"""
        # 향후 구현
        self._mark_recycled(content, RecycleAction.REPURPOSE, "")

        return RecycleResult(
            content=content,
            action=RecycleAction.REPURPOSE,
            success=True,
            message="Marked for repurpose",
        )

    async def _execute_delete(self, content: DeadContent) -> RecycleResult:
        """삭제 (실제 삭제는 수동으로)"""
        self._mark_recycled(content, RecycleAction.DELETE, "")

        return RecycleResult(
            content=content,
            action=RecycleAction.DELETE,
            success=True,
            message="Marked for deletion",
        )

    def _mark_recycled(self, content: DeadContent, action: RecycleAction, target: str):
        """재활용 완료 마킹"""
        try:
            self.ssot.conn.execute("""
                UPDATE dead_content
                SET recycled = 1,
                    recycle_action = ?,
                    recycle_target = ?,
                    recycled_at = datetime('now')
                WHERE id = ?
            """, (action.value, target, content.id))
            self.ssot.conn.commit()
        except Exception as e:
            logger.error("Failed to mark recycled: %s", e)

    # ═══════════════════════════════════════════════════════════════════════
    # 분석
    # ═══════════════════════════════════════════════════════════════════════

    def get_recycle_stats(self, blog: str = None) -> Dict:
        """재활용 통계"""
        try:
            query = "SELECT recycle_action, COUNT(*) FROM dead_content WHERE recycled = 1"
            params = []

            if blog:
                query += " AND blog = ?"
                params.append(blog)

            query += " GROUP BY recycle_action"

            rows = self.ssot.conn.execute(query, params).fetchall()

            stats = {
                "total_recycled": 0,
                "by_action": {},
                "pending": 0,
            }

            for action, count in rows:
                stats["by_action"][action] = count
                stats["total_recycled"] += count

            # 미처리 건수
            pending_query = "SELECT COUNT(*) FROM dead_content WHERE recycled = 0"
            if blog:
                pending_query += " AND blog = ?"
                pending_row = self.ssot.conn.execute(pending_query, (blog,)).fetchone()
            else:
                pending_row = self.ssot.conn.execute(pending_query).fetchone()

            stats["pending"] = pending_row[0] if pending_row else 0

            return stats
        except Exception as e:
            logger.error("Failed to get recycle stats: %s", e)
            return {}

    def identify_candidates(self, blog: str, limit: int = 10) -> List[Dict]:
        """재활용 후보 식별 (GA4 데이터 기반)"""
        candidates = []

        try:
            # 저성과 콘텐츠 식별 (signals 테이블의 GA4 데이터)
            rows = self.ssot.conn.execute("""
                SELECT data FROM signals
                WHERE kind = 'page_analytics'
                AND data LIKE ?
                AND created_at > datetime('now', '-7 days')
            """, (f'%{blog}%',)).fetchall()

            for row in rows:
                try:
                    data = json.loads(row[0])
                    page_views = data.get("page_views", 0)
                    bounce_rate = data.get("bounce_rate", 0)
                    slug = data.get("slug", "")

                    # 죽음 판정
                    if page_views < self.DEATH_THRESHOLDS["min_page_views_30d"]:
                        reason = DeathReason.NO_TRAFFIC
                    elif bounce_rate > self.DEATH_THRESHOLDS["max_bounce_rate"]:
                        reason = DeathReason.HIGH_BOUNCE
                    else:
                        continue  # 아직 살아있음

                    candidates.append({
                        "blog": blog,
                        "slug": slug,
                        "page_views": page_views,
                        "bounce_rate": bounce_rate,
                        "death_reason": reason.value,
                        "suggested_action": self.RECYCLE_RULES[reason].value,
                    })
                except:
                    continue

        except Exception as e:
            logger.error("Failed to identify candidates: %s", e)

        return candidates[:limit]
