"""
REZE Self-Evolution Engine.
새 기술 발견 시 자기 코드에 적용하는 셀프코딩 능력.
"""

import subprocess
import json
import time
from datetime import datetime
from pathlib import Path

import logging
logger = logging.getLogger("REZE.evolution")

REZE_ROOT = Path.home() / "reze-agent"


class SelfEvolution:

    def __init__(self, call_llm_fn, store_signal_fn, get_db_fn):
        """
        call_llm_fn: LLM 호출 함수 (async)
        store_signal_fn: ssot의 save_signal 함수
        get_db_fn: ssot의 _get_db 함수
        """
        self.call_llm = call_llm_fn
        self.store_signal = store_signal_fn
        self.get_db = get_db_fn

    async def evaluate(self, tech_info: dict) -> dict:
        """
        새 기술의 적용 가치를 평가.

        tech_info = {
            "name": "uvloop",
            "description": "asyncio 대체, 2배 빠름",
            "source": "trend_scan"
        }

        Returns: {"should_apply": bool, "reason": str, "steps": [...], ...}
        """
        self_analysis = self._analyze_self()

        prompt = f"""
나는 REZE. 자율형 AI 에이전트.
새 기술을 발견했다. 나한테 적용할 가치가 있는지 판단하라.

=== 발견한 기술 ===
이름: {tech_info['name']}
설명: {tech_info.get('description', '')}

=== 현재 내 스택 ===
Python 파일: {self_analysis['python_files']}
의존성: {self_analysis['dependencies'][:20]}
총 코드: {self_analysis['total_lines']}줄
현재 스택: FastAPI, APScheduler, aiohttp, SQLite, loguru

=== 판단 기준 ===
1. 이 기술이 나한테 적용 가능한가?
2. 적용하면 뭐가 나아지는가? (성능? 비용? 새 능력?)
3. 위험은? (호환성? 안정성?)
4. 구현 난이도는?

JSON 응답:
{{
    "should_apply": true/false,
    "reason": "판단 근거",
    "benefit": "기대 효과",
    "risk_level": "low|medium|high",
    "risk_detail": "위험 요소",
    "affected_files": ["file1.py"],
    "steps": [
        {{"action": "pip install uvloop --break-system-packages", "type": "shell"}},
        {{"action": "reze_daemon.py에 uvloop.install() 추가", "type": "code_edit", "file": "reze_daemon.py", "description": "변경 설명"}}
    ],
    "benchmark": {{
        "metric": "api_response_ms",
        "command": "curl -w '%{{time_total}}' -s -o /dev/null http://localhost:8888/health"
    }}
}}

적용할 가치 없으면 should_apply: false.
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
            evaluation = json.loads(text.strip())
        except:
            evaluation = {"should_apply": False, "reason": "LLM 응답 파싱 실패"}

        # evolutions 테이블에 기록
        db = self.get_db()
        db.execute(
            """INSERT INTO evolutions
               (tech_name, tech_description, source, evaluation, autonomy_level, status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                tech_info["name"],
                tech_info.get("description", ""),
                tech_info.get("source", "unknown"),
                json.dumps(evaluation, ensure_ascii=False),
                "auto" if evaluation.get("risk_level") != "high" else "review",
                "evaluated"
            )
        )
        db.commit()

        return evaluation

    async def evolve(self, tech_info: dict, evaluation: dict) -> dict:
        """
        실제 자기 진화.
        git backup → 벤치마크(before) → 코드 수정 → health_check → 벤치마크(after) → 성공/롤백
        """
        from reze_permissions import FORBIDDEN_FILES, MAX_DAILY_EVOLUTIONS

        db = self.get_db()

        # 일일 한도 체크
        today = datetime.now().strftime("%Y-%m-%d")
        today_count = db.execute(
            "SELECT COUNT(*) FROM evolutions WHERE status IN ('success','failed') AND created_at LIKE ?",
            (f"{today}%",)
        ).fetchone()[0]

        if today_count >= MAX_DAILY_EVOLUTIONS:
            return {"success": False, "reason": f"일일 한도 ({today_count}/{MAX_DAILY_EVOLUTIONS})"}

        # FORBIDDEN 파일 체크
        for f in evaluation.get("affected_files", []):
            for forbidden in FORBIDDEN_FILES:
                if forbidden in f:
                    return {"success": False, "reason": f"FORBIDDEN: {f}"}

        # 1. Git Backup
        tag = f"auto-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        self._git_backup(tag, f"pre-evolution: {tech_info['name']}")

        # 2. 벤치마크 Before
        benchmark_cmd = evaluation.get("benchmark", {}).get("command", "")
        perf_before = self._benchmark(benchmark_cmd)

        # evolution ID 가져오기 (가장 최근 evaluated 상태인 것)
        evo_row = db.execute(
            "SELECT id FROM evolutions WHERE tech_name=? AND status='evaluated' ORDER BY created_at DESC LIMIT 1",
            (tech_info["name"],)
        ).fetchone()
        evolution_id = evo_row[0] if evo_row else None

        try:
            # 3. 코드 수정 실행
            step_results = []
            for step in evaluation.get("steps", []):
                result = await self._execute_step(step)
                step_results.append(result)
                if not result.get("ok"):
                    raise Exception(f"Step failed: {step['action']}: {result.get('error', '')}")

            # 4. Health Check
            if not self._health_check():
                raise Exception("health_check failed after evolution")

            # 5. 벤치마크 After
            perf_after = self._benchmark(benchmark_cmd)

            # 6. 성공: 커밋
            self._git_commit(f"feat(self-evolution): {tech_info['name']}")

            if evolution_id:
                db.execute(
                    """UPDATE evolutions SET
                       status='success', git_backup_tag=?,
                       changes=?, test_results=?,
                       performance_before=?, performance_after=?,
                       completed_at=datetime('now')
                       WHERE id=?""",
                    (tag, json.dumps(step_results, ensure_ascii=False),
                     json.dumps({"health": "passed"}),
                     str(perf_before), str(perf_after), evolution_id)
                )
                db.commit()

            # 즉시 교훈 생성
            await self._generate_lesson(tech_info, perf_before, perf_after)

            self.store_signal("self_evolution_success", json.dumps({
                "tech": tech_info["name"],
                "before": perf_before,
                "after": perf_after,
                "tag": tag
            }))

            logger.info(f"Evolution SUCCESS: {tech_info['name']} ({perf_before} -> {perf_after})")
            return {"success": True, "tech": tech_info["name"],
                    "before": perf_before, "after": perf_after, "tag": tag}

        except Exception as e:
            # 롤백
            logger.error(f"Evolution FAILED: {tech_info['name']}: {e}")
            self._rollback(tag)

            if evolution_id:
                db.execute(
                    """UPDATE evolutions SET
                       status='failed', git_backup_tag=?,
                       test_results=?, completed_at=datetime('now')
                       WHERE id=?""",
                    (tag, json.dumps({"error": str(e)}), evolution_id)
                )
                db.commit()

            self.store_signal("self_evolution_failed", json.dumps({
                "tech": tech_info["name"],
                "error": str(e),
                "rolled_back_to": tag
            }))

            # 실패에서도 교훈
            self.store_signal("lesson_learned", json.dumps({
                "lesson": f"[진화실패] {tech_info['name']}: {str(e)[:200]}",
                "source": "self_evolution",
                "effective": False
            }))

            return {"success": False, "error": str(e), "rolled_back_to": tag}

    async def evaluate_and_evolve(self, tech_info: dict) -> dict:
        """평가 + 진화를 한 번에. trend_scan에서 호출."""

        evaluation = await self.evaluate(tech_info)

        if not evaluation.get("should_apply"):
            logger.info(f"Evolution SKIP: {tech_info['name']} - {evaluation.get('reason')}")
            return {"skipped": True, "reason": evaluation.get("reason")}

        if evaluation.get("risk_level") == "high":
            # 고위험은 보스에게 제안만
            from reze_daemon import request_approval
            await request_approval(
                action=f"자기 진화: {tech_info['name']}",
                reason=evaluation.get("reason", ""),
                analysis=f"위험: {evaluation.get('risk_detail', '')}"
            )
            return {"proposed": True, "reason": "high risk - 보스 승인 필요"}

        return await self.evolve(tech_info, evaluation)

    # 내부 함수들

    def _analyze_self(self) -> dict:
        """자기 코드 분석."""
        py_files = list(REZE_ROOT.glob("*.py"))
        deps = []
        req = REZE_ROOT / "requirements.txt"
        if req.exists():
            deps = [l.strip().split("==")[0] for l in req.read_text().splitlines()
                    if l.strip() and not l.startswith("#")]

        total_lines = 0
        for f in py_files:
            try:
                total_lines += len(f.read_text().splitlines())
            except:
                pass

        return {
            "python_files": [f.name for f in py_files],
            "dependencies": deps,
            "total_lines": total_lines,
        }

    def _benchmark(self, command: str) -> str:
        """벤치마크 실행. 3회 평균."""
        if not command:
            return "N/A"
        try:
            values = []
            for _ in range(3):
                r = subprocess.run(
                    ["bash", "-c", command],
                    capture_output=True, text=True, timeout=30
                )
                values.append(r.stdout.strip())
                time.sleep(0.3)
            return f"avg({','.join(values)})"
        except:
            return "benchmark_failed"

    def _git_backup(self, tag: str, message: str):
        subprocess.run(["git", "add", "-A"], cwd=str(REZE_ROOT), capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", message, "--allow-empty"],
            cwd=str(REZE_ROOT), capture_output=True
        )
        subprocess.run(["git", "tag", tag], cwd=str(REZE_ROOT), capture_output=True)

    def _git_commit(self, message: str):
        subprocess.run(["git", "add", "-A"], cwd=str(REZE_ROOT), capture_output=True)
        subprocess.run(["git", "commit", "-m", message], cwd=str(REZE_ROOT), capture_output=True)

    def _rollback(self, tag: str):
        subprocess.run(["git", "checkout", tag, "--", "."], cwd=str(REZE_ROOT), capture_output=True)
        subprocess.run(["pm2", "restart", "reze-daemon"], capture_output=True)
        logger.warning(f"Rolled back to {tag}")

    def _health_check(self) -> bool:
        """PM2 restart 후 REZE가 살아있는지 확인."""
        try:
            subprocess.run(["pm2", "restart", "reze-daemon"], capture_output=True, timeout=30)
            time.sleep(5)  # 부팅 대기
            r = subprocess.run(
                ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                 "--max-time", "15", "http://localhost:8888/health"],
                capture_output=True, text=True, timeout=20
            )
            return r.stdout.strip() == "200"
        except:
            return False

    async def _execute_step(self, step: dict) -> dict:
        """진화 단계 하나 실행."""
        step_type = step.get("type", "shell")

        if step_type == "shell":
            try:
                r = subprocess.run(
                    ["bash", "-c", step["action"]],
                    capture_output=True, text=True, timeout=120,
                    cwd=str(REZE_ROOT)
                )
                return {"ok": r.returncode == 0, "output": r.stdout[:500], "error": r.stderr[:500]}
            except Exception as e:
                return {"ok": False, "error": str(e)}

        elif step_type == "code_edit":
            target = REZE_ROOT / step.get("file", "")
            if not target.exists():
                return {"ok": False, "error": f"File not found: {step.get('file')}"}

            current = target.read_text()

            new_code = await self.call_llm(
                f"""다음 파일을 수정하라.
파일: {step['file']}
수정: {step.get('description', step['action'])}
현재 코드:
```python
{current[:8000]}
```

수정된 전체 파일만 출력. 설명 없이. ```python``` 블록으로.
기존 기능 깨뜨리지 마. 최소한의 변경만.""",
                role="coding"
            )

            # 코드 블록 추출
            if "```python" in new_code:
                code = new_code.split("```python")[1].split("```")[0]
            elif "```" in new_code:
                code = new_code.split("```")[1].split("```")[0]
            else:
                code = new_code

            if code.strip():
                target.write_text(code.strip() + "\n")
                return {"ok": True, "output": f"Modified {step['file']}"}
            return {"ok": False, "error": "Empty code generated"}

        return {"ok": False, "error": f"Unknown step type: {step_type}"}

    async def _generate_lesson(self, tech_info: dict, before: str, after: str):
        """성공 즉시 교훈 생성."""
        lesson = await self.call_llm(
            f"""REZE 자기 진화 결과를 한 줄 교훈으로 만들어라.
기술: {tech_info['name']}
변경 전: {before}
변경 후: {after}
형식: "[카테고리] 교훈 (수치 포함)"
예시: "[성능] uvloop 적용 시 API 응답 51% 개선"
""",
            role="reasoning"
        )
        self.store_signal("lesson_learned", json.dumps({
            "lesson": lesson.strip(),
            "source": "self_evolution",
            "tech": tech_info["name"],
            "effective": True
        }))
