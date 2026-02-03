---
name: python
description: Python 개발 — FastAPI, 라이브러리, 가상환경
type: dev
triggers:
  - python
  - fastapi
  - pip
  - venv
  - 파이썬
health_checks:
  - name: python_version
    command: "python3 --version"
    expect: "Python 3"
    severity: info
fix_actions: []
---
# Python Development

## Environment
- Version: Python 3.12.3
- Package Manager: pip

## FastAPI Projects
| Project | Path | Port |
|---------|------|------|
| reze-agent | ~/reze-agent | 8300 |
| quotepilot | ~/quotepilot/backend | 8030 |
| browserpilot | ~/browserpilot/backend | 8100 |
| agenthub | ~/agenthub/backend | 8101 |
| rag-service | ~/rag-service/backend | 8020 |

## Common Commands
```bash
# 가상환경
python3 -m venv venv
source venv/bin/activate

# 패키지 관리
pip install -r requirements.txt
pip freeze > requirements.txt

# 실행
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

## Code Standards
- Type hints 사용
- Black formatter
- isort for imports
- pytest for testing
