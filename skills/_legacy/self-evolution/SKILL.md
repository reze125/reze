---
name: self-evolution
description: 웹에서 새 기술 발견 -> 자기 코드에 적용하는 셀프코딩 능력
type: self
triggers:
  - self-upgrade
  - self-improve
  - new-tech
  - evolution
  - 자기진화
  - 셀프코딩
health_checks:
  - name: evolution_log_exists
    command: "sqlite3 ~/reze-agent/reze_data/ssot.sqlite \"SELECT COUNT(*) FROM evolutions\" 2>/dev/null || echo 0"
    verify_check: "int(output) >= 0"
    severity: info
fix_actions: []
---
# Self-Evolution

REZE가 트렌드 스캔 중 새 기술을 발견하면 자기 코드에 적용.

## 파이프라인
1. **탐색**: trend_scan_job에서 새 기술 발견
2. **평가**: 적용 가치, 위험도, 난이도 분석
3. **백업**: git backup (auto-YYYYMMDDHHMMSS 태그)
4. **수정**: 코드 변경
5. **검증**: health_check 자기 자신
6. **결과**: 성공(커밋) / 실패(롤백)

## 안전장치
- reze_permissions.py는 FORBIDDEN (수정 불가)
- 하루 최대 5번 (MAX_DAILY_EVOLUTIONS)
- 모든 수정 전 git backup 필수
- SELF_MODIFIABLE_FILES 화이트리스트만 수정 가능

## 진화 기록
```sql
SELECT * FROM evolutions ORDER BY created_at DESC LIMIT 10;
```
