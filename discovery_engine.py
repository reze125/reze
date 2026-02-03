"""REZE v5.0 — Discovery Engine: 서버 환경 자동 감지."""

import json
import logging
import re
from datetime import datetime

logger = logging.getLogger("REZE.discovery")


class DiscoveryEngine:
    """PM2, Docker, 포트 스캔 → 변화 감지 → LLM 분석 → SSOT 등록."""

    def __init__(self, ssot, tools, call_llm_fn, discord_notify=None):
        self.ssot = ssot
        self.tools = tools
        self.llm = call_llm_fn
        self.discord = discord_notify
        self.known_state = {}
        self._initialized = False

    async def full_scan(self) -> list:
        """서버 전체 스캔 → 변화 감지."""
        logger.info("Discovery scan started")
        current = {}
        discoveries = []

        try:
            # PM2
            raw = await self.tools.execute("shell", "pm2 jlist 2>/dev/null || echo '[]'", "discovery")
            try:
                current["pm2"] = {p["name"]: p for p in json.loads(raw)}
            except:
                current["pm2"] = {}

            # Docker
            raw = await self.tools.execute("shell",
                "docker ps --format '{{.Names}}|||{{.Image}}|||{{.Status}}|||{{.Ports}}' 2>/dev/null || echo ''",
                "discovery")
            current["docker"] = {}
            for line in raw.strip().split("\n"):
                parts = line.split("|||")
                if len(parts) >= 2:
                    current["docker"][parts[0]] = {
                        "name": parts[0],
                        "image": parts[1],
                        "status": parts[2] if len(parts) > 2 else "",
                        "ports": parts[3] if len(parts) > 3 else ""
                    }

            # 리스닝 포트
            raw = await self.tools.execute("shell",
                "ss -tlnp 2>/dev/null | tail -n +2 | awk '{print $4}'", "discovery")
            current["ports"] = set()
            for line in raw.strip().split("\n"):
                if ":" in line:
                    port = line.rsplit(":", 1)[-1]
                    if port.isdigit():
                        current["ports"].add(port)

        except Exception as e:
            logger.error(f"Scan error: {e}")
            return []

        if not self._initialized:
            # 첫 스캔: 벌크 등록
            await self._initial_register(current)
            self._initialized = True
        else:
            # 변화 감지
            discoveries = await self._detect_and_analyze(current)

        self.known_state = current

        # 알림
        if discoveries and self.discord:
            msg = "🔍 **Discovery Scan**\n" + "\n".join(
                f"- {d['type']}: **{d.get('name', '?')}**" for d in discoveries[:5])
            try:
                await self.discord(msg)
            except:
                pass

        logger.info(f"Discovery complete: {len(discoveries)} changes")
        return discoveries

    async def _initial_register(self, state):
        """첫 스캔: 기존 서비스 벌크 등록."""
        count = 0

        for name, info in state.get("pm2", {}).items():
            if not self.ssot.get_service(name):
                script = info.get("pm2_env", {}).get("pm_exec_path", "")
                self.ssot.register_managed_service({
                    "name": name,
                    "category": "unknown",
                    "description": f"PM2: {name}",
                    "health_check": f"pm2 describe {name} 2>/dev/null | grep status",
                    "restart_command": f"pm2 restart {name}",
                    "project_path": script,
                })
                count += 1

        for name, info in state.get("docker", {}).items():
            if not self.ssot.get_service(name):
                port_match = re.search(r':(\d+)->', info.get("ports", ""))
                self.ssot.register_managed_service({
                    "name": name,
                    "category": "unknown",
                    "description": f"Docker: {name} ({info.get('image', '')})",
                    "tech_stack": [info.get("image", "")],
                    "port": int(port_match.group(1)) if port_match else None,
                    "health_check": f"docker ps --filter name={name} --format '{{{{.Status}}}}'",
                    "restart_command": f"docker restart {name}",
                })
                count += 1

        logger.info(f"Initial registration: {count} services")

    async def _detect_and_analyze(self, current) -> list:
        """이전 상태와 비교하여 변화 감지."""
        changes = []
        old = self.known_state

        # PM2 변화
        old_pm2 = set(old.get("pm2", {}).keys())
        new_pm2 = set(current.get("pm2", {}).keys())
        for name in new_pm2 - old_pm2:
            changes.append(await self._analyze_change("new_pm2", name, current["pm2"][name]))
        for name in old_pm2 - new_pm2:
            changes.append({"type": "pm2_removed", "name": name})
            self.ssot.update_service_status(name, "down")

        # Docker 변화
        old_docker = set(old.get("docker", {}).keys())
        new_docker = set(current.get("docker", {}).keys())
        for name in new_docker - old_docker:
            changes.append(await self._analyze_change("new_docker", name, current["docker"][name]))
        for name in old_docker - new_docker:
            changes.append({"type": "docker_removed", "name": name})
            self.ssot.update_service_status(name, "down")

        return [c for c in changes if c]

    async def _analyze_change(self, change_type, name, info) -> dict:
        """변화를 LLM으로 분석하고 등록."""
        # 추가 정보 수집
        context = ""
        if "pm2" in change_type:
            context = await self.tools.execute("shell", f"pm2 describe {name} 2>/dev/null | head -25", "discovery")
        elif "docker" in change_type:
            context = await self.tools.execute("shell", f"docker inspect {name} 2>/dev/null | head -40", "discovery")

        try:
            prompt = f"""서버에서 새 서비스 감지: {name}
유형: {change_type}
정보: {json.dumps(info, default=str)[:800]}
추가 정보: {context[:1000]}

JSON만 출력:
{{"category":"web_app|api|database|queue|monitoring|blog|saas|utility|unknown","description":"1문장","tech_stack":["기술"],"health_check":"확인 명령어","restart_command":"재시작 명령어","risk_level":"low|medium|high"}}"""

            resp = await self.llm(prompt, role="analysis")
            text = resp if isinstance(resp, str) else str(resp)
            if "```" in text:
                text = text.split("```json")[-1].split("```")[0] if "```json" in text else text.split("```")[1].split("```")[0]
            data = json.loads(text.strip())
            data["name"] = name

            self.ssot.register_managed_service(data)
            logger.info(f"Registered: {name} ({data.get('category')})")

            return {"type": change_type, "name": name, "analysis": data}
        except Exception as e:
            logger.error(f"Analysis failed for {name}: {e}")
            # 기본값으로 등록
            restart = f"pm2 restart {name}" if "pm2" in change_type else f"docker restart {name}"
            self.ssot.register_managed_service({
                "name": name,
                "category": "unknown",
                "description": f"{change_type}: {name}",
                "restart_command": restart
            })
            return {"type": change_type, "name": name}

    async def health_check_all(self) -> list:
        """등록된 모든 서비스 헬스체크."""
        services = self.ssot.get_all_services()
        issues = []

        for svc in services:
            if not svc.get("health_check"):
                continue

            try:
                result = await self.tools.execute("shell", svc["health_check"], "discovery")
                is_healthy = "online" in result.lower() or "running" in result.lower() or "healthy" in result.lower()

                if is_healthy:
                    self.ssot.update_service_status(svc["name"], "active")
                else:
                    self.ssot.update_service_status(svc["name"], "unhealthy")
                    issues.append({"name": svc["name"], "status": "unhealthy", "output": result[:200]})
            except Exception as e:
                issues.append({"name": svc["name"], "status": "error", "error": str(e)})

        return issues
