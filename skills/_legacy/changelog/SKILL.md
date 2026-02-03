---
name: changelog
description: 변경 로그 — 버전, 업데이트 기록
type: ops
triggers:
  - changelog
  - 변경로그
  - version
  - 버전
  - release
health_checks: []
fix_actions: []
---
# Changelog

## REZE Versions
| Version | Date | Changes |
|---------|------|---------|
| v3.3-universal-p1 | 2026-02-03 | 62 skills, safety, blog quality gate |
| v3.3-pre-universal | 2026-02-03 | Backup before Phase 1 |
| v3.3 | 2026-02-02 | Initial v3.3 |

## Changelog Format
```markdown
## [Version] - YYYY-MM-DD

### Added
- New feature

### Changed
- Modified behavior

### Fixed
- Bug fix

### Removed
- Deprecated feature
```

## Git Tags
```bash
# 버전 태그 생성
git tag v3.3.1 -m "Description"
git push origin v3.3.1

# 태그 목록
git tag -l 'v*'
```
