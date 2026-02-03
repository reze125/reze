"""
REZE 입력 소스 확장.
6개 무료 소스에서 AI/노코드/SaaS 트렌드를 수집한다.

소스별 특성:
- HackerNews: 개발자 커뮤니티 (기술 트렌드, 라이브러리)
- GitHub Trending: 코드 트렌드 (새 프레임워크, 도구)
- RSS: 특정 블로그/뉴스 (TechCrunch AI, The Verge AI)
"""

import aiohttp
import asyncio
import json
import re
from datetime import datetime

import logging
logger = logging.getLogger("REZE.sources")

# HackerNews (완전 무료, 인증 불필요)
HN_TOP_URL = "https://hacker-news.firebaseio.com/v0/topstories.json"
HN_ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{}.json"

# AI/SaaS 관련 키워드 필터
AI_KEYWORDS = [
    "ai", "llm", "gpt", "claude", "gemini", "openai", "anthropic",
    "automation", "no-code", "nocode", "low-code", "saas", "agent",
    "rag", "vector", "embedding", "fine-tune", "fine-tuning",
    "nextjs", "vercel", "supabase", "dify", "n8n", "langchain",
    "fastapi", "python", "typescript", "react",
    "seo", "affiliate", "blogging", "content",
]


async def fetch_hackernews(limit: int = 30) -> list[dict]:
    """
    HackerNews top stories에서 AI/SaaS 관련 글만 필터링.

    API: https://hacker-news.firebaseio.com/v0/
    인증: 불필요
    제한: 없음 (합리적 사용)

    Returns: [{"title": str, "url": str, "score": int, "source": "hackernews"}]
    """
    results = []
    try:
        async with aiohttp.ClientSession() as session:
            # top stories ID 가져오기
            async with session.get(HN_TOP_URL, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return []
                story_ids = await resp.json()

            # 상위 N개만 가져오기
            for story_id in story_ids[:limit]:
                try:
                    url = HN_ITEM_URL.format(story_id)
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status != 200:
                            continue
                        item = await resp.json()

                    if not item or item.get("type") != "story":
                        continue

                    title = (item.get("title") or "").lower()

                    # AI/SaaS 키워드 필터
                    if any(kw in title for kw in AI_KEYWORDS):
                        results.append({
                            "title": item.get("title", ""),
                            "url": item.get("url", f"https://news.ycombinator.com/item?id={story_id}"),
                            "score": item.get("score", 0),
                            "comments": item.get("descendants", 0),
                            "source": "hackernews",
                            "source_id": str(story_id),
                            "discovered_at": datetime.now().isoformat(),
                        })
                except Exception:
                    continue

            logger.info(f"HackerNews: {len(results)} AI/SaaS stories from top {limit}")
    except Exception as e:
        logger.error(f"HackerNews fetch failed: {e}")

    return results


async def fetch_github_trending(language: str = "", since: str = "daily") -> list[dict]:
    """
    GitHub Trending 페이지를 스크래핑.

    URL: https://github.com/trending?since=daily
    인증: 불필요
    제한: 합리적 사용 (하루 3회 이하)

    Returns: [{"title": str, "url": str, "description": str, "stars": int, "source": "github_trending"}]
    """
    results = []
    try:
        url = f"https://github.com/trending/{language}?since={since}"

        async with aiohttp.ClientSession() as session:
            headers = {"User-Agent": "REZE-Agent/3.3 (trend scanner)"}
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status != 200:
                    return []
                html = await resp.text()

        # HTML 파싱 (regex)
        repos = re.findall(r'<article class="Box-row">(.*?)</article>', html, re.DOTALL)

        for repo_html in repos[:20]:
            # repo 이름 추출
            href_match = re.search(r'<a href="(/[^"]+)"', repo_html)
            if not href_match:
                continue

            repo_path = href_match.group(1).strip()
            repo_name = repo_path.split("/")[-1] if "/" in repo_path else repo_path

            # 설명 추출
            desc_match = re.search(r'<p class="col-9[^"]*"[^>]*>\s*(.*?)\s*</p>', repo_html, re.DOTALL)
            description = desc_match.group(1).strip() if desc_match else ""
            description = re.sub(r'<[^>]+>', '', description).strip()

            # 스타 추출
            star_match = re.search(r'(\d[\d,]*)\s*stars?\s*today', repo_html, re.IGNORECASE)
            stars_today = int(star_match.group(1).replace(",", "")) if star_match else 0

            # AI/SaaS 키워드 필터
            text = f"{repo_name} {description}".lower()
            if any(kw in text for kw in AI_KEYWORDS):
                results.append({
                    "title": repo_name,
                    "url": f"https://github.com{repo_path}",
                    "description": description[:300],
                    "stars_today": stars_today,
                    "source": "github_trending",
                    "discovered_at": datetime.now().isoformat(),
                })

        logger.info(f"GitHub Trending: {len(results)} AI/SaaS repos")
    except Exception as e:
        logger.error(f"GitHub Trending fetch failed: {e}")

    return results


# RSS Feeds (무료)
RSS_FEEDS = [
    "https://techcrunch.com/category/artificial-intelligence/feed/",
    "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "https://www.searchenginejournal.com/feed/",
]


async def fetch_rss_feeds() -> list[dict]:
    """
    RSS 피드에서 AI/SaaS 관련 기사 수집.
    XML 파싱은 간단한 regex로 처리.

    Returns: [{"title": str, "url": str, "source": "rss", "feed": str}]
    """
    results = []

    async with aiohttp.ClientSession() as session:
        for feed_url in RSS_FEEDS:
            try:
                async with session.get(
                    feed_url,
                    headers={"User-Agent": "REZE-Agent/3.3"},
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    if resp.status != 200:
                        continue
                    xml = await resp.text()

                # 간단한 RSS 파싱
                items = re.findall(r'<item>(.*?)</item>', xml, re.DOTALL)
                if not items:
                    items = re.findall(r'<entry>(.*?)</entry>', xml, re.DOTALL)

                for item_xml in items[:10]:
                    title_match = re.search(r'<title[^>]*>(.*?)</title>', item_xml, re.DOTALL)
                    link_match = re.search(r'<link[^>]*>(.*?)</link>', item_xml, re.DOTALL)
                    if not link_match:
                        link_match = re.search(r'<link[^>]*href="([^"]+)"', item_xml)

                    if not title_match:
                        continue

                    title = re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', title_match.group(1)).strip()
                    title = re.sub(r'<[^>]+>', '', title).strip()

                    link = ""
                    if link_match:
                        link = link_match.group(1).strip()
                        link = re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', link)

                    # AI 키워드 필터
                    if any(kw in title.lower() for kw in AI_KEYWORDS[:15]):
                        results.append({
                            "title": title,
                            "url": link,
                            "source": "rss",
                            "feed": feed_url.split("/")[2],
                            "discovered_at": datetime.now().isoformat(),
                        })
            except Exception as e:
                logger.warning(f"RSS feed failed {feed_url}: {e}")

    logger.info(f"RSS: {len(results)} AI/SaaS articles from {len(RSS_FEEDS)} feeds")
    return results


def classify_discovery(item: dict) -> str:
    """소스와 내용 기반으로 발견 유형 자동 분류."""
    title = (item.get("title", "") + " " + item.get("description", "")).lower()
    source = item.get("source", "")

    # 자기 개선 기술 (즉시 검증 대상)
    if source == "github_trending" and any(kw in title for kw in [
        "fastapi", "uvloop", "orjson", "asyncio", "sqlite", "qdrant", "embedding"
    ]):
        return "self_improvement_tech"

    # 새 도구/제품 (블로그 글감)
    if source in ("producthunt", "rss") or "launch" in title or "new" in title:
        return "new_tool_discovered"

    # 경쟁사 동향
    if any(kw in title for kw in ["zapier", "make.com", "jasper", "writesonic", "copy.ai"]):
        return "competitor_response"

    # SEO 변화
    if any(kw in title for kw in ["google", "seo", "algorithm", "ranking", "search"]):
        return "seo_change"

    # 키워드 기회
    if any(kw in title for kw in ["vs", "alternative", "best", "top", "review", "comparison"]):
        return "keyword_opportunity"

    # 기본
    return "new_tool_discovered"


async def collect_all_sources() -> list[dict]:
    """
    모든 소스에서 발견을 수집하고 중복 제거.
    trend_scan_job에서 호출.
    """
    # 병렬 수집
    hn_task = fetch_hackernews(limit=30)
    gh_task = fetch_github_trending(since="daily")
    rss_task = fetch_rss_feeds()

    hn_results, gh_results, rss_results = await asyncio.gather(
        hn_task, gh_task, rss_task,
        return_exceptions=True
    )

    all_results = []
    for result_set in [hn_results, gh_results, rss_results]:
        if isinstance(result_set, list):
            all_results.extend(result_set)

    # 중복 제거 (URL 기반)
    seen_urls = set()
    unique = []
    for item in all_results:
        url = item.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique.append(item)

    logger.info(f"Total collected: {len(unique)} unique items from all sources")
    return unique
