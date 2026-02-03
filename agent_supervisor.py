"""
REZE v4.0 ULTIMATE Agent Supervisor
- 다른 자동화 에이전트 감시 (Docker, n8n, PM2, cron, Dify)
- 자동 복구 및 에스컬레이션
- 새 에이전트 자동 발견
"""

import json
import asyncio
import subprocess
from datetime import datetime
from typing import Optional, Callable

import logging
logger = logging.getLogger("REZE.supervisor")


# 에이전트 타입별 설정
AGENT_TYPES = {
    "docker_container": {
        "check": "docker inspect --format='{{{{.State.Status}}}}' {name}",
        "healthy": "running",
        "restart": "docker restart {name}",
        "max_auto_restarts": 3
    },
    "n8n_workflow": {
        "check": "curl -s http://localhost:5678/api/v1/workflows/{workflow_id}",
        "healthy_field": "active",
        "activate": "curl -X PATCH http://localhost:5678/api/v1/workflows/{workflow_id}/activate",
        "max_auto_restarts": 3
    },
    "pm2_process": {
        "check": "pm2 jlist",
        "healthy": "online",
        "restart": "pm2 restart {name}",
        "max_auto_restarts": 3
    },
    "cron_job": {
        "check": "systemctl status cron",
        "healthy": "active",
        "restart": "sudo systemctl restart cron",
        "max_auto_restarts": 2
    },
    "dify_app": {
        "check": "curl -s http://localhost:3000/api/apps/{app_id}/status",
        "healthy_field": "status",
        "healthy_value": "active",
        "max_auto_restarts": 2
    }
}


