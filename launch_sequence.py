"""
REZE 런치 시퀀스 — 신제품/업데이트 멀티채널 런치 자동화.

역할:
- D-7: 블로그에 "곧 출시" 포스트
- D-3: 이메일 리스트에 프리뷰
- D-1: Product Hunt Coming Soon 알림
- D-Day: 전 채널 동시 런치
- D+7: 후속 이메일 시퀀스

★ 현실:
  - 이메일 리스트: 아직 없음 (Brevo 셋업 후)
  - Product Hunt: API가 아닌 수동 (알림만)
  - 블로그 포스트: blog_spinup.py 연동 가능
  → 현재는 "런치 체크리스트 + Discord 알림" 모드

SSOT: launches 테이블
"""

import json
from datetime import datetime, timedelta
from typing import Optional

import config

import logging
logger = logging.getLogger("REZE.launch")


class LaunchSequence:
    """멀티채널 런치 자동화."""

    def __init__(self, ssot, alert_fn=None, call_llm_fn=None):
        self.ssot = ssot
        self.alert_fn = alert_fn
        self.call_llm = call_llm_fn

    async def create_launch(self, product_name: str, target_date: str,
                            launch_type: str = "new_product",
                            channels: str = "blog,discord,email") -> dict:
        """
        새 런치 계획 생성.

        target_date: "YYYY-MM-DD" 형식
        channels: 쉼표 구분 (blog, discord, email, producthunt, hackernews)
        """
        launch_id = self.ssot.save_launch(
            product_name, target_date, launch_type, channels
        )

        # 런치 체크리스트 생성
        checklist = self._generate_checklist(target_date, channels)

        # Discord 알림
        if self.alert_fn:
            try:
                await self.alert_fn(
                    "info", "launch_sequence",
                    f"🚀 **런치 등록**: {product_name}\n"
                    f"D-Day: {target_date}\n"
                    f"채널: {channels}\n"
                    f"체크리스트: {len(checklist)}개 항목"
                )
            except Exception:
                pass

        self.ssot.save_signal("launch_created", json.dumps({
            "launch_id": launch_id,
            "product": product_name,
            "target_date": target_date,
            "channels": channels,
        }))

        return {
            "launch_id": launch_id,
            "product": product_name,
            "target_date": target_date,
            "checklist": checklist,
        }

    def _generate_checklist(self, target_date: str, channels: str) -> list[dict]:
        """런치 체크리스트 자동 생성."""
        try:
            d_day = datetime.strptime(target_date, "%Y-%m-%d")
        except ValueError:
            d_day = datetime.now() + timedelta(days=7)

        channel_list = [c.strip() for c in channels.split(",")]
        checklist = []

        # D-14: 준비
        checklist.append({
            "day": "D-14",
            "date": (d_day - timedelta(days=14)).strftime("%Y-%m-%d"),
            "task": "Landing page ready + final copy review",
            "channel": "all",
            "status": "pending",
        })

        # D-7: 블로그 예고
        if "blog" in channel_list:
            checklist.append({
                "day": "D-7",
                "date": (d_day - timedelta(days=7)).strftime("%Y-%m-%d"),
                "task": "Publish 'Coming Soon' blog post",
                "channel": "blog",
                "status": "pending",
            })

        # D-3: 이메일 프리뷰
        if "email" in channel_list:
            checklist.append({
                "day": "D-3",
                "date": (d_day - timedelta(days=3)).strftime("%Y-%m-%d"),
                "task": "Send preview email to subscriber list",
                "channel": "email",
                "status": "pending",
            })

        # D-1: Product Hunt Coming Soon
        if "producthunt" in channel_list:
            checklist.append({
                "day": "D-1",
                "date": (d_day - timedelta(days=1)).strftime("%Y-%m-%d"),
                "task": "Set up Product Hunt Coming Soon page",
                "channel": "producthunt",
                "status": "pending",
            })

        # D-Day
        checklist.append({
            "day": "D-Day",
            "date": target_date,
            "task": "Launch across all channels simultaneously",
            "channel": "all",
            "status": "pending",
        })

        if "producthunt" in channel_list:
            checklist.append({
                "day": "D-Day",
                "date": target_date,
                "task": "Submit to Product Hunt (Tue/Wed/Thu, 12:01 AM PT optimal)",
                "channel": "producthunt",
                "status": "pending",
            })

        if "hackernews" in channel_list:
            checklist.append({
                "day": "D-Day",
                "date": target_date,
                "task": "Post Show HN on Hacker News",
                "channel": "hackernews",
                "status": "pending",
            })

        # D+1: 후속
        checklist.append({
            "day": "D+1",
            "date": (d_day + timedelta(days=1)).strftime("%Y-%m-%d"),
            "task": "Reply to all comments + share results on Discord",
            "channel": "all",
            "status": "pending",
        })

        # D+7: 후속 이메일
        if "email" in channel_list:
            checklist.append({
                "day": "D+7",
                "date": (d_day + timedelta(days=7)).strftime("%Y-%m-%d"),
                "task": "Send follow-up email with launch results + testimonials",
                "channel": "email",
                "status": "pending",
            })

        return checklist

    async def check_due_launches(self) -> list[dict]:
        """
        오늘 + 내일 해야 할 런치 작업 확인.
        매일 스케줄러에서 호출 → 해당 작업 Discord 알림.
        """
        db = self.ssot._get_db()
        today = datetime.now(config.KST).strftime("%Y-%m-%d")
        tomorrow = (datetime.now(config.KST) + timedelta(days=1)).strftime("%Y-%m-%d")

        # 활성 런치 조회
        active = db.execute(
            "SELECT * FROM launches WHERE status IN ('planning', 'in_progress')"
        ).fetchall()
        active = [dict(l) for l in active]

        due_items = []

        for launch in active:
            target = launch.get("target_date", "")
            if not target:
                continue

            try:
                d_day = datetime.strptime(target, "%Y-%m-%d")
            except ValueError:
                continue

            days_until = (d_day - datetime.strptime(today, "%Y-%m-%d")).days

            # 기한 내 작업 알림
            reminders = []
            if days_until == 7:
                reminders.append(f"D-7: {launch['product_name']} 런치 1주 전!")
            elif days_until == 3:
                reminders.append(f"D-3: {launch['product_name']} 이메일 프리뷰 발송")
            elif days_until == 1:
                reminders.append(f"D-1: {launch['product_name']} 내일 런치!")
            elif days_until == 0:
                reminders.append(f"🚀 D-Day: {launch['product_name']} 런치!")
                # 상태 업데이트
                self.ssot.update_launch(launch["id"], status="launched")
            elif days_until == -7:
                reminders.append(f"D+7: {launch['product_name']} 후속 이메일")
                self.ssot.update_launch(launch["id"], status="completed")

            for msg in reminders:
                due_items.append({"launch_id": launch["id"], "message": msg})
                if self.alert_fn:
                    try:
                        await self.alert_fn("info", "launch_sequence", msg)
                    except Exception:
                        pass

        return due_items

    async def generate_launch_plan(self, product_name: str,
                                   product_description: str = "") -> dict:
        """LLM으로 맞춤 런치 전략 생성."""
        if not self.call_llm:
            return {"error": "LLM not available"}

        prompt = f"""Product Hunt + 멀티채널 런치 전략가.

제품: {product_name}
설명: {product_description or "디지털 제품/SaaS"}

보스 상황:
- 솔로 개발자 (한국, 영어권 타겟)
- 예산: $0 (무료 채널만)
- 블로그 2개 운영 중 (AI Tools Lab, NoCode Tools Lab)
- 이메일 리스트: 아직 소규모

최적 런치 전략:
1. 최적 요일/시간? (Product Hunt 기준)
2. 30일 준비 체크리스트?
3. 무료 채널 활용 방법? (HN, Reddit, IndieHackers)
4. 이메일 수집 전략?

JSON:
{{"optimal_day": "화/수/목", "optimal_time": "12:01 AM PT",
  "prep_checklist": ["항목"], "free_channels": ["채널+전략"],
  "email_collection": ["방법"], "estimated_visits": "X-Y"}}
JSON만 반환."""

        try:
            result = await self.call_llm(prompt, role="reasoning")
            text = result.strip().replace("```json", "").replace("```", "").strip()
            plan = json.loads(text)
        except Exception:
            plan = {"raw": "분석 실패"}

        self.ssot.save_signal("launch_plan_generated", json.dumps({
            "product": product_name,
            "plan": plan,
        }, ensure_ascii=False)[:5000])

        return plan
