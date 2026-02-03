"""
REZE 블로그 스핀업 파이프라인.

보스가 "이 니치에 블로그 만들어" 하면:
1. Next.js 프로젝트 생성
2. Vercel 배포
3. 스케줄러에 발행 잡 등록
4. 브랜드 컬러/로고 설정

현재는 설계만. 실제 배포는 보스 승인 후.
"""

import json

import logging
logger = logging.getLogger("REZE.spinup")


# 블로그 템플릿
BLOG_TEMPLATE = {
    "framework": "next.js",
    "hosting": "vercel",
    "cms": "markdown + frontmatter",
    "analytics": "vercel analytics",
    "schedule": {"articles_per_week": 6, "publish_hour": 10},
}

# 니치별 브랜드 색상 팔레트
NICHE_COLORS = {
    "ai_tools": "#6366F1",       # 인디고 (AI Tools Lab)
    "nocode": "#10B981",          # 에메랄드 (NoCode Tools Lab)
    "saas_reviews": "#F59E0B",    # 앰버
    "developer_tools": "#3B82F6", # 블루
    "productivity": "#8B5CF6",    # 바이올렛
    "marketing_ai": "#EC4899",    # 핑크
    "data_tools": "#06B6D4",      # 시안
    "design_tools": "#F97316",    # 오렌지
    "finance_tools": "#14B8A6",   # 틸
    "education_tech": "#A855F7",  # 퍼플
}


class BlogSpinup:

    def __init__(self, call_llm_fn, store_signal_fn):
        self.call_llm = call_llm_fn
        self.store_signal = store_signal_fn

    async def propose_new_blog(self, niche: str = "") -> dict:
        """
        새 블로그 제안 생성. 보스 승인 후 실행.
        """
        prompt = f"""
REZE 새 블로그 제안.

현재 블로그: AI Tools Lab, NoCode Tools Lab
{f'요청 니치: {niche}' if niche else '가장 수익성 높은 니치를 추천하라.'}

마스터플랜: 10개 블로그로 확장

분석:
1. 이 니치의 검색 볼륨은?
2. 경쟁 강도는?
3. 어필리에이트 수익 가능성은?
4. 기존 블로그와 시너지는?
5. 6개월 후 예상 월수익?

JSON:
{{
    "niche": "니치명",
    "domain_suggestion": "example-tools-lab.com",
    "brand_name": "브랜드명",
    "target_keywords": ["키워드1", "키워드2", "키워드3"],
    "affiliate_programs": ["프로그램1", "프로그램2"],
    "monthly_articles": 12,
    "estimated_monthly_revenue_6m": "$X",
    "estimated_monthly_revenue_12m": "$X",
    "competition_level": "low|medium|high",
    "synergy_with_existing": "시너지 설명",
    "recommendation": "추천 또는 비추천 이유"
}}
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
            proposal = json.loads(text.strip())
        except:
            proposal = {"raw": result[:500]}

        # 색상 자동 배정
        niche_key = proposal.get("niche", "").lower().replace(" ", "_")
        proposal["brand_color"] = NICHE_COLORS.get(niche_key, "#6366F1")

        self.store_signal("blog_proposal", json.dumps(proposal, ensure_ascii=False))

        return proposal

    async def generate_spinup_plan(self, proposal: dict) -> dict:
        """
        블로그 생성 실행 계획 생성.
        실제 실행은 Claude Code에 전달.
        """
        domain = proposal.get('domain_suggestion', 'new-blog').replace('.com', '')

        plan = {
            "steps": [
                {
                    "step": 1,
                    "action": "Next.js 프로젝트 생성",
                    "command": f"npx create-next-app@latest {domain} --typescript --tailwind --eslint --app",
                },
                {
                    "step": 2,
                    "action": "Vercel 배포",
                    "command": "vercel deploy --prod",
                },
                {
                    "step": 3,
                    "action": "자동 발행 스케줄 등록",
                    "details": f"주 {proposal.get('monthly_articles', 12) // 4}개 발행 크론잡",
                },
                {
                    "step": 4,
                    "action": "브랜드 설정",
                    "color": proposal.get("brand_color", "#6366F1"),
                    "name": proposal.get("brand_name", ""),
                },
            ],
            "proposal": proposal,
        }

        self.store_signal("blog_spinup_plan", json.dumps(plan, ensure_ascii=False))

        return plan
