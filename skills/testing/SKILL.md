---
name: testing
description: 테스트 — pytest, jest, E2E
type: dev
triggers:
  - test
  - 테스트
  - pytest
  - jest
  - unit test
health_checks: []
fix_actions: []
---
# Testing

## Python (pytest)
```bash
# 실행
pytest
pytest tests/test_api.py -v
pytest -k "test_login"

# 커버리지
pytest --cov=src --cov-report=html
```

## JavaScript (jest)
```bash
npm test
npm run test:coverage
```

## Test Structure
```
tests/
  unit/
    test_utils.py
  integration/
    test_api.py
  e2e/
    test_flow.py
```

## Best Practices
1. 테스트 이름은 명확하게 (test_user_login_success)
2. Arrange-Act-Assert 패턴
3. 외부 의존성은 mock
4. CI에서 자동 실행
