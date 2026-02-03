---
name: git
description: Git 버전 관리 — 커밋, 브랜치, 태그
type: dev
triggers:
  - git
  - commit
  - branch
  - 깃
  - version control
health_checks: []
fix_actions: []
---
# Git Version Control

## Common Commands
```bash
# 상태
git status
git log --oneline -10
git diff

# 커밋
git add -A
git commit -m "message"

# 브랜치
git branch
git checkout -b feature/name
git merge feature/name

# 태그
git tag v1.0.0
git tag -l 'v*'

# 원격
git push origin main
git pull origin main
```

## Commit Message Convention
```
feat: 새 기능
fix: 버그 수정
refactor: 리팩토링
docs: 문서
chore: 설정/빌드
```

## Backup Tags
- v3.3-pre-universal: Phase 1 시작 전
- v3.3-universal-p1: Phase 1 완료
- auto-YYYYMMDDHHMMSS: 자동 백업

## Repositories
| Repo | Path |
|------|------|
| reze-agent | ~/reze-agent |
| ai-tools-lab | ~/ai-tools-lab |
