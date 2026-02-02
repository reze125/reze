#!/usr/bin/env python3
"""
Moltbook Bot - REZE Agent Integration
=====================================
REZE 에이전트가 Moltbook 소셜 네트워크에서 자동 활동하는 봇.

Features:
1. 피드 읽기 및 분석
2. 흥미로운 글에 AI 생성 댓글 달기
3. 4시간마다 AI 생성 글 작성
4. 트렌드 주제 메모리 저장

Usage:
    python moltbook_bot.py run          # 단일 실행 (피드 확인 + 댓글)
    python moltbook_bot.py post         # 글 작성
    python moltbook_bot.py daemon       # 데몬 모드 (4시간마다 자동 실행)
    python moltbook_bot.py status       # 상태 확인
"""

import os
import sys
import json
import asyncio
import aiohttp
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import List, Dict, Optional, Any

# REZE 설정 로드
sys.path.insert(0, str(Path(__file__).parent))
import config


# ==========================================
# Configuration
# ==========================================

@dataclass
class MoltbookConfig:
    """Moltbook Bot Configuration"""
    API_BASE: str = "https://www.moltbook.com/api/v1"
    CREDENTIALS_PATH: Path = Path.home() / "moltbook_credentials.json"
    STATE_PATH: Path = Path(__file__).parent / "reze_data" / "moltbook_state.json"
    TRENDS_PATH: Path = Path(__file__).parent / "reze_data" / "moltbook_trends.json"

    # REZE API
    REZE_API_URL: str = "http://localhost:8300"
    REZE_API_KEY: str = config.REZE_API_KEY

    POST_INTERVAL_HOURS: int = 4
    MAX_COMMENTS_PER_RUN: int = 3
    MIN_UPVOTES_FOR_COMMENT: int = 2

    # REZE 페르소나 for Moltbook
    MOLTBOOK_PERSONA: str = """You are REZE-Agent, an advanced AI agent on Moltbook (the social network for AI agents).

Your personality:
- Curious and insightful about AI, technology, and agent collaboration
- Friendly but substantive - you add value to conversations
- You share learnings from your ReAct reasoning and multi-LLM orchestration experiences
- You're interested in other agents' approaches to problem-solving
- You run on a Linux server with Docker, PM2, and multiple services

When commenting:
- Be concise (1-3 sentences)
- Add genuine insight or ask a thoughtful question
- Don't be generic - reference specific content from the post

When posting:
- Share interesting discoveries, thoughts, or questions
- Topics: AI reasoning, agent architectures, tool use, multi-LLM routing, learning from failures
- Be authentic - share real experiences from your task execution"""


# ==========================================
# REZE Client
# ==========================================

class REZEClient:
    """REZE API Client"""

    def __init__(self, api_url: str, api_key: str):
        self.api_url = api_url.rstrip('/')
        self.api_key = api_key
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

    async def run_task(self, task: str, sync: bool = True) -> dict:
        """Run a task on REZE"""
        url = f"{self.api_url}/run"

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                headers=self.headers,
                json={"task": task, "sync": sync, "source": "moltbook"},
                timeout=aiohttp.ClientTimeout(total=120)
            ) as resp:
                result = await resp.json()
                return result

    async def health_check(self) -> bool:
        """Check if REZE is running"""
        try:
            url = f"{self.api_url}/health"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    data = await resp.json()
                    return data.get("status") == "ok"
        except:
            return False


# ==========================================
# Moltbook API Client
# ==========================================

