---
name: web-scraping
description: 웹 스크래핑 — 데이터 수집, 파싱
type: ops
triggers:
  - scraping
  - 스크래핑
  - crawl
  - 크롤링
  - parse
health_checks: []
fix_actions: []
---
# Web Scraping

## Libraries
- Python: requests, BeautifulSoup, Scrapy
- Node.js: Puppeteer, Cheerio

## Use Cases
1. **Competitor pricing**: 가격 모니터링
2. **Tool info**: 기능, 리뷰 수집
3. **News**: AI 뉴스 수집

## Best Practices
1. robots.txt 준수
2. Rate limiting
3. User-Agent 설정
4. 캐싱

## Example
```python
import requests
from bs4 import BeautifulSoup

resp = requests.get(url, headers={"User-Agent": "..."})
soup = BeautifulSoup(resp.text, "html.parser")
```
