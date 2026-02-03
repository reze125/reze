---
name: browser-automation
description: 브라우저 자동화 — Playwright, Puppeteer
type: ops
triggers:
  - browser automation
  - playwright
  - puppeteer
  - headless
health_checks: []
fix_actions: []
---
# Browser Automation

## Tools
- Playwright (Python/Node)
- Puppeteer (Node)
- Selenium

## Use Cases
1. **E2E Testing**: 서비스 테스트
2. **Screenshots**: 도구 스크린샷
3. **Scraping**: JS 렌더링 필요한 페이지

## Playwright Example
```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto("https://example.com")
    page.screenshot(path="screenshot.png")
    browser.close()
```

## Best Practices
1. Headless 모드 사용
2. 타임아웃 설정
3. 에러 핸들링
4. 리소스 정리
