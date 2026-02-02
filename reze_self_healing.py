"""REZE Self-Healing — L1.5 규칙 기반 + L2 LLM 진단. fix → verify → report."""
import re
import json
import asyncio
import logging

logger = logging.getLogger("REZE.self_healing")

# PM2 서비스 → 포트 매핑 (실제 서버 기반)
PM2_SERVICES = {
    "postpilot-backend": 8000,
    "postpilot-frontend": 3000,
    "ai-tools-lab": 3005,
    "browserpilot-api": 8100,
    "agenthub-api": 8101,
    "rag-service": 8020,
    "quotepilot-api": 8030,
    "rapidapi-server": 8001,
    "rapidapi-nocode": 8002,
}

# L1.5 규칙: 패턴 → fix + verify
KNOWN_FIXES = [
    {
        "name": "pm2_service_down",
        "pattern": r"(?P<name>[\w-]+)\(unreachable\)",
        "fix": "pm2 restart {name}",
        "verify": "curl -sf http://localhost:{port}/health -o /dev/null && echo OK || echo FAIL",
        "verify_expect": "OK",
        "cooldown_key": "restart_{name}",
    },
    {
        "name": "docker_oom",
        "pattern": r"(?P<container>[\w-]+).*(?:OOM|out of memory|Exited)",
        "fix": "docker restart {container}",
        "verify": "docker inspect --format='{{{{.State.Running}}}}' {container}",
        "verify_expect": "true",
        "cooldown_key": "docker_{container}",
    },
    {
        "name": "disk_full",
        "pattern": r"(?P<pct>9[0-9])%\s",
        "fix": "docker system prune -f --volumes 2>/dev/null; find /tmp -type f -mtime +7 -delete 2>/dev/null; echo done",
        "verify": "df / --output=pcent | tail -1 | tr -d ' %'",
        "verify_check": "int(output) < 90",
        "cooldown_key": "disk_prune",
    },
    {
        "name": "ssl_expiry",
        "pattern": r"certificate.*(?:expir|INVALID)",
        "fix": "certbot renew --nginx --quiet",
        "verify": "certbot certificates 2>/dev/null | grep -c VALID",
        "verify_check": "int(output) > 0",
        "cooldown_key": "certbot",
    },
]


class SelfHealing:
    """L1.5 규칙 기반 자가 치유. dry_run=True면 기록만."""

    MAX_PER_DAY = 3       # 동일 규칙 하루 3회 제한
    VERIFY_WAIT = 10      # fix 후 verify까지 대기(초)

    def __init__(self, tool_executor, ssot, router=None, dry_run=True):
        self.executor = tool_executor
        self.ssot = ssot
        self.router = router      # L2 LLM 진단용
        self.dry_run = dry_run

    async def handle(self, error_text: str, context: dict = None) -> dict:
        """에러 텍스트 분석 → 매칭 → fix → verify → report."""
        for rule in KNOWN_FIXES:
            match = re.search(rule["pattern"], error_text, re.IGNORECASE)
            if not match:
                continue

            groups = match.groupdict()

            # name → port 매핑
            if "name" in groups and groups["name"] in PM2_SERVICES:
                groups["port"] = str(PM2_SERVICES[groups["name"]])
            elif "name" in groups:
                groups["port"] = "80"

            fix_cmd = rule["fix"].format(**groups)
            cooldown_key = rule["cooldown_key"].format(**groups)

            # 쿨다운 체크
            if self._over_cooldown(cooldown_key):
                logger.info(f"Self-heal cooldown: {cooldown_key}")
                return {"action": "cooldown", "key": cooldown_key, "rule": rule["name"]}

            # dry-run
            if self.dry_run:
                self.ssot.save_signal("self_heal_dry", f"[DRY] {rule['name']}: would run '{fix_cmd}'")
                logger.info(f"[DRY-RUN] {rule['name']}: {fix_cmd}")
                return {"action": "dry_run", "rule": rule["name"], "fix": fix_cmd}

            # 실행
            logger.info(f"Self-healing: {rule['name']} → {fix_cmd}")
            fix_result = await self.executor.execute("shell", fix_cmd, source="schedule")

            # verify
            verified = await self._verify(rule, groups)

            # 기록
            self._record_cooldown(cooldown_key)
            status = "success" if verified else "verify_failed"
            self.ssot.save_signal(
                "self_heal",
                f"[{status}] {rule['name']}: {fix_cmd} | verified={verified}"
            )
            logger.info(f"Self-heal {status}: {rule['name']} verified={verified}")

            return {"action": "executed", "rule": rule["name"],
                    "fix": fix_cmd, "verified": verified}

        # 매칭 실패 → L2 (있으면)
        if self.router and not self.dry_run:
            return await self._l2_diagnose(error_text, context)

        return {"action": "no_match"}

    async def _verify(self, rule: dict, groups: dict) -> bool:
        """fix 실행 후 검증."""
        if "verify" not in rule:
            return True

        await asyncio.sleep(self.VERIFY_WAIT)
        verify_cmd = rule["verify"].format(**groups)
        output = await self.executor.execute("shell", verify_cmd, source="schedule")
        output = output.strip() if isinstance(output, str) else str(output)

        if "verify_expect" in rule:
            return output.strip() == rule["verify_expect"]
        elif "verify_check" in rule:
            try:
                return eval(rule["verify_check"], {"output": output, "int": int, "float": float})
            except Exception:
                return False
        return True

    async def _l2_diagnose(self, error_text: str, context: dict = None) -> dict:
        """L2: LLM에게 진단 요청. confidence < 0.8이면 보고만."""
        prompt = (
            f"서버 에러를 분석해줘. JSON으로만 응답.\n\n"
            f"에러: {error_text[:1500]}\n\n"
            f'응답 형식: {{"root_cause":"...","fix_command":"bash 명령","risk":"LOW|MEDIUM|HIGH","confidence":0.0-1.0}}'
        )
        try:
            resp = await self.router.call(
                "reasoning",
                [{"role": "user", "content": prompt}],
                system="서버 에러 분석 전문가. JSON만 반환."
            )
            text = resp.text.strip().replace("```json", "").replace("```", "").strip()
            diag = json.loads(text)
        except Exception as e:
            logger.warning(f"L2 parse error: {e}")
            return {"action": "l2_parse_error"}

        # 안전 기준: confidence >= 0.8 AND risk != HIGH
        if diag.get("confidence", 0) < 0.8 or diag.get("risk") == "HIGH":
            self.ssot.save_signal("self_heal_l2", f"[REPORT] {diag.get('root_cause', '?')}")
            return {"action": "report_only", "diagnosis": diag}

        # 실행
        fix = diag.get("fix_command", "")
        if fix:
            result = await self.executor.execute("shell", fix, source="schedule")
            self.ssot.save_signal("self_heal_l2", f"[EXEC] {fix} → {str(result)[:200]}")
            return {"action": "l2_executed", "diagnosis": diag, "result": str(result)[:200]}

        return {"action": "l2_no_fix", "diagnosis": diag}

    def _over_cooldown(self, key: str) -> bool:
        """동일 규칙 하루 N회 제한."""
        rows = self.ssot.conn.execute(
            "SELECT COUNT(*) FROM signals "
            "WHERE kind IN ('self_heal', 'self_heal_exec') AND data LIKE ? "
            "AND created_at > datetime('now', '-1 day')",
            (f"%{key}%",)
        ).fetchone()
        return (rows[0] if rows else 0) >= self.MAX_PER_DAY

    def _record_cooldown(self, key: str) -> None:
        self.ssot.save_signal("self_heal_exec", key)