class AgentSupervisor:
    """
    다른 자동화 에이전트를 감시하고, 문제 발견 시 자동 복구 또는 에스컬레이션.
    """

    SCAN_INTERVAL_MINUTES = 30

    def __init__(self, ssot, discord_notify: Callable = None):
        """
        Args:
            ssot: SSOT 인스턴스
            discord_notify: Discord 알림 함수
        """
        self.ssot = ssot
        self.discord_notify = discord_notify
        self.agent_types = AGENT_TYPES

    async def scan_all_agents(self) -> list:
        """모든 등록된 에이전트 상태 스캔."""
        logger.info("Scanning all agents...")

        agents = self.ssot.get_all_agents(enabled_only=True)
        issues = []

        for agent in agents:
            status = await self._check_agent(agent)

            if status["healthy"]:
                self.ssot.update_agent_status(agent["id"], "healthy", status)
                continue

            # 문제 발견!
            issue = {
                "agent": dict(agent),
                "status": status,
                "severity": self._assess_severity(agent, status),
                "timestamp": datetime.now().isoformat()
            }
            issues.append(issue)

            # 자동 복구 시도
            if agent.get("auto_recover") and status.get("auto_recoverable"):
                recovery = await self._auto_recover(agent, status)
                issue["recovery"] = recovery

                if recovery["success"]:
                    if self.discord_notify:
                        await self.discord_notify(
                            f"🔧 자동 복구: {agent['name']} — {recovery['action']}"
                        )
                else:
                    # 복구 실패 → 에스컬레이션
                    if self.discord_notify:
                        await self.discord_notify(
                            f"🚨 자동 복구 실패: {agent['name']}\n"
                            f"문제: {status.get('error', 'Unknown')}\n"
                            f"시도한 복구: {recovery['action']}\n"
                            f"수동 개입 필요"
                        )
            else:
                # 자동 복구 불가 → 즉시 알림
                if self.discord_notify:
                    await self.discord_notify(
                        f"⚠️ {agent['name']} 이상 감지: {status.get('error', 'Unknown')}"
                    )

            # 상태 업데이트
            self.ssot.update_agent_status(agent["id"], "unhealthy", status)

        logger.info(f"Agent scan complete: {len(issues)} issues found")
        return issues

    async def _check_agent(self, agent: dict) -> dict:
        """개별 에이전트 상태 체크."""
        agent_type = self.agent_types.get(agent.get("agent_type"))
        if not agent_type:
            return {
                "healthy": False,
                "error": f"Unknown agent type: {agent.get('agent_type')}",
                "auto_recoverable": False
            }

        try:
            # 체크 명령 포맷팅
            check_cmd = agent_type["check"].format(
                name=agent.get("name", ""),
                container_name=agent.get("container_name", agent.get("name", "")),
                workflow_id=agent.get("workflow_id", ""),
                app_id=agent.get("workflow_id", ""),  # dify도 같은 필드 사용
                process_name=agent.get("process_name", agent.get("name", ""))
            )

            result = await self._exec_shell(check_cmd, timeout=10)

            # 상태 판단
            if "healthy" in agent_type:
                is_healthy = agent_type["healthy"] in result.get("stdout", "")
            elif "healthy_field" in agent_type:
                try:
                    data = json.loads(result.get("stdout", "{}"))
                    is_healthy = data.get(agent_type["healthy_field"]) == agent_type.get("healthy_value", True)
                except:
                    is_healthy = False
            else:
                is_healthy = result.get("returncode", 1) == 0

            return {
                "healthy": is_healthy,
                "raw": result,
                "auto_recoverable": "restart" in agent_type or "activate" in agent_type,
                "error": None if is_healthy else f"Status check failed: {result.get('stdout', '')[:200]}"
            }
        except Exception as e:
            return {
                "healthy": False,
                "error": str(e),
                "auto_recoverable": False
            }

    async def _auto_recover(self, agent: dict, status: dict) -> dict:
        """자동 복구 시도."""
        agent_type = self.agent_types.get(agent.get("agent_type"))

        # 재시작 횟수 체크
        recent_restarts = self.ssot.count_recent_restarts(agent["id"], hours=24)
        max_restarts = agent_type.get("max_auto_restarts", 3)

        if recent_restarts >= max_restarts:
            return {
                "success": False,
                "action": f"24시간 내 {recent_restarts}회 재시작 — 한계 초과"
            }

        # 복구 명령 선택
        if "restart" in agent_type:
            cmd_template = agent_type["restart"]
        elif "activate" in agent_type:
            cmd_template = agent_type["activate"]
        else:
            return {"success": False, "action": "복구 명령 없음"}

        cmd = cmd_template.format(
            name=agent.get("name", ""),
            container_name=agent.get("container_name", agent.get("name", "")),
            workflow_id=agent.get("workflow_id", ""),
            process_name=agent.get("process_name", agent.get("name", ""))
        )

        logger.info(f"Auto-recovering {agent['name']}: {cmd}")

        # 복구 실행
        result = await self._exec_shell(cmd, timeout=30)

        # 잠시 대기 후 재확인
        await asyncio.sleep(5)
        recheck = await self._check_agent(agent)

        # 로그 기록
        self.ssot.log_restart(agent["id"], cmd, recheck["healthy"],
                              error=recheck.get("error"))

        return {
            "success": recheck["healthy"],
            "action": cmd,
            "result": result
        }

    async def auto_discover_agents(self):
        """새 에이전트 자동 발견."""
        logger.info("Auto-discovering agents...")
        discovered = []

        # 1) Docker 컨테이너 스캔
        docker_discovered = await self._discover_docker()
        discovered.extend(docker_discovered)

        # 2) PM2 프로세스 스캔
        pm2_discovered = await self._discover_pm2()
        discovered.extend(pm2_discovered)

        # 3) n8n 워크플로우 스캔 (선택적)
        # n8n_discovered = await self._discover_n8n()
        # discovered.extend(n8n_discovered)

        # 알림
        if discovered and self.discord_notify:
            await self.discord_notify(
                f"🆕 새 에이전트 발견: {len(discovered)}개\n" +
                "\n".join(f"- {d['name']} ({d['type']})" for d in discovered[:10])
            )

        logger.info(f"Auto-discovery complete: {len(discovered)} new agents")
        return discovered

    async def _discover_docker(self) -> list:
        """Docker 컨테이너 발견."""
        discovered = []

        result = await self._exec_shell("docker ps --format '{{.Names}}'")
        if result.get("returncode") != 0:
            return discovered

        containers = result.get("stdout", "").strip().split("\n")
        known_containers = self.ssot.get_known_agent_names("docker_container")

        for name in containers:
            if name and name not in known_containers:
                # 새 컨테이너 발견!
                self.ssot.register_agent(
                    name=name,
                    agent_type="docker_container",
                    container_name=name,
                    auto_recover=1,
                    enabled=1,
                    discovered_at=datetime.now().isoformat(),
                    status="new"
                )
                discovered.append({"name": name, "type": "docker_container"})
                logger.info(f"Discovered Docker container: {name}")

        return discovered

    async def _discover_pm2(self) -> list:
        """PM2 프로세스 발견."""
        discovered = []

        result = await self._exec_shell("pm2 jlist 2>/dev/null || echo '[]'")
        try:
            processes = json.loads(result.get("stdout", "[]"))
        except:
            return discovered

        known_pm2 = self.ssot.get_known_agent_names("pm2_process")

        for proc in processes:
            name = proc.get("name", "")
            if name and name not in known_pm2:
                # 새 PM2 프로세스 발견!
                self.ssot.register_agent(
                    name=name,
                    agent_type="pm2_process",
                    process_name=name,
                    auto_recover=1,
                    enabled=1,
                    discovered_at=datetime.now().isoformat(),
                    status="new",
                    purpose=f"PM2 process: {proc.get('pm2_env', {}).get('script', 'N/A')}"
                )
                discovered.append({"name": name, "type": "pm2_process"})
                logger.info(f"Discovered PM2 process: {name}")

        return discovered

    def _assess_severity(self, agent: dict, status: dict) -> str:
        """이슈 심각도 평가."""
        # SaaS 관련 서비스는 높은 심각도
        name = agent.get("name", "").lower()
        if any(s in name for s in ["postpilot", "quotepilot", "browserpilot", "agenthub", "rag"]):
            return "high"

        # 블로그/인프라
        if any(s in name for s in ["nginx", "postgresql", "redis"]):
            return "critical"

        return "medium"

    async def _exec_shell(self, cmd: str, timeout: int = 30) -> dict:
        """셸 명령 실행."""
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout
            )
            return {
                "stdout": stdout.decode().strip(),
                "stderr": stderr.decode().strip(),
                "returncode": proc.returncode
            }
        except asyncio.TimeoutError:
            return {"stdout": "", "stderr": "Timeout", "returncode": -1}
        except Exception as e:
            return {"stdout": "", "stderr": str(e), "returncode": -1}

    async def get_agent_status_summary(self) -> dict:
        """에이전트 상태 요약."""
        agents = self.ssot.get_all_agents(enabled_only=False)

        summary = {
            "total": len(agents),
            "healthy": 0,
            "unhealthy": 0,
            "unknown": 0,
            "new": 0,
            "by_type": {}
        }

        for agent in agents:
            status = agent.get("status", "unknown")
            if status == "healthy":
                summary["healthy"] += 1
            elif status == "unhealthy":
                summary["unhealthy"] += 1
            elif status == "new":
                summary["new"] += 1
            else:
                summary["unknown"] += 1

            # 타입별 집계
            agent_type = agent.get("agent_type", "unknown")
            if agent_type not in summary["by_type"]:
                summary["by_type"][agent_type] = {"total": 0, "healthy": 0}
            summary["by_type"][agent_type]["total"] += 1
            if status == "healthy":
                summary["by_type"][agent_type]["healthy"] += 1

        return summary

    async def force_check_agent(self, agent_name: str) -> dict:
        """특정 에이전트 강제 체크."""
        agent = self.ssot.conn.execute(
            "SELECT * FROM supervised_agents WHERE name = ?",
            [agent_name]
        ).fetchone()

        if not agent:
            return {"error": f"Agent not found: {agent_name}"}

        status = await self._check_agent(dict(agent))
        self.ssot.update_agent_status(agent["id"],
                                       "healthy" if status["healthy"] else "unhealthy",
                                       status)
        return {"agent": agent_name, "status": status}

    async def recover_agent(self, agent_name: str) -> dict:
        """특정 에이전트 복구 시도 (public wrapper for _auto_recover)."""
        agent = self.ssot.conn.execute(
            "SELECT * FROM supervised_agents WHERE name = ?",
            [agent_name]
        ).fetchone()

        if not agent:
            return {"success": False, "error": f"Agent not found: {agent_name}"}

        agent_dict = dict(agent)
        status = await self._check_agent(agent_dict)

        if status["healthy"]:
            return {"success": True, "action": "Already healthy"}

        if not status.get("auto_recoverable"):
            return {"success": False, "action": "Not auto-recoverable"}

        return await self._auto_recover(agent_dict, status)


# === 편의 함수 ===

async def scan_agents(ssot, discord_notify=None):
    """에이전트 스캔 (단순 래퍼)."""
    supervisor = AgentSupervisor(ssot, discord_notify)
    return await supervisor.scan_all_agents()


async def discover_agents(ssot, discord_notify=None):
    """에이전트 발견 (단순 래퍼)."""
    supervisor = AgentSupervisor(ssot, discord_notify)
    return await supervisor.auto_discover_agents()
