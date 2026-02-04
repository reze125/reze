"""Acon - Autonomous Control Engine.

자율 행동 결정:
1. 위험도 평가 (0.0~1.0)
2. 자율 등급 판정 (AUTO/LOW/MEDIUM/HIGH/LOCK)
3. 일일 예산 관리
4. 에스컬레이션 정책
"""
import logging
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from datetime import datetime, date
from enum import Enum

logger = logging.getLogger("REZE.acon")


class RiskLevel(Enum):
    AUTO = "auto"           # 0.0~0.2: 완전 자율
    LOW = "low"             # 0.2~0.4: 자율 (로그만)
    MEDIUM = "medium"       # 0.4~0.7: 자율 (경고 + 검증)
    HIGH = "high"           # 0.7~0.9: 확인 권장
    LOCK = "lock"           # 0.9~1.0: 승인 필수


class Decision(Enum):
    APPROVED = "approved"     # 실행 허용
    DENIED = "denied"         # 실행 거부
    ESCALATED = "escalated"   # 상위로 에스컬레이션
    DEFERRED = "deferred"     # 나중에 재시도


@dataclass
class RiskAssessment:
    """위험도 평가 결과."""
    score: float              # 0.0~1.0
    level: RiskLevel
    factors: List[str]
    cost: int                 # 예산 비용
    mitigations: List[str] = field(default_factory=list)


@dataclass
class ControlDecision:
    """자율 제어 결정."""
    decision: Decision
    risk: RiskAssessment
    reason: str
    can_retry: bool = False
    alternative: str = ""
    requires_confirmation: bool = False


