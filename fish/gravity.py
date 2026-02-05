"""
EVENT HORIZON v3.0 — Gravity Well
Pillar-Cluster SEO 구조 관리

Pillar (필러) = 핵심 주제의 대형 글
Cluster (클러스터) = 필러를 지원하는 관련 글들
Internal Links = 클러스터 → 필러 링크로 SEO 강화

목표: +43% organic traffic (업계 평균)
"""

import logging
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any

logger = logging.getLogger("reze.fish.gravity")


@dataclass
class Pillar:
    """Pillar 콘텐츠 (중력 우물의 중심)"""
    id: int = 0
    blog: str = ""                    # aitoolslab, nocodetoolslab
    slug: str = ""                    # "best-ai-writing-tools-2025"
    title: str = ""
    topic_cluster: str = ""           # "ai-writing"
    target_keywords: List[str] = field(default_factory=list)
    cluster_count: int = 0
    total_traffic: int = 0
    created_at: str = ""
    updated_at: str = ""


@dataclass
class Cluster:
    """Cluster 콘텐츠 (필러 주위를 도는 위성)"""
    id: int = 0
    pillar_id: int = 0
    slug: str = ""
    title: str = ""
    link_to_pillar: bool = True
    traffic: int = 0
    created_at: str = ""


@dataclass
class InternalLink:
    """블로그 간 내부 링크"""
    id: int = 0
    from_blog: str = ""
    from_slug: str = ""
    to_blog: str = ""
    to_slug: str = ""
    anchor_text: str = ""
    link_type: str = "related"        # related, pillar, cluster, cta
    clicks: int = 0


