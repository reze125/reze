"""
REZE 어필리에이트 최적화.

리서치 기반:
- SaaS 어필리에이트가 최고 수익 (recurring commission)
- 자연스러운 삽입이 전환율을 높임 (강제 삽입 역효과)
"""

import json

import logging
logger = logging.getLogger("REZE.affiliate")

# 어필리에이트 프로그램 DB
AFFILIATE_PROGRAMS = {
    # AI Tools
    "jasper": {"url": "https://jasper.ai?ref=REZE", "commission": "30% recurring", "category": "ai_writing"},
    "surfer_seo": {"url": "https://surferseo.com?ref=REZE", "commission": "75% first month", "category": "seo"},
    "copy.ai": {"url": "https://copy.ai?ref=REZE", "commission": "45% recurring", "category": "ai_writing"},
    "frase": {"url": "https://frase.io?ref=REZE", "commission": "30% recurring", "category": "seo"},

    # No-Code Tools
    "zapier": {"url": "https://zapier.com?ref=REZE", "commission": "$5-10/lead", "category": "automation"},
    "make": {"url": "https://make.com?ref=REZE", "commission": "20% recurring", "category": "automation"},
    "airtable": {"url": "https://airtable.com?ref=REZE", "commission": "$10/signup", "category": "database"},
    "notion": {"url": "https://notion.so?ref=REZE", "commission": "50% first year", "category": "productivity"},

    # Hosting/Dev
    "vercel": {"url": "https://vercel.com?ref=REZE", "commission": "25% recurring", "category": "hosting"},
    "hostinger": {"url": "https://hostinger.com?ref=REZE", "commission": "60% sale", "category": "hosting"},
}


class AffiliateOptimizer:

    def __init__(self, call_llm_fn):
        self.call_llm = call_llm_fn

    async def insert_affiliate_links(self, article: dict) -> dict:
        """
        글에 어필리에이트 링크를 자연스럽게 삽입.

        규칙:
        1. 글당 최대 3개 어필리에이트 링크
        2. 리뷰/비교 글은 최대 5개
        3. 강제 삽입 금지 - 언급된 도구만
        4. 각 링크는 가치 있는 문맥에서만
        """
        content = article.get("content", "")
        title = article.get("title", "")

        # 글에서 언급된 도구 찾기
        mentioned_tools = []
        for tool_key, program in AFFILIATE_PROGRAMS.items():
            tool_name = tool_key.replace("_", " ")
            if tool_name.lower() in content.lower() or tool_name.lower() in title.lower():
                mentioned_tools.append({
                    "key": tool_key,
                    "name": tool_name,
                    **program,
                })

        if not mentioned_tools:
            return {"links_inserted": 0, "reason": "No matching tools mentioned"}

        # LLM에게 자연스러운 삽입 위치 요청
        is_comparison = any(w in title.lower() for w in ["vs", "comparison", "compare", "best", "top", "alternative"])
        max_links = 5 if is_comparison else 3

        prompt = f"""
이 블로그 글에 어필리에이트 링크를 자연스럽게 삽입할 위치를 찾아라.

글 제목: {title}
언급된 도구: {json.dumps(mentioned_tools, ensure_ascii=False)}
최대 링크 수: {max_links}

규칙:
- 도구를 처음 언급하는 곳에 링크
- "가격", "시작하기", "무료 체험" 근처가 최적
- 강제로 끼워넣지 마. 자연스럽지 않으면 안 넣어도 됨
- CTA는 "Try X free" 또는 "Get started with X" 형태

JSON:
[
    {{
        "tool": "도구 이름",
        "position": "어디에 넣을지 설명",
        "anchor_text": "링크 텍스트",
        "cta_text": "CTA 텍스트 (선택)"
    }}
]
JSON만 반환.
"""
        result = await self.call_llm(prompt, role="reasoning")

        # JSON 파싱
        text = result.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]

        try:
            placements = json.loads(text.strip())
        except:
            placements = []

        return {
            "links_inserted": len(placements),
            "placements": placements[:max_links],
            "mentioned_tools": [t["name"] for t in mentioned_tools],
        }

    def get_affiliate_url(self, tool_name: str) -> str:
        """도구 이름으로 어필리에이트 URL 반환."""
        tool_key = tool_name.lower().replace(" ", "_")
        program = AFFILIATE_PROGRAMS.get(tool_key)
        if program:
            return program["url"]
        return ""