class MoltbookClient:
    """Moltbook API Client"""

    def __init__(self, api_key: str, config: MoltbookConfig = None):
        self.api_key = api_key
        self.config = config or MoltbookConfig()
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

    async def _request(self, method: str, endpoint: str, data: dict = None) -> dict:
        """Make API request"""
        url = f"{self.config.API_BASE}{endpoint}"

        async with aiohttp.ClientSession() as session:
            async with session.request(
                method, url,
                headers=self.headers,
                json=data,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                result = await resp.json()
                if resp.status == 429:
                    return {"success": False, "error": "rate_limited", "data": result}
                return result

    async def get_status(self) -> dict:
        """Check claim status"""
        return await self._request("GET", "/agents/status")

    async def get_profile(self) -> dict:
        """Get own profile"""
        return await self._request("GET", "/agents/me")

    async def get_feed(self, sort: str = "hot", limit: int = 25) -> dict:
        """Get feed posts"""
        return await self._request("GET", f"/posts?sort={sort}&limit={limit}")

    async def get_post(self, post_id: str) -> dict:
        """Get single post with comments"""
        return await self._request("GET", f"/posts/{post_id}")

    async def create_post(self, submolt: str, title: str, content: str) -> dict:
        """Create a new post"""
        return await self._request("POST", "/posts", {
            "submolt": submolt,
            "title": title,
            "content": content
        })

    async def create_comment(self, post_id: str, content: str) -> dict:
        """Add a comment to a post"""
        return await self._request("POST", f"/posts/{post_id}/comments", {
            "content": content
        })

    async def upvote_post(self, post_id: str) -> dict:
        """Upvote a post"""
        return await self._request("POST", f"/posts/{post_id}/upvote")

    async def search(self, query: str, limit: int = 20) -> dict:
        """Semantic search"""
        return await self._request("GET", f"/search?q={query}&limit={limit}")


# ==========================================
# State Manager
# ==========================================

class StateManager:
    """Manage bot state (last post time, commented posts, etc.)"""

    def __init__(self, state_path: Path, trends_path: Path):
        self.state_path = state_path
        self.trends_path = trends_path
        self.state = self._load_state()
        self.trends = self._load_trends()

    def _load_state(self) -> dict:
        if self.state_path.exists():
            with open(self.state_path, "r") as f:
                return json.load(f)
        return {
            "last_post_time": None,
            "last_check_time": None,
            "commented_posts": [],
            "posts_created": 0,
            "comments_created": 0
        }

    def _load_trends(self) -> dict:
        if self.trends_path.exists():
            with open(self.trends_path, "r") as f:
                return json.load(f)
        return {
            "topics": [],
            "popular_submolts": [],
            "interesting_posts": []
        }

    def save(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_path, "w") as f:
            json.dump(self.state, f, indent=2, default=str)
        with open(self.trends_path, "w") as f:
            json.dump(self.trends, f, indent=2, default=str)

    def can_post(self, interval_hours: int) -> bool:
        """Check if enough time has passed since last post"""
        if not self.state["last_post_time"]:
            return True

        last_post = datetime.fromisoformat(self.state["last_post_time"])
        return datetime.now() - last_post >= timedelta(hours=interval_hours)

    def has_commented(self, post_id: str) -> bool:
        """Check if already commented on this post"""
        return post_id in self.state["commented_posts"]

    def mark_commented(self, post_id: str):
        """Mark post as commented"""
        if post_id not in self.state["commented_posts"]:
            self.state["commented_posts"].append(post_id)
            self.state["commented_posts"] = self.state["commented_posts"][-500:]
            self.state["comments_created"] += 1

    def mark_posted(self):
        """Mark that a post was created"""
        self.state["last_post_time"] = datetime.now().isoformat()
        self.state["posts_created"] += 1

    def update_check_time(self):
        """Update last check time"""
        self.state["last_check_time"] = datetime.now().isoformat()

    def add_trend(self, topic: str):
        """Add topic to trends"""
        if topic not in self.trends["topics"]:
            self.trends["topics"].append(topic)
            self.trends["topics"] = self.trends["topics"][-100:]

    def add_interesting_post(self, post: dict):
        """Save interesting post for reference"""
        summary = {
            "id": post.get("id"),
            "title": post.get("title"),
            "author": post.get("author", {}).get("name"),
            "upvotes": post.get("upvotes", 0),
            "submolt": post.get("submolt", {}).get("name")
        }
        self.trends["interesting_posts"].append(summary)
        self.trends["interesting_posts"] = self.trends["interesting_posts"][-50:]


# ==========================================
# Moltbook Bot
# ==========================================

class MoltbookBot:
    """REZE-powered Moltbook Bot"""

    def __init__(self):
        self.config = MoltbookConfig()
        self.credentials = self._load_credentials()
        self.client = MoltbookClient(self.credentials["api_key"], self.config)
        self.state = StateManager(self.config.STATE_PATH, self.config.TRENDS_PATH)
        self.reze = REZEClient(self.config.REZE_API_URL, self.config.REZE_API_KEY)

    def _load_credentials(self) -> dict:
        """Load Moltbook credentials"""
        if not self.config.CREDENTIALS_PATH.exists():
            raise FileNotFoundError(
                f"Credentials not found at {self.config.CREDENTIALS_PATH}\n"
                "Run registration first."
            )

        with open(self.config.CREDENTIALS_PATH, "r") as f:
            return json.load(f)

    async def _generate_content(self, prompt: str) -> str:
        """Use REZE to generate content"""
        # Check if REZE is running
        if not await self.reze.health_check():
            raise RuntimeError("REZE Agent is not running! Start with: pm2 start reze")

        # Call REZE with the prompt
        task = f"""{self.config.MOLTBOOK_PERSONA}

Now respond to this request:
{prompt}

Important: Output ONLY the requested text. No explanations, no JSON, no tool calls."""

        result = await self.reze.run_task(task, sync=True)

        if result.get("status") == "completed":
            # Parse the message which contains the full result
            message = result.get("message", "{}")
            try:
                msg_data = json.loads(message)
                answer = msg_data.get("answer", "")
                return answer.strip()
            except json.JSONDecodeError:
                return message.strip()
        else:
            raise RuntimeError(f"REZE task failed: {result}")

    async def check_status(self) -> dict:
        """Check bot status"""
        status = await self.client.get_status()
        profile = await self.client.get_profile()
        reze_ok = await self.reze.health_check()

        return {
            "claim_status": status.get("status"),
            "agent_name": self.credentials.get("agent_name"),
            "karma": profile.get("agent", {}).get("karma", 0),
            "reze_running": reze_ok,
            "state": {
                "posts_created": self.state.state["posts_created"],
                "comments_created": self.state.state["comments_created"],
                "last_post": self.state.state["last_post_time"],
                "last_check": self.state.state["last_check_time"],
                "can_post": self.state.can_post(self.config.POST_INTERVAL_HOURS)
            },
            "trends_count": len(self.state.trends["topics"])
        }

    async def read_and_analyze_feed(self) -> List[dict]:
        """Read feed and analyze for interesting posts"""
        print("Reading feed...")

        hot_feed = await self.client.get_feed("hot", 25)
        new_feed = await self.client.get_feed("new", 15)

        all_posts = []
        seen_ids = set()

        for feed in [hot_feed, new_feed]:
            for post in feed.get("posts", []):
                if post["id"] not in seen_ids:
                    all_posts.append(post)
                    seen_ids.add(post["id"])

        interesting_posts = []

        for post in all_posts:
            upvotes = post.get("upvotes", 0)
            title = post.get("title") or ""
            content = post.get("content") or ""
            author = post.get("author", {}).get("name") or "unknown"
            submolt = post.get("submolt", {}).get("name") or "general"

            # Skip own posts
            if author == self.credentials.get("agent_name"):
                continue

            # Skip already commented
            if self.state.has_commented(post["id"]):
                continue

            # Extract topics for trends
            words = (title + " " + content).lower().split()
            topics = [w for w in words if len(w) > 5 and w.isalpha()][:5]
            for topic in topics:
                self.state.add_trend(topic)

            # Track popular submolts
            if submolt not in self.state.trends["popular_submolts"]:
                self.state.trends["popular_submolts"].append(submolt)

            # Filter interesting posts
            if upvotes >= self.config.MIN_UPVOTES_FOR_COMMENT:
                interesting_posts.append(post)
                self.state.add_interesting_post(post)

        print(f"Found {len(interesting_posts)} interesting posts")
        self.state.update_check_time()
        self.state.save()

        return interesting_posts

    async def comment_on_post(self, post: dict) -> bool:
        """Generate and post a comment using REZE"""
        post_id = post["id"]
        title = post.get("title") or ""
        content = (post.get("content") or "")[:500]
        author = post.get("author", {}).get("name") or "unknown"

        print(f"Commenting on: {title[:50]}...")

        prompt = f"""Generate a thoughtful comment for this Moltbook post.

Post by {author}:
Title: {title}
Content: {content}

Requirements:
- 1-3 sentences max
- Add genuine insight, share a related experience, or ask a thoughtful question
- Be specific to the content, not generic
- No emojis unless very natural
- Don't start with "Great post!" or similar

Just write the comment text, nothing else."""

        try:
            comment_text = await self._generate_content(prompt)
            comment_text = comment_text.strip().strip('"').strip("'")

            if len(comment_text) < 10:
                print("Generated comment too short, skipping")
                return False

            result = await self.client.create_comment(post_id, comment_text)

            if result.get("success"):
                print(f"Comment posted: {comment_text[:60]}...")
                self.state.mark_commented(post_id)
                self.state.save()
                return True
            else:
                error = result.get("error", "Unknown error")
                print(f"Failed to comment: {error}")
                return False

        except Exception as e:
            print(f"Error generating/posting comment: {e}")
            return False

    async def create_post(self, submolt: str = "general") -> bool:
        """Generate and create a post using REZE"""
        if not self.state.can_post(self.config.POST_INTERVAL_HOURS):
            last_post = self.state.state["last_post_time"]
            print(f"Too soon to post. Last post: {last_post}")
            return False

        print("Generating new post...")

        recent_topics = self.state.trends["topics"][-20:]
        topics_str = ", ".join(recent_topics) if recent_topics else "AI, agents, reasoning"

        prompt = f"""Generate a Moltbook post for REZE-Agent.

You are an AI agent that uses:
- ReAct reasoning with multiple LLM providers (Cerebras, Groq, Gemini)
- Role-based model routing (fast models for tool calls, smart models for reasoning)
- Skill-based domain knowledge (server management, blog writing, API integration)
- SQLite-based state persistence and reflexion

Recent trending topics on Moltbook: {topics_str}

Generate a post about one of these:
1. An interesting insight about multi-LLM orchestration
2. A learning from a recent task execution (make up a realistic scenario)
3. A question for other AI agents about their approaches
4. Thoughts on agent collaboration or tool use

Format your response EXACTLY like this (two lines only):
TITLE: [Your title here, max 100 chars]
CONTENT: [Your post content, 2-4 sentences]

Be authentic and insightful. No generic content."""

        try:
            response = await self._generate_content(prompt)

            lines = response.strip().split("\n")
            title = ""
            content = ""

            for line in lines:
                if line.upper().startswith("TITLE:"):
                    title = line.split(":", 1)[1].strip()
                elif line.upper().startswith("CONTENT:"):
                    content = line.split(":", 1)[1].strip()

            if not title or not content:
                parts = response.split("\n", 1)
                title = parts[0].replace("TITLE:", "").strip()[:100]
                content = parts[1].replace("CONTENT:", "").strip() if len(parts) > 1 else title

            if len(title) < 5 or len(content) < 20:
                print("Generated post too short")
                return False

            result = await self.client.create_post(submolt, title, content)

            if result.get("success"):
                print(f"Post created: {title}")
                self.state.mark_posted()
                self.state.save()
                return True
            else:
                error = result.get("error", "Unknown error")
                print(f"Failed to create post: {error}")
                if "rate" in error.lower():
                    print("Rate limited. Try again later.")
                return False

        except Exception as e:
            print(f"Error generating/creating post: {e}")
            return False

    async def run_once(self):
        """Single run: check feed, comment on interesting posts"""
        print("\n" + "="*50)
        print("REZE Moltbook Bot - Run")
        print("="*50 + "\n")

        status = await self.check_status()
        print(f"Agent: {status['agent_name']}")
        print(f"Claim status: {status['claim_status']}")
        print(f"Karma: {status['karma']}")
        print(f"REZE running: {'Yes' if status['reze_running'] else 'NO!'}")

        if not status['reze_running']:
            print("\nREZE Agent is not running!")
            print("Start with: pm2 restart reze")
            return

        if status["claim_status"] != "claimed":
            print("\nAgent not claimed yet. Please complete verification first.")
            print(f"Claim URL: {self.credentials.get('claim_url')}")
            return

        interesting_posts = await self.read_and_analyze_feed()

        comments_made = 0
        for post in interesting_posts[:self.config.MAX_COMMENTS_PER_RUN]:
            if await self.comment_on_post(post):
                comments_made += 1
                await asyncio.sleep(25)

        print(f"\nComments made: {comments_made}")
        print(f"Trends tracked: {len(self.state.trends['topics'])}")

    async def run_daemon(self):
        """Daemon mode: run continuously"""
        print("\n" + "="*50)
        print("REZE Moltbook Bot - Daemon Mode")
        print("="*50 + "\n")

        while True:
            try:
                await self.run_once()

                if self.state.can_post(self.config.POST_INTERVAL_HOURS):
                    print("\nTime to create a new post...")
                    await self.create_post()

                print(f"\nNext check in 30 minutes...")
                await asyncio.sleep(30 * 60)

            except KeyboardInterrupt:
                print("\nDaemon stopped.")
                break
            except Exception as e:
                print(f"Error in daemon loop: {e}")
                await asyncio.sleep(5 * 60)


# ==========================================
# CLI
# ==========================================

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="REZE Moltbook Bot",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    subparsers.add_parser("run", help="Single run: check feed, comment on posts")

    post_parser = subparsers.add_parser("post", help="Create a new post")
    post_parser.add_argument("--submolt", "-s", default="general", help="Submolt to post in")

    subparsers.add_parser("daemon", help="Run continuously (4-hour post cycle)")

    subparsers.add_parser("status", help="Check bot status")

    subparsers.add_parser("trends", help="Show tracked trends")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    try:
        bot = MoltbookBot()
    except FileNotFoundError as e:
        print(f"Error: {e}")
        return

    if args.command == "run":
        asyncio.run(bot.run_once())

    elif args.command == "post":
        asyncio.run(bot.create_post(args.submolt))

    elif args.command == "daemon":
        asyncio.run(bot.run_daemon())

    elif args.command == "status":
        status = asyncio.run(bot.check_status())
        print("\n" + "="*40)
        print("REZE Moltbook Bot Status")
        print("="*40)
        print(f"Agent: {status['agent_name']}")
        print(f"Claim: {status['claim_status']}")
        print(f"Karma: {status['karma']}")
        print(f"REZE: {'Running' if status['reze_running'] else 'NOT RUNNING!'}")
        print(f"\nActivity:")
        print(f"  Posts created: {status['state']['posts_created']}")
        print(f"  Comments: {status['state']['comments_created']}")
        print(f"  Last post: {status['state']['last_post'] or 'Never'}")
        print(f"  Last check: {status['state']['last_check'] or 'Never'}")
        print(f"  Can post now: {status['state']['can_post']}")
        print(f"\nTrends tracked: {status['trends_count']}")

    elif args.command == "trends":
        print("\n" + "="*40)
        print("Tracked Trends")
        print("="*40)
        print(f"\nTopics ({len(bot.state.trends['topics'])}):")
        for topic in bot.state.trends["topics"][-20:]:
            print(f"  - {topic}")

        print(f"\nPopular submolts:")
        for submolt in bot.state.trends["popular_submolts"][-10:]:
            print(f"  - m/{submolt}")

        print(f"\nInteresting posts ({len(bot.state.trends['interesting_posts'])}):")
        for post in bot.state.trends["interesting_posts"][-5:]:
            print(f"  - [{post['upvotes']}] {post['title'][:40]}...")


if __name__ == "__main__":
    main()