class GravityWell:
    """
    Pillar-Cluster SEO 구조 관리 시스템.
    블랙홀의 중력이 주변 물질을 끌어당기듯,
    Pillar가 Cluster 콘텐츠를 통해 트래픽을 끌어당긴다.
    """

    def __init__(self, ssot):
        self.ssot = ssot

    # ═══════════════════════════════════════════════════════════════════════
    # Pillar 관리
    # ═══════════════════════════════════════════════════════════════════════

    def create_pillar(
        self,
        blog: str,
        slug: str,
        title: str,
        topic_cluster: str,
        target_keywords: List[str] = None
    ) -> Optional[int]:
        """새 Pillar 생성"""
        try:
            cursor = self.ssot.conn.execute(
                """INSERT INTO gravity_well
                   (blog, pillar_slug, pillar_title, topic_cluster, target_keywords)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    blog,
                    slug,
                    title,
                    topic_cluster,
                    json.dumps(target_keywords or [])
                )
            )
            self.ssot.conn.commit()
            pillar_id = cursor.lastrowid
            logger.info("GravityWell: Created pillar %s/%s (id=%d)", blog, slug, pillar_id)
            return pillar_id
        except Exception as e:
            if "UNIQUE constraint" in str(e):
                logger.warning("GravityWell: Pillar already exists: %s/%s", blog, slug)
            else:
                logger.error("GravityWell: Failed to create pillar: %s", e)
            return None

    def get_pillar(self, blog: str, slug: str) -> Optional[Pillar]:
        """Pillar 조회"""
        try:
            row = self.ssot.conn.execute(
                """SELECT id, blog, pillar_slug, pillar_title, topic_cluster,
                          target_keywords, cluster_count, total_traffic,
                          created_at, updated_at
                   FROM gravity_well
                   WHERE blog=? AND pillar_slug=?""",
                (blog, slug)
            ).fetchone()

            if row:
                return Pillar(
                    id=row[0],
                    blog=row[1],
                    slug=row[2],
                    title=row[3],
                    topic_cluster=row[4],
                    target_keywords=json.loads(row[5] or "[]"),
                    cluster_count=row[6],
                    total_traffic=row[7],
                    created_at=row[8],
                    updated_at=row[9],
                )
        except Exception as e:
            logger.error("GravityWell: Failed to get pillar: %s", e)
        return None

    def list_pillars(self, blog: str = None) -> List[Pillar]:
        """모든 Pillar 목록"""
        try:
            if blog:
                rows = self.ssot.conn.execute(
                    """SELECT id, blog, pillar_slug, pillar_title, topic_cluster,
                              target_keywords, cluster_count, total_traffic,
                              created_at, updated_at
                       FROM gravity_well WHERE blog=?
                       ORDER BY total_traffic DESC""",
                    (blog,)
                ).fetchall()
            else:
                rows = self.ssot.conn.execute(
                    """SELECT id, blog, pillar_slug, pillar_title, topic_cluster,
                              target_keywords, cluster_count, total_traffic,
                              created_at, updated_at
                       FROM gravity_well
                       ORDER BY total_traffic DESC"""
                ).fetchall()

            return [Pillar(
                id=r[0], blog=r[1], slug=r[2], title=r[3],
                topic_cluster=r[4], target_keywords=json.loads(r[5] or "[]"),
                cluster_count=r[6], total_traffic=r[7],
                created_at=r[8], updated_at=r[9]
            ) for r in rows]
        except Exception as e:
            logger.error("GravityWell: Failed to list pillars: %s", e)
            return []

    # ═══════════════════════════════════════════════════════════════════════
    # Cluster 관리
    # ═══════════════════════════════════════════════════════════════════════

    def add_cluster(
        self,
        pillar_id: int,
        slug: str,
        title: str,
        link_to_pillar: bool = True
    ) -> Optional[int]:
        """Pillar에 Cluster 추가"""
        try:
            cursor = self.ssot.conn.execute(
                """INSERT INTO gravity_well_cluster
                   (pillar_id, cluster_slug, cluster_title, link_to_pillar)
                   VALUES (?, ?, ?, ?)""",
                (pillar_id, slug, title, 1 if link_to_pillar else 0)
            )

            # Pillar의 cluster_count 업데이트
            self.ssot.conn.execute(
                """UPDATE gravity_well
                   SET cluster_count = cluster_count + 1,
                       updated_at = datetime('now')
                   WHERE id=?""",
                (pillar_id,)
            )

            self.ssot.conn.commit()
            cluster_id = cursor.lastrowid
            logger.info("GravityWell: Added cluster %s to pillar %d", slug, pillar_id)
            return cluster_id
        except Exception as e:
            logger.error("GravityWell: Failed to add cluster: %s", e)
            return None

    def get_clusters(self, pillar_id: int) -> List[Cluster]:
        """Pillar의 모든 Cluster 조회"""
        try:
            rows = self.ssot.conn.execute(
                """SELECT id, pillar_id, cluster_slug, cluster_title,
                          link_to_pillar, traffic, created_at
                   FROM gravity_well_cluster
                   WHERE pillar_id=?
                   ORDER BY traffic DESC""",
                (pillar_id,)
            ).fetchall()

            return [Cluster(
                id=r[0], pillar_id=r[1], slug=r[2], title=r[3],
                link_to_pillar=bool(r[4]), traffic=r[5], created_at=r[6]
            ) for r in rows]
        except Exception as e:
            logger.error("GravityWell: Failed to get clusters: %s", e)
            return []

    # ═══════════════════════════════════════════════════════════════════════
    # 내부 링크 관리
    # ═══════════════════════════════════════════════════════════════════════

    def add_internal_link(
        self,
        from_blog: str,
        from_slug: str,
        to_blog: str,
        to_slug: str,
        anchor_text: str,
        link_type: str = "related"
    ) -> bool:
        """내부 링크 추가"""
        try:
            self.ssot.conn.execute(
                """INSERT OR REPLACE INTO cross_blog_link
                   (from_blog, from_slug, to_blog, to_slug, anchor_text, link_type)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (from_blog, from_slug, to_blog, to_slug, anchor_text, link_type)
            )
            self.ssot.conn.commit()
            logger.info("GravityWell: Added link %s/%s -> %s/%s",
                       from_blog, from_slug, to_blog, to_slug)
            return True
        except Exception as e:
            logger.error("GravityWell: Failed to add internal link: %s", e)
            return False

    def get_outbound_links(self, blog: str, slug: str) -> List[InternalLink]:
        """특정 글에서 나가는 내부 링크"""
        try:
            rows = self.ssot.conn.execute(
                """SELECT id, from_blog, from_slug, to_blog, to_slug,
                          anchor_text, link_type, clicks
                   FROM cross_blog_link
                   WHERE from_blog=? AND from_slug=?""",
                (blog, slug)
            ).fetchall()

            return [InternalLink(
                id=r[0], from_blog=r[1], from_slug=r[2],
                to_blog=r[3], to_slug=r[4], anchor_text=r[5],
                link_type=r[6], clicks=r[7]
            ) for r in rows]
        except Exception as e:
            logger.error("GravityWell: Failed to get outbound links: %s", e)
            return []

    def get_inbound_links(self, blog: str, slug: str) -> List[InternalLink]:
        """특정 글로 들어오는 내부 링크"""
        try:
            rows = self.ssot.conn.execute(
                """SELECT id, from_blog, from_slug, to_blog, to_slug,
                          anchor_text, link_type, clicks
                   FROM cross_blog_link
                   WHERE to_blog=? AND to_slug=?""",
                (blog, slug)
            ).fetchall()

            return [InternalLink(
                id=r[0], from_blog=r[1], from_slug=r[2],
                to_blog=r[3], to_slug=r[4], anchor_text=r[5],
                link_type=r[6], clicks=r[7]
            ) for r in rows]
        except Exception as e:
            logger.error("GravityWell: Failed to get inbound links: %s", e)
            return []

    # ═══════════════════════════════════════════════════════════════════════
    # 자동 링크 제안
    # ═══════════════════════════════════════════════════════════════════════

    def suggest_links_for_cluster(self, cluster_slug: str, pillar_id: int) -> List[Dict]:
        """Cluster 글에 추가할 링크 제안"""
        suggestions = []

        try:
            # 1. Pillar로의 링크 (필수)
            pillar = self.ssot.conn.execute(
                """SELECT blog, pillar_slug, pillar_title
                   FROM gravity_well WHERE id=?""",
                (pillar_id,)
            ).fetchone()

            if pillar:
                suggestions.append({
                    "type": "pillar",
                    "to_blog": pillar[0],
                    "to_slug": pillar[1],
                    "anchor_text": pillar[2],
                    "priority": "high",
                    "reason": "Link to pillar for SEO boost"
                })

            # 2. 같은 Pillar의 다른 Cluster들
            siblings = self.ssot.conn.execute(
                """SELECT cluster_slug, cluster_title FROM gravity_well_cluster
                   WHERE pillar_id=? AND cluster_slug != ?
                   ORDER BY traffic DESC LIMIT 3""",
                (pillar_id, cluster_slug)
            ).fetchall()

            for sibling in siblings:
                suggestions.append({
                    "type": "sibling",
                    "to_blog": pillar[0] if pillar else "",
                    "to_slug": sibling[0],
                    "anchor_text": sibling[1],
                    "priority": "medium",
                    "reason": "Related cluster content"
                })

        except Exception as e:
            logger.error("GravityWell: Failed to suggest links: %s", e)

        return suggestions

    # ═══════════════════════════════════════════════════════════════════════
    # 분석
    # ═══════════════════════════════════════════════════════════════════════

    def get_pillar_stats(self, pillar_id: int) -> Dict:
        """Pillar 통계"""
        try:
            pillar = self.ssot.conn.execute(
                """SELECT pillar_slug, pillar_title, cluster_count, total_traffic
                   FROM gravity_well WHERE id=?""",
                (pillar_id,)
            ).fetchone()

            if not pillar:
                return {}

            clusters = self.get_clusters(pillar_id)
            cluster_traffic = sum(c.traffic for c in clusters)

            inbound = self.ssot.conn.execute(
                """SELECT COUNT(*) FROM cross_blog_link
                   WHERE to_slug=?""",
                (pillar[0],)
            ).fetchone()[0]

            return {
                "pillar_slug": pillar[0],
                "pillar_title": pillar[1],
                "cluster_count": pillar[2],
                "pillar_traffic": pillar[3],
                "cluster_traffic": cluster_traffic,
                "total_traffic": pillar[3] + cluster_traffic,
                "inbound_links": inbound,
                "avg_cluster_traffic": cluster_traffic / max(len(clusters), 1),
            }
        except Exception as e:
            logger.error("GravityWell: Failed to get pillar stats: %s", e)
            return {}

    def identify_weak_clusters(self, min_traffic: int = 100) -> List[Dict]:
        """트래픽이 낮은 Cluster 식별 (Hawking Radiation 후보)"""
        weak = []

        try:
            rows = self.ssot.conn.execute(
                """SELECT c.id, c.cluster_slug, c.cluster_title, c.traffic,
                          p.pillar_slug, p.blog
                   FROM gravity_well_cluster c
                   JOIN gravity_well p ON c.pillar_id = p.id
                   WHERE c.traffic < ?
                   ORDER BY c.traffic ASC LIMIT 20""",
                (min_traffic,)
            ).fetchall()

            for r in rows:
                weak.append({
                    "cluster_id": r[0],
                    "cluster_slug": r[1],
                    "cluster_title": r[2],
                    "traffic": r[3],
                    "pillar_slug": r[4],
                    "blog": r[5],
                    "action": "update" if r[3] > 0 else "merge_or_delete",
                })
        except Exception as e:
            logger.error("GravityWell: Failed to identify weak clusters: %s", e)

        return weak

    # ═══════════════════════════════════════════════════════════════════════
    # 자동 Pillar 발견
    # ═══════════════════════════════════════════════════════════════════════

    def discover_potential_pillars(self, blog: str) -> List[Dict]:
        """기존 콘텐츠에서 잠재적 Pillar 발견"""
        potentials = []

        try:
            # 검색 쿼리 데이터에서 클러스터링
            rows = self.ssot.conn.execute("""
                SELECT data FROM signals
                WHERE kind='search_query' AND data LIKE ?
                AND created_at > datetime('now', '-30 days')
            """, (f'%{blog}%',)).fetchall()

            # 키워드 빈도 분석
            keyword_counts = {}
            for row in rows:
                try:
                    data = json.loads(row[0])
                    query = data.get("query", "").lower()
                    words = query.split()
                    for word in words:
                        if len(word) > 3:
                            keyword_counts[word] = keyword_counts.get(word, 0) + 1
                except:
                    continue

            # 상위 키워드 = 잠재적 Pillar 토픽
            sorted_keywords = sorted(keyword_counts.items(), key=lambda x: x[1], reverse=True)

            for keyword, count in sorted_keywords[:5]:
                if count >= 10:  # 최소 10회 언급
                    potentials.append({
                        "keyword": keyword,
                        "count": count,
                        "suggested_pillar": f"best-{keyword}-tools-2025",
                        "topic_cluster": keyword,
                    })

        except Exception as e:
            logger.error("GravityWell: Failed to discover pillars: %s", e)

        return potentials
