"""
EVENT HORIZON v3.0 — Content Pipeline
사냥 → 포식 → 발행 파이프라인

Hunt → Devour → Publish 사이클:
1. Hunt: 콘텐츠 기회 발견 (hunt_memory)
2. Devour: 콘텐츠 생성 (draft)
3. Review: 품질 검증
4. Publish: 블로그 발행
5. Track: 성과 추적
"""

import asyncio
import logging
import json
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Callable
from enum import Enum
from pathlib import Path

logger = logging.getLogger("reze.fish.pipeline")


class ContentStatus(Enum):
    """콘텐츠 상태"""
    HUNTED = "hunted"           # 사냥됨 (기회 발견)
    DRAFTING = "drafting"       # 초안 작성 중
    DRAFTED = "drafted"         # 초안 완료
    REVIEWING = "reviewing"     # 리뷰 중
    APPROVED = "approved"       # 승인됨
    PUBLISHING = "publishing"   # 발행 중
    PUBLISHED = "published"     # 발행 완료
    FAILED = "failed"           # 실패


@dataclass
class ContentDraft:
    """콘텐츠 초안"""
    id: int = 0
    hunt_id: int = 0            # hunt_memory.id
    blog: str = ""              # aitoolslab, nocodetoolslab
    slug: str = ""
    title: str = ""
    content: str = ""
    meta_description: str = ""
    tags: List[str] = field(default_factory=list)
    status: ContentStatus = ContentStatus.HUNTED
    quality_score: float = 0.0
    pillar_id: int = 0          # gravity_well.id (있으면)
    created_at: str = ""
    published_at: str = ""


@dataclass
class PublishResult:
    """발행 결과"""
    success: bool
    slug: str = ""
    url: str = ""
    message: str = ""
    publish_time: str = ""


