"""
REZE SEO 최적화 엔진.

2026 SEO 3축:
1. Traditional SEO (Google 검색)
2. GEO (Generative Engine Optimization - ChatGPT/Perplexity 노출)
3. AEO (Answer Engine Optimization - AI Overview/Featured Snippet)

리서치 기반:
- AI Overview가 클릭을 30% 줄이고 있음
- 구조화된 데이터(Schema.org)가 AI 인용의 핵심
- 내부링크 자동화가 SEO 순위에 직접 영향
"""

import json

import logging
logger = logging.getLogger("REZE.seo")


class SEOOptimizer:

    def __init__(self, call_llm_fn, get_db_fn):
        self.call_llm = call_llm_fn
        self.get_db = get_db_fn

    async def optimize_article(self, article: dict) -> dict:
        """
        블로그 글을 SEO 최적화.

        article = {
            "title": str,
            "content": str (markdown),
            "target_keyword": str,
            "blog": "aitools" | "nocode",
        }

        Returns: {
            "optimized_title": str,
            "meta_description": str,
            "faq": list,
            "internal_links": list,
            "seo_score": int (0-100),
        }
        """
        # 기존 글 목록에서 내부링크 후보 가져오기
        internal_links = await self._get_internal_link_candidates(article.get("blog", ""))

        prompt = f"""
SEO 최적화 전문가. 2026년 기준으로 이 글을 최적화하라.

=== 원본 ===
제목: {article['title']}
키워드: {article.get('target_keyword', '')}
글 (처음 3000자):
{article['content'][:3000]}

=== 2026 SEO 요구사항 ===
1. **Traditional SEO**
   - 키워드를 제목, H2, 첫 문단, 마지막 문단에 자연스럽게 배치
   - 메타 디스크립션 155자 이내, 키워드 포함
   - H2/H3 구조 최적화

2. **GEO (Generative Engine Optimization)**
   - ChatGPT/Perplexity가 인용할 수 있는 "사실 문장" 포함
   - "X is Y" 형태의 명확한 정의 문장 추가
   - 비교표, 수치, 통계 포함 (AI가 인용하기 좋음)

3. **AEO (Answer Engine Optimization)**
   - FAQ 섹션 추가 (최소 3개 Q&A)
   - "What is X?", "How does X work?" 형태
   - Google Featured Snippet 대응

4. **내부링크**
   가능한 내부링크 후보: {json.dumps(internal_links[:10], ensure_ascii=False)}
   이 중 관련 있는 글에 자연스럽게 링크

JSON 응답:
{{
    "optimized_title": "SEO 최적화된 제목",
    "meta_description": "155자 이내",
    "content_improvements": [
        "개선 1: ...",
        "개선 2: ..."
    ],
    "faq": [
        {{"q": "질문", "a": "답변"}}
    ],
    "internal_links": [
        {{"anchor_text": "앵커텍스트", "url": "/slug", "context": "어디에 넣을지"}}
    ],
    "schema_type": "Article|HowTo|FAQ",
    "seo_score": 0-100,
    "geo_tips": ["AI 엔진 최적화 팁"]
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
            return json.loads(text.strip())
        except:
            return {"seo_score": 0, "error": "parsing failed"}

    async def _get_internal_link_candidates(self, blog: str) -> list[dict]:
        """기존 발행된 글 목록에서 내부링크 후보 추출."""
        db = self.get_db()

        published = db.execute(
            """SELECT data FROM signals
               WHERE kind = 'blog_published'
               AND data LIKE ?
               ORDER BY created_at DESC LIMIT 30""",
            (f'%{blog}%',)
        ).fetchall()

        candidates = []
        for row in published:
            try:
                data = json.loads(row[0])
                candidates.append({
                    "title": data.get("title", ""),
                    "slug": data.get("slug", ""),
                    "keyword": data.get("keyword", ""),
                })
            except:
                pass

        return candidates

    async def generate_schema_markup(self, article: dict, seo_result: dict) -> str:
        """JSON-LD Schema.org 마크업 생성."""
        schema_type = seo_result.get("schema_type", "Article")

        if schema_type == "FAQ":
            faq_items = seo_result.get("faq", [])
            schema = {
                "@context": "https://schema.org",
                "@type": "FAQPage",
                "mainEntity": [
                    {
                        "@type": "Question",
                        "name": item["q"],
                        "acceptedAnswer": {
                            "@type": "Answer",
                            "text": item["a"]
                        }
                    }
                    for item in faq_items
                ]
            }
        else:
            schema = {
                "@context": "https://schema.org",
                "@type": "Article",
                "headline": seo_result.get("optimized_title", article.get("title", "")),
                "description": seo_result.get("meta_description", ""),
                "author": {
                    "@type": "Organization",
                    "name": "AI Tools Lab" if article.get("blog") == "aitools" else "NoCode Tools Lab"
                },
            }

        return json.dumps(schema, ensure_ascii=False, indent=2)
