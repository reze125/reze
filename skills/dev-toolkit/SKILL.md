---
name: dev-toolkit
description: "개발 도구킷. 코드 리뷰, 버그 수정, 테스트, 배포, Git 워크플로우."
type: meta-skill
triggers:
  - 코드
  - 버그
  - 리팩토링
  - 테스트
  - 배포
  - git
  - deploy
  - code
  - bug
  - refactor
  - test
  - python
  - nextjs
  - typescript
health_checks:
  - name: git_status
    command: "cd /home/reze/reze-agent && git status --porcelain | wc -l"
    verify_check: "int(output) < 50"
fix_actions: []
---

# Dev-Toolkit Meta-Skill

개발 자동화. 코드 품질, 테스트, 배포, Git 워크플로우.

## 핵심 워크플로우

### 코드 리뷰
1. 변경 파일 확인
2. 보안 취약점 체크
3. 코딩 표준 준수 확인
4. 개선 제안

### 버그 수정
1. 에러 로그 분석
2. 원인 파악
3. 최소 변경으로 수정
4. 테스트 확인

### 배포
1. git pull
2. dependencies 설치
3. build
4. pm2/docker 재시작
5. health check 확인

### Git 워크플로우
1. 브랜치 관리
2. 커밋 메시지 표준
3. 충돌 해결

## 안전 규칙
- git force push 금지
- main 브랜치 직접 수정 주의
- 배포 전 반드시 테스트