class ContentPipeline:
    """
    사냥 → 포식 → 발행 파이프라인.
    Hunt 결과를 블로그 콘텐츠로 변환하고 발행.
    """

    # 블로그별 콘텐츠 경로
    BLOG_PATHS = {
        "aitoolslab": Path.home() / "ai-tools-lab" / "src" / "content" / "blog",
        "nocodetoolslab": Path.home() / "nocodetoolslab" / "content" / "blog",
    }

    # 발행 스크립트
    PUBLISH_SCRIPT = Path.home() / "reze-agent" / "scripts" / "publish-blog.sh"

    def __init__(self, ssot, core=None, router=None, gravity=None):
        self.ssot = ssot
        self.core = core
        self.router = router
        self.gravity = gravity

    # ═══════════════════════════════════════════════════════════════════════
    # 1. Hunt → Draft (포식)
    # ═══════════════════════════════════════════════════════════════════════

    async def devour_hunt(self, hunt_id: int) -> Optional[ContentDraft]:
        """사냥 결과를 초안으로 변환"""
        # hunt_memory에서 정보 가져오기
        hunt = self._get_hunt(hunt_id)
        if not hunt:
            logger.error("Hunt not found: %d", hunt_id)
            return None

        logger.info("Pipeline: Devouring hunt %d (%s)", hunt_id, hunt.get("strategy"))

        # 블로그 결정 (기본: aitoolslab)
        blog = "aitoolslab"

        # 콘텐츠 타입 결정
        strategy = hunt.get("strategy", "")
        content_type = self._decide_content_type(strategy)

        # 초안 생성
        draft = await self._generate_draft(hunt, blog, content_type)

        if draft:
            # DB에 저장 (daemon_tasks로 추적)
            self._save_draft_task(draft)

            # hunt_memory 업데이트
            self.ssot.conn.execute(
                "UPDATE hunt_memory SET blog_slug=? WHERE id=?",
                (draft.slug, hunt_id)
            )
            self.ssot.conn.commit()

        return draft

    def _get_hunt(self, hunt_id: int) -> Optional[Dict]:
        """hunt_memory에서 정보 조회"""
        try:
            row = self.ssot.conn.execute("""
                SELECT id, strategy, source, target, score, metadata
                FROM hunt_memory WHERE id=?
            """, (hunt_id,)).fetchone()

            if row:
                return {
                    "id": row[0],
                    "strategy": row[1],
                    "source": row[2],
                    "target": row[3],
                    "score": row[4],
                    "metadata": json.loads(row[5] or "{}"),
                }
        except Exception as e:
            logger.error("Failed to get hunt: %s", e)
        return None

    def _decide_content_type(self, strategy: str) -> str:
        """전략에 따른 콘텐츠 타입 결정"""
        mapping = {
            "trending_news": "news",
            "tool_discovery": "review",
            "competitor_gap": "comparison",
            "affiliate": "review",
            "evergreen": "guide",
        }
        return mapping.get(strategy, "article")

    async def _generate_draft(self, hunt: Dict, blog: str,
                             content_type: str) -> Optional[ContentDraft]:
        """LLM으로 초안 생성"""
        if not self.core:
            logger.error("Core not available for draft generation")
            return None

        target = hunt.get("target", "")
        metadata = hunt.get("metadata", {})
        snippet = metadata.get("snippet", "")

        # 프롬프트 구성
        prompt = f"""Write a blog post for AI Tools Lab.

Topic: {target}
Type: {content_type}
Source snippet: {snippet[:500] if snippet else 'N/A'}

Requirements:
1. Title: Catchy, SEO-optimized, under 60 characters
2. Meta description: 150-160 characters
3. Content: 1500-2000 words
4. Include H2 and H3 headers
5. Add a comparison table if relevant
6. Include pros and cons
7. End with a clear CTA

Output format:
---
title: "Your Title Here"
description: "Meta description here"
tags: ["tag1", "tag2"]
---

[Content in markdown]
"""

        try:
            result = await self.core.run(prompt, source="pipeline_devour")

            if result.get("success"):
                content = result.get("answer", "")

                # 메타데이터 파싱
                title, description, tags, body = self._parse_draft_content(content)

                # 슬러그 생성
                slug = self._generate_slug(title)

                return ContentDraft(
                    hunt_id=hunt["id"],
                    blog=blog,
                    slug=slug,
                    title=title,
                    content=body,
                    meta_description=description,
                    tags=tags,
                    status=ContentStatus.DRAFTED,
                    quality_score=hunt.get("score", 0.5),
                )
        except Exception as e:
            logger.error("Draft generation failed: %s", e)

        return None

    def _parse_draft_content(self, content: str) -> tuple:
        """초안 콘텐츠 파싱"""
        title = ""
        description = ""
        tags = []
        body = content

        try:
            # YAML frontmatter 파싱
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    frontmatter = parts[1]
                    body = parts[2].strip()

                    for line in frontmatter.strip().split("\n"):
                        if line.startswith("title:"):
                            title = line.split(":", 1)[1].strip().strip('"\'')
                        elif line.startswith("description:"):
                            description = line.split(":", 1)[1].strip().strip('"\'')
                        elif line.startswith("tags:"):
                            # 간단한 태그 파싱
                            tag_part = line.split(":", 1)[1].strip()
                            if "[" in tag_part:
                                import re
                                tags = re.findall(r'"([^"]+)"', tag_part)
        except:
            pass

        return title, description, tags, body

    def _generate_slug(self, title: str) -> str:
        """제목에서 슬러그 생성"""
        import re
        slug = title.lower()
        slug = re.sub(r'[^a-z0-9\s-]', '', slug)
        slug = re.sub(r'[\s_]+', '-', slug)
        slug = slug.strip('-')[:60]

        # 날짜 추가
        date_str = datetime.now().strftime("%Y-%m-%d")
        return f"{date_str}-{slug}"

    def _save_draft_task(self, draft: ContentDraft):
        """초안을 daemon_tasks에 저장"""
        try:
            task_spec = json.dumps({
                "type": "publish_draft",
                "blog": draft.blog,
                "slug": draft.slug,
                "title": draft.title,
                "hunt_id": draft.hunt_id,
            })

            self.ssot.conn.execute("""
                INSERT INTO daemon_tasks (task_spec, mode, priority, status)
                VALUES (?, 'write', 6, 'pending')
            """, (task_spec,))
            self.ssot.conn.commit()
        except Exception as e:
            logger.error("Failed to save draft task: %s", e)

    # ═══════════════════════════════════════════════════════════════════════
    # 2. Review (품질 검증)
    # ═══════════════════════════════════════════════════════════════════════

    async def review_draft(self, draft: ContentDraft) -> tuple[bool, float, str]:
        """초안 품질 검증"""
        if not self.router:
            return True, 0.7, "Router not available, auto-approved"

        try:
            prompt = f"""Review this blog post draft:

Title: {draft.title}
Content (first 2000 chars):
{draft.content[:2000]}

Rate 0-100 and provide feedback:
1. SEO optimization
2. Content quality
3. Readability
4. Accuracy

Format: SCORE: [number] | FEEDBACK: [text]"""

            response = await self.router.call("reflection", [
                {"role": "user", "content": prompt}
            ])

            text = response.text if hasattr(response, 'text') else str(response)

            # 점수 파싱
            score = 70  # 기본값
            feedback = text
            if "SCORE:" in text:
                try:
                    score_part = text.split("SCORE:")[1].split("|")[0]
                    score = int(''.join(filter(str.isdigit, score_part[:5])))
                except:
                    pass

            approved = score >= 70
            return approved, score / 100, feedback

        except Exception as e:
            logger.error("Review failed: %s", e)
            return True, 0.7, f"Review error: {e}"

    # ═══════════════════════════════════════════════════════════════════════
    # 3. Publish (발행)
    # ═══════════════════════════════════════════════════════════════════════

    async def publish_draft(self, draft: ContentDraft) -> PublishResult:
        """블로그에 발행"""
        blog_path = self.BLOG_PATHS.get(draft.blog)
        if not blog_path:
            return PublishResult(
                success=False,
                message=f"Unknown blog: {draft.blog}"
            )

        try:
            # 1. 파일 생성
            file_path = blog_path / f"{draft.slug}.md"

            # Frontmatter + Content
            frontmatter = f"""---
title: "{draft.title}"
description: "{draft.meta_description}"
pubDate: "{datetime.now().strftime('%Y-%m-%d')}"
tags: {json.dumps(draft.tags)}
---

"""
            full_content = frontmatter + draft.content

            # 파일 쓰기
            file_path.write_text(full_content, encoding='utf-8')
            logger.info("Pipeline: Created %s", file_path)

            # 2. Git commit & push (선택적)
            await self._git_publish(blog_path, draft.slug, draft.title)

            # 3. Gravity Well 연결 (Pillar가 있으면)
            if self.gravity and draft.pillar_id:
                self.gravity.add_cluster(
                    pillar_id=draft.pillar_id,
                    slug=draft.slug,
                    title=draft.title
                )

            # 4. 발행 기록
            self._record_publish(draft)

            url = f"https://{draft.blog}.com/{draft.slug}"

            return PublishResult(
                success=True,
                slug=draft.slug,
                url=url,
                message=f"Published: {draft.title}",
                publish_time=datetime.now().isoformat(),
            )

        except Exception as e:
            logger.error("Publish failed: %s", e)
            return PublishResult(
                success=False,
                message=str(e)
            )

    async def _git_publish(self, blog_path: Path, slug: str, title: str):
        """Git commit & push"""
        try:
            # Git add
            subprocess.run(
                ["git", "add", f"{slug}.md"],
                cwd=str(blog_path),
                capture_output=True,
                timeout=10
            )

            # Git commit
            commit_msg = f"Add: {title[:50]}"
            subprocess.run(
                ["git", "commit", "-m", commit_msg],
                cwd=str(blog_path),
                capture_output=True,
                timeout=10
            )

            # Git push (background)
            subprocess.Popen(
                ["git", "push"],
                cwd=str(blog_path),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            logger.info("Pipeline: Git pushed %s", slug)
        except Exception as e:
            logger.warning("Git publish warning: %s", e)

    def _record_publish(self, draft: ContentDraft):
        """발행 기록"""
        try:
            self.ssot.save_signal("blog_published", json.dumps({
                "blog": draft.blog,
                "slug": draft.slug,
                "title": draft.title,
                "hunt_id": draft.hunt_id,
            }))
        except Exception as e:
            logger.error("Failed to record publish: %s", e)

    # ═══════════════════════════════════════════════════════════════════════
    # 전체 파이프라인
    # ═══════════════════════════════════════════════════════════════════════

    async def run_pipeline(self, hunt_id: int) -> PublishResult:
        """전체 파이프라인 실행: Hunt → Devour → Review → Publish"""
        logger.info("Pipeline: Starting for hunt %d", hunt_id)

        # 1. Devour
        draft = await self.devour_hunt(hunt_id)
        if not draft:
            return PublishResult(success=False, message="Devour failed")

        # 2. Review
        approved, score, feedback = await self.review_draft(draft)
        draft.quality_score = score

        if not approved:
            logger.warning("Pipeline: Draft rejected (score=%.2f)", score)
            return PublishResult(
                success=False,
                message=f"Review rejected: {feedback[:100]}"
            )

        # 3. Publish
        result = await self.publish_draft(draft)

        logger.info("Pipeline: Complete for hunt %d - %s",
                   hunt_id, "SUCCESS" if result.success else "FAILED")

        return result

    # ═══════════════════════════════════════════════════════════════════════
    # 미발행 사냥 처리
    # ═══════════════════════════════════════════════════════════════════════

    def get_unpublished_hunts(self, limit: int = 5) -> List[Dict]:
        """발행되지 않은 성공한 사냥 목록"""
        try:
            rows = self.ssot.conn.execute("""
                SELECT id, strategy, source, target, score, created_at
                FROM hunt_memory
                WHERE success = 1 AND blog_slug IS NULL
                ORDER BY score DESC, created_at DESC
                LIMIT ?
            """, (limit,)).fetchall()

            return [
                {
                    "id": r[0],
                    "strategy": r[1],
                    "source": r[2],
                    "target": r[3],
                    "score": r[4],
                    "created_at": r[5],
                }
                for r in rows
            ]
        except Exception as e:
            logger.error("Failed to get unpublished hunts: %s", e)
            return []

    async def process_pending_hunts(self, max_count: int = 3) -> List[PublishResult]:
        """대기 중인 사냥 일괄 처리"""
        hunts = self.get_unpublished_hunts(max_count)
        results = []

        for hunt in hunts:
            result = await self.run_pipeline(hunt["id"])
            results.append(result)

            # 발행 간격
            await asyncio.sleep(5)

        return results