class AconEngine:
    """Autonomous Control Engine."""

    # 행동별 기본 비용
    ACTION_COSTS = {
        "web_search": 1,
        "web_fetch": 1,
        "file_read": 1,
        "filesystem": 2,
        "shell": 5,
        "python": 3,
        "http": 3,
        "code_edit": 8,
        "final_answer": 0,
    }

    # LOCK 행동 (reze_permissions.py와 동기화)
    LOCK_ACTIONS = frozenset({
        "price_change", "paid_api_subscribe", "refund_process",
        "server_plan_change", "env_modify", "credentials_modify",
        "permissions_critical_change", "firewall_change", "ssh_change",
        "db_drop", "db_mass_delete", "project_dir_delete",
        "backup_delete", "git_force_push", "domain_purchase",
        "external_account_create", "email_send", "external_post",
    })

    def __init__(
        self,
        ssot=None,
        daily_budget: int = 100,
        auto_threshold: float = 0.2,
        confirm_threshold: float = 0.7,
        max_retries: int = 2
    ):
        self.ssot = ssot
        self.daily_budget = daily_budget
        self.auto_threshold = auto_threshold
        self.confirm_threshold = confirm_threshold
        self.max_retries = max_retries

    # === 위험도 평가 ===

    def assess_risk(
        self,
        action_type: str,
        action_input: Any,
        context: Dict[str, Any] = None
    ) -> RiskAssessment:
        """
        행동 위험도 평가.

        Args:
            action_type: 행동 유형
            action_input: 행동 입력
            context: 추가 컨텍스트

        Returns:
            RiskAssessment
        """
        context = context or {}
        factors = []
        score = 0.0

        # Factor 1: LOCK 행동 체크
        if action_type in self.LOCK_ACTIONS:
            return RiskAssessment(
                score=1.0,
                level=RiskLevel.LOCK,
                factors=["LOCK action"],
                cost=0,  # LOCK은 예산 차감 없음 (실행 안 함)
                mitigations=["주인 승인 필요"]
            )

        # Factor 2: 행동 유형별 기본 위험도
        type_risk = self._get_type_risk(action_type)
        score += type_risk * 0.4
        if type_risk > 0.5:
            factors.append(f"risky_type ({action_type})")

        # Factor 3: 입력 내용 분석
        input_risk = self._analyze_input_risk(action_type, action_input)
        score += input_risk * 0.3
        if input_risk > 0.3:
            factors.append(f"risky_input ({input_risk:.2f})")

        # Factor 4: 연속 실패
        if context.get("consecutive_failures", 0) > 0:
            failure_penalty = min(0.3, context["consecutive_failures"] * 0.1)
            score += failure_penalty
            factors.append(f"failures ({context['consecutive_failures']})")

        # Factor 5: 시간대 (야간은 더 신중)
        hour = datetime.now().hour
        if hour < 6 or hour > 22:
            score += 0.1
            factors.append("night_time")

        # Factor 6: 일일 예산 소진율
        budget_used_ratio = self._get_budget_used_ratio()
        if budget_used_ratio > 0.8:
            score += 0.15
            factors.append(f"budget_low ({budget_used_ratio:.0%})")

        score = min(1.0, max(0.0, score))

        # 등급 결정
        level = self._score_to_level(score)

        # 비용 결정
        cost = self._calculate_cost(action_type, level)

        # 완화 조치 제안
        mitigations = self._suggest_mitigations(action_type, factors)

        return RiskAssessment(
            score=score,
            level=level,
            factors=factors,
            cost=cost,
            mitigations=mitigations
        )

    def _get_type_risk(self, action_type: str) -> float:
        """행동 유형별 기본 위험도."""
        risk_map = {
            "web_search": 0.1,
            "web_fetch": 0.1,
            "file_read": 0.15,
            "filesystem": 0.35,
            "python": 0.35,
            "http": 0.3,
            "shell": 0.5,
            "code_edit": 0.5,
            "final_answer": 0.0,
        }
        return risk_map.get(action_type, 0.4)

    def _analyze_input_risk(self, action_type: str, action_input: Any) -> float:
        """입력 내용 기반 위험도."""
        input_str = str(action_input).lower()
        risk = 0.0

        # 위험 키워드
        danger_keywords = {
            "delete": 0.3, "remove": 0.3, "drop": 0.4,
            "rm ": 0.3, "rm -rf": 0.5, "rm -r": 0.4,
            "sudo": 0.2, "root": 0.2,
            "password": 0.3, "secret": 0.3, "key": 0.2,
            "production": 0.2, "prod": 0.15,
            "force": 0.2, "--force": 0.25,
            "truncate": 0.4, "format": 0.3,
            "chmod 777": 0.3, "chmod -r": 0.25,
        }

        for keyword, weight in danger_keywords.items():
            if keyword in input_str:
                risk += weight

        # 안전 키워드 (감점)
        safe_keywords = ["--dry-run", "test", "sandbox", "local", "debug", "echo", "print"]
        for keyword in safe_keywords:
            if keyword in input_str:
                risk -= 0.1

        return max(0.0, min(1.0, risk))

    def _score_to_level(self, score: float) -> RiskLevel:
        """점수 → 등급 변환."""
        if score < self.auto_threshold:
            return RiskLevel.AUTO
        elif score < 0.4:
            return RiskLevel.LOW
        elif score < self.confirm_threshold:
            return RiskLevel.MEDIUM
        elif score < 0.9:
            return RiskLevel.HIGH
        else:
            return RiskLevel.LOCK

    def _calculate_cost(self, action_type: str, level: RiskLevel) -> int:
        """예산 비용 계산."""
        base_cost = self.ACTION_COSTS.get(action_type, 3)

        # 등급별 가중치
        multipliers = {
            RiskLevel.AUTO: 0.5,
            RiskLevel.LOW: 1.0,
            RiskLevel.MEDIUM: 1.5,
            RiskLevel.HIGH: 2.0,
            RiskLevel.LOCK: 0,  # LOCK은 실행 안 함
        }

        return int(base_cost * multipliers.get(level, 1.0))

    def _suggest_mitigations(self, action_type: str, factors: List[str]) -> List[str]:
        """위험 완화 조치 제안."""
        mitigations = []

        if "risky_input" in str(factors):
            mitigations.append("입력값 검토 권장")
        if "failures" in str(factors):
            mitigations.append("이전 실패 원인 분석 후 재시도")
        if "night_time" in str(factors):
            mitigations.append("긴급하지 않으면 주간에 실행")
        if "budget_low" in str(factors):
            mitigations.append("중요 작업만 선별 실행")
        if "risky_type" in str(factors):
            mitigations.append("실행 전 영향 범위 확인")

        return mitigations

    # === 결정 ===

    def decide(
        self,
        action_type: str,
        action_input: Any,
        source: str = "api",
        context: Dict[str, Any] = None
    ) -> ControlDecision:
        """
        자율 실행 여부 결정.

        Args:
            action_type: 행동 유형
            action_input: 행동 입력
            source: 요청 출처
            context: 추가 컨텍스트

        Returns:
            ControlDecision
        """
        risk = self.assess_risk(action_type, action_input, context)

        # LOCK 행동
        if risk.level == RiskLevel.LOCK:
            decision = ControlDecision(
                decision=Decision.DENIED,
                risk=risk,
                reason="LOCK action requires owner approval",
                requires_confirmation=True
            )
            self._log_decision(action_type, action_input, decision, source)
            return decision

        # 예산 체크
        remaining = self._get_remaining_budget()
        if risk.cost > remaining:
            decision = ControlDecision(
                decision=Decision.DEFERRED,
                risk=risk,
                reason=f"Daily budget exhausted ({remaining}/{self.daily_budget})",
                can_retry=True
            )
            self._log_decision(action_type, action_input, decision, source)
            return decision

        # 등급별 결정
        if risk.level in (RiskLevel.AUTO, RiskLevel.LOW):
            decision = ControlDecision(
                decision=Decision.APPROVED,
                risk=risk,
                reason=f"Auto-approved ({risk.level.value})"
            )
        elif risk.level == RiskLevel.MEDIUM:
            decision = ControlDecision(
                decision=Decision.APPROVED,
                risk=risk,
                reason=f"Approved with caution ({risk.level.value})",
                requires_confirmation=False  # 실행은 하되 로그 강화
            )
        else:  # HIGH
            decision = ControlDecision(
                decision=Decision.ESCALATED,
                risk=risk,
                reason="High risk - confirmation recommended",
                requires_confirmation=True,
                alternative=self._suggest_alternative(action_type, action_input)
            )

        # 예산 차감
        if decision.decision == Decision.APPROVED:
            self._deduct_budget(risk.cost, risk.level)

        self._log_decision(action_type, action_input, decision, source)
        return decision

    def _suggest_alternative(self, action_type: str, action_input: Any) -> str:
        """더 안전한 대안 제안."""
        input_str = str(action_input)

        if "rm -rf" in input_str:
            return input_str.replace("rm -rf", "rm -ri")  # 확인 프롬프트
        if "rm -r" in input_str:
            return input_str.replace("rm -r", "rm -ri")
        if "delete" in input_str.lower() and "where" not in input_str.lower():
            return "WHERE 조건 추가 필요"
        if "sudo" in input_str:
            return input_str.replace("sudo ", "")  # sudo 제거 시도
        if "--force" in input_str:
            return input_str.replace("--force", "")

        return ""

    # === 예산 관리 ===

    def _get_remaining_budget(self) -> int:
        """오늘 남은 예산."""
        if not self.ssot:
            return self.daily_budget

        today = date.today().isoformat()
        try:
            row = self.ssot.conn.execute(
                "SELECT used FROM acon_budget WHERE date = ?", (today,)
            ).fetchone()
            used = row[0] if row else 0
            return self.daily_budget - used
        except:
            return self.daily_budget

    def _get_budget_used_ratio(self) -> float:
        """예산 사용률."""
        remaining = self._get_remaining_budget()
        return 1.0 - (remaining / self.daily_budget)

    def _deduct_budget(self, cost: int, level: RiskLevel):
        """예산 차감."""
        if not self.ssot:
            return

        today = date.today().isoformat()

        try:
            # upsert
            self.ssot.conn.execute("""
                INSERT INTO acon_budget (date, total_budget, used, auto_count, low_count, medium_count)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    used = used + ?,
                    auto_count = auto_count + ?,
                    low_count = low_count + ?,
                    medium_count = medium_count + ?
            """, (
                today, self.daily_budget, cost,
                1 if level == RiskLevel.AUTO else 0,
                1 if level == RiskLevel.LOW else 0,
                1 if level == RiskLevel.MEDIUM else 0,
                cost,
                1 if level == RiskLevel.AUTO else 0,
                1 if level == RiskLevel.LOW else 0,
                1 if level == RiskLevel.MEDIUM else 0,
            ))
            self.ssot.conn.commit()
        except Exception as e:
            logger.warning(f"[Acon] Budget deduction failed: {e}")

    def _log_decision(
        self,
        action_type: str,
        action_input: Any,
        decision: ControlDecision,
        source: str
    ):
        """결정 로그."""
        if not self.ssot:
            return

        try:
            self.ssot.conn.execute("""
                INSERT INTO acon_decisions
                (action_type, action_input, risk_level, risk_score, decision, reason, cost, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                action_type,
                str(action_input)[:500],
                decision.risk.level.value,
                decision.risk.score,
                decision.decision.value,
                decision.reason,
                decision.risk.cost,
                source
            ))
            self.ssot.conn.commit()
        except Exception as e:
            logger.warning(f"[Acon] Decision log failed: {e}")

        # 콘솔 로그
        if decision.decision == Decision.APPROVED:
            logger.debug(f"[Acon] {action_type}: {decision.decision.value} (risk={decision.risk.score:.2f})")
        else:
            logger.warning(f"[Acon] {action_type}: {decision.decision.value} (risk={decision.risk.score:.2f}, reason={decision.reason})")

    # === 통계 ===

    def get_stats(self) -> Dict[str, Any]:
        """Acon 통계."""
        today = date.today().isoformat()
        budget_info = {"used": 0, "auto": 0, "low": 0, "medium": 0, "denied": 0}

        if self.ssot:
            try:
                row = self.ssot.conn.execute(
                    "SELECT used, auto_count, low_count, medium_count, denied_count FROM acon_budget WHERE date = ?",
                    (today,)
                ).fetchone()
                if row:
                    budget_info = {
                        "used": row[0],
                        "auto": row[1],
                        "low": row[2],
                        "medium": row[3],
                        "denied": row[4] if len(row) > 4 else 0
                    }
            except:
                pass

        return {
            "daily_budget": self.daily_budget,
            "remaining": self._get_remaining_budget(),
            "today": budget_info,
            "thresholds": {
                "auto": self.auto_threshold,
                "confirm": self.confirm_threshold
            }
        }

    def get_recent_decisions(self, limit: int = 20) -> List[Dict]:
        """최근 결정 이력."""
        if not self.ssot:
            return []

        try:
            rows = self.ssot.conn.execute("""
                SELECT action_type, risk_level, risk_score, decision, reason, created_at
                FROM acon_decisions
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,)).fetchall()
            return [dict(r) for r in rows]
        except:
            return []

    def reset_daily_budget(self):
        """일일 예산 초기화 (테스트용)."""
        if not self.ssot:
            return

        today = date.today().isoformat()
        try:
            self.ssot.conn.execute(
                "DELETE FROM acon_budget WHERE date = ?", (today,)
            )
            self.ssot.conn.commit()
        except:
            pass
