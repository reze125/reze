"""REZE SSOT - Single Source of Truth (SQLite)"""
import sqlite3
import uuid
from datetime import datetime, timedelta
from typing import Optional
from pathlib import Path

import config


class SSOT:
    """영속적 상태 저장소. 모든 실행 기록, 큐, 예산을 관리."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or (config.DATA_DIR / "ssot.sqlite")
        self.conn: Optional[sqlite3.Connection] = None
        self._connect()
        self._init_schema()
        self._mark_stale_running()

    def _connect(self) -> None:
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")

    def _init_schema(self) -> None:
        self.conn.executescript("""
        -- 기존 APEX 호환
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'created',
            final_answer TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            completed_at TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS iterations (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            iteration_num INTEGER NOT NULL,
            thought TEXT NOT NULL,
            action_type TEXT NOT NULL,
            action_input TEXT NOT NULL,
            observation TEXT DEFAULT '',
            success INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY(task_id) REFERENCES tasks(id)
        );
        CREATE TABLE IF NOT EXISTS reflections (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            what_went_wrong TEXT NOT NULL,
            key_insight TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(task_id) REFERENCES tasks(id)
        );

        -- REZE 확장
        CREATE TABLE IF NOT EXISTS daemon_tasks (
            id TEXT PRIMARY KEY,
            task_spec TEXT NOT NULL,
            priority INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'pending',
            mode TEXT DEFAULT 'react',
            source TEXT DEFAULT 'api',
            created_at TEXT NOT NULL,
            started_at TEXT DEFAULT '',
            completed_at TEXT DEFAULT '',
            result TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS daily_budget (
            date TEXT PRIMARY KEY,
            total_tokens INTEGER DEFAULT 0,
            cerebras_calls INTEGER DEFAULT 0,
            groq_calls INTEGER DEFAULT 0,
            gemini_pro_calls INTEGER DEFAULT 0,
            gemini_flash_calls INTEGER DEFAULT 0,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS events (
            event_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            task_id TEXT DEFAULT '',
            raw_input TEXT DEFAULT '',
            output_preview TEXT DEFAULT '',
            tier TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS signals (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            data TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        -- v3.3 traces: 모든 LLM 호출 + 도구 실행 추적
        CREATE TABLE IF NOT EXISTS traces (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trace_id TEXT NOT NULL,
            span_type TEXT NOT NULL,
            provider TEXT,
            model TEXT,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            latency_ms INTEGER DEFAULT 0,
            status TEXT DEFAULT 'ok',
            error_type TEXT,
            metadata TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_traces_provider ON traces(provider, created_at);
        CREATE INDEX IF NOT EXISTS idx_traces_trace_id ON traces(trace_id);

        -- v3.3 plan_cache: 성공한 실행 계획 캐시
        CREATE TABLE IF NOT EXISTS plan_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            keywords TEXT NOT NULL,
            task_pattern TEXT NOT NULL,
            plan_json TEXT NOT NULL,
            success_count INTEGER DEFAULT 1,
            fail_count INTEGER DEFAULT 0,
            last_used TEXT,
            created_at TEXT NOT NULL
        );

        -- v3.3 biz_metrics: 비즈니스 지표
        CREATE TABLE IF NOT EXISTS biz_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            metric_type TEXT NOT NULL,
            metric_name TEXT NOT NULL,
            value REAL,
            unit TEXT,
            metadata TEXT,
            measured_at TEXT NOT NULL
        );

        -- v3.3 인덱스 추가
        CREATE INDEX IF NOT EXISTS idx_signals_created ON signals(created_at);
        CREATE INDEX IF NOT EXISTS idx_signals_kind ON signals(kind);

        -- v3.3 discoveries: 발견 기록
        CREATE TABLE IF NOT EXISTS discoveries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            discovery_type TEXT NOT NULL,
            source_skill TEXT NOT NULL,
            detail TEXT NOT NULL,
            interpretation TEXT,
            affected_services TEXT,
            impact_level TEXT,
            actions_taken TEXT,
            verification_date TEXT,
            verification_result TEXT,
            status TEXT DEFAULT 'new',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_discoveries_status ON discoveries(status);

        -- v3.3 evolutions: 자기 진화 기록
        CREATE TABLE IF NOT EXISTS evolutions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tech_name TEXT NOT NULL,
            tech_description TEXT,
            source TEXT,
            autonomy_level TEXT,
            status TEXT DEFAULT 'evaluated',
            git_backup_tag TEXT,
            changes TEXT,
            test_results TEXT,
            performance_before TEXT,
            performance_after TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            completed_at TEXT
        );

        -- v3.3 Phase 4 Part D: SaaS 성장 자동화
        CREATE TABLE IF NOT EXISTS saas_health (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_name TEXT NOT NULL,
            active_subs INTEGER DEFAULT 0,
            past_due_subs INTEGER DEFAULT 0,
            cancelled_subs INTEGER DEFAULT 0,
            paused_subs INTEGER DEFAULT 0,
            mrr_cents INTEGER DEFAULT 0,
            arr_cents INTEGER DEFAULT 0,
            total_revenue_cents INTEGER DEFAULT 0,
            total_orders INTEGER DEFAULT 0,
            total_customers INTEGER DEFAULT 0,
            metadata TEXT,
            measured_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_saas_health_product ON saas_health(product_name, measured_at);

        CREATE TABLE IF NOT EXISTS landing_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_name TEXT NOT NULL,
            page_url TEXT,
            visitors INTEGER DEFAULT 0,
            signups INTEGER DEFAULT 0,
            conversion_rate REAL DEFAULT 0.0,
            bounce_rate REAL DEFAULT 0.0,
            avg_time_on_page REAL DEFAULT 0.0,
            headline_variant TEXT,
            cta_variant TEXT,
            notes TEXT,
            measured_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_landing_metrics_product ON landing_metrics(product_name, measured_at);

        CREATE TABLE IF NOT EXISTS feature_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_name TEXT NOT NULL,
            source TEXT DEFAULT 'manual',
            category TEXT DEFAULT 'feature_request',
            title TEXT NOT NULL,
            description TEXT,
            user_email TEXT,
            impact_score INTEGER DEFAULT 0,
            effort_score INTEGER DEFAULT 0,
            priority_score REAL DEFAULT 0.0,
            status TEXT DEFAULT 'new',
            llm_analysis TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_feature_requests_product ON feature_requests(product_name, status);

        CREATE TABLE IF NOT EXISTS email_campaigns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_type TEXT NOT NULL,
            product_name TEXT,
            recipient_email TEXT,
            subject TEXT,
            status TEXT DEFAULT 'pending',
            trigger_event TEXT,
            sent_at TEXT,
            opened_at TEXT,
            clicked_at TEXT,
            metadata TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_email_campaigns_type ON email_campaigns(campaign_type, status);

        -- v3.3 Phase 4 Part E: Gumroad 자동화
        CREATE TABLE IF NOT EXISTS gumroad_sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_id TEXT UNIQUE,
            product_id TEXT NOT NULL,
            product_name TEXT,
            email TEXT,
            price_cents INTEGER DEFAULT 0,
            currency TEXT DEFAULT 'usd',
            refunded INTEGER DEFAULT 0,
            sale_timestamp TEXT,
            metadata TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_gumroad_sales_product ON gumroad_sales(product_id, sale_timestamp);

        CREATE TABLE IF NOT EXISTS launches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_name TEXT NOT NULL,
            launch_type TEXT DEFAULT 'new_product',
            target_date TEXT NOT NULL,
            status TEXT DEFAULT 'planning',
            channels TEXT,
            pre_launch_done TEXT,
            launch_day_done TEXT,
            post_launch_done TEXT,
            results TEXT,
            notes TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_launches_status ON launches(status, target_date);

        -- v4.0 신규 테이블

        -- 자동 감지된 서비스
        CREATE TABLE IF NOT EXISTS known_services (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            type TEXT NOT NULL,
            port INTEGER,
            domain TEXT,
            config_path TEXT,
            discovered_at TEXT DEFAULT (datetime('now')),
            status TEXT DEFAULT 'active',
            meta TEXT DEFAULT '{}'
        );

        -- v4.0 plan_cache (절차 캐싱)
        CREATE TABLE IF NOT EXISTS plan_cache_v4 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_pattern TEXT NOT NULL,
            skills_used TEXT,
            procedure TEXT NOT NULL,
            steps INTEGER,
            tokens INTEGER,
            score REAL DEFAULT 0.8,
            created_at TEXT DEFAULT (datetime('now')),
            used_count INTEGER DEFAULT 0,
            last_used TEXT
        );

        -- v4.0 반성 저장 (Reflexion episodic memory)
        CREATE TABLE IF NOT EXISTS reflections_v4 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_pattern TEXT NOT NULL,
            failure_reason TEXT,
            lesson TEXT NOT NULL,
            suggested_approach TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        -- 리서치 인사이트
        CREATE TABLE IF NOT EXISTS research_insights (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            area TEXT NOT NULL,
            insight TEXT NOT NULL,
            source_url TEXT,
            applicability_score REAL,
            applied BOOLEAN DEFAULT FALSE,
            created_at TEXT DEFAULT (datetime('now'))
        );

        -- 동적 생성 스킬 레지스트리
        CREATE TABLE IF NOT EXISTS generated_skills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            domain TEXT UNIQUE NOT NULL,
            type TEXT NOT NULL,
            skill_path TEXT NOT NULL,
            operations TEXT,
            creation_trigger TEXT,
            test_passed BOOLEAN DEFAULT TRUE,
            active BOOLEAN DEFAULT TRUE,
            success_count INTEGER DEFAULT 0,
            fail_count INTEGER DEFAULT 0,
            avg_score REAL DEFAULT 0.0,
            created_at TEXT DEFAULT (datetime('now')),
            last_used TEXT,
            notes TEXT
        );

        -- 목표 트리
        CREATE TABLE IF NOT EXISTS goal_tree (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            goal TEXT NOT NULL,
            decomposition TEXT NOT NULL,
            feasibility TEXT,
            status TEXT DEFAULT 'active',
            progress_pct REAL DEFAULT 0.0,
            created_at TEXT DEFAULT (datetime('now')),
            last_reviewed TEXT,
            completed_at TEXT,
            notes TEXT
        );

        -- 목표 하위 태스크
        CREATE TABLE IF NOT EXISTS goal_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            goal_id INTEGER NOT NULL,
            sub_goal TEXT NOT NULL,
            task_name TEXT NOT NULL,
            description TEXT,
            skill_required TEXT,
            priority TEXT DEFAULT 'P2',
            status TEXT DEFAULT 'pending',
            kpi TEXT,
            actual_result TEXT,
            scheduled_cron TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            completed_at TEXT,
            FOREIGN KEY (goal_id) REFERENCES goal_tree(id)
        );

        -- ========== v4.0 ULTIMATE 신규 테이블 ==========

        -- 1) 태스크 큐 (Goal → Auto-Execute)
        CREATE TABLE IF NOT EXISTS task_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_type TEXT NOT NULL,
            target_service TEXT NOT NULL,
            action TEXT NOT NULL,
            parameters TEXT,
            parent_goal TEXT,
            sub_goal TEXT,
            priority INTEGER DEFAULT 50,
            frequency TEXT DEFAULT 'once',
            status TEXT DEFAULT 'pending',
            retry_count INTEGER DEFAULT 0,
            max_retries INTEGER DEFAULT 3,
            result TEXT,
            created_at TEXT NOT NULL,
            next_run TEXT,
            completed_at TEXT,
            error_log TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_task_queue_status ON task_queue(status, priority DESC);
        CREATE INDEX IF NOT EXISTS idx_task_queue_next_run ON task_queue(next_run);

        -- 2) 보스 피드백 (Quality Gate 캘리브레이션)
        CREATE TABLE IF NOT EXISTS boss_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            result_type TEXT NOT NULL,
            llm_score REAL NOT NULL,
            boss_score REAL,
            boss_comment TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_boss_feedback_type ON boss_feedback(result_type, created_at);

        -- 3) 감시 대상 에이전트
        CREATE TABLE IF NOT EXISTS supervised_agents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            agent_type TEXT NOT NULL,
            container_name TEXT,
            workflow_id TEXT,
            process_name TEXT,
            cron_pattern TEXT,
            health_url TEXT,
            auto_recover INTEGER DEFAULT 1,
            enabled INTEGER DEFAULT 1,
            status TEXT DEFAULT 'unknown',
            last_check TEXT,
            last_healthy TEXT,
            restart_count_24h INTEGER DEFAULT 0,
            skill_ref TEXT,
            purpose TEXT,
            dependencies TEXT,
            discovered_at TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_supervised_agents_status ON supervised_agents(status, enabled);

        -- 4) 동적 스킬 상태 (enhanced)
        CREATE TABLE IF NOT EXISTS dynamic_skills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            skill_name TEXT UNIQUE NOT NULL,
            skill_path TEXT NOT NULL,
            source TEXT NOT NULL,
            status TEXT DEFAULT 'draft',
            success_count INTEGER DEFAULT 0,
            failure_count INTEGER DEFAULT 0,
            consecutive_successes INTEGER DEFAULT 0,
            last_used TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            verified_at TEXT,
            metadata TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_dynamic_skills_status ON dynamic_skills(status);

        -- 5) 에이전트 재시작 로그
        CREATE TABLE IF NOT EXISTS agent_restarts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id INTEGER NOT NULL,
            command TEXT NOT NULL,
            success INTEGER NOT NULL,
            error TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (agent_id) REFERENCES supervised_agents(id)
        );
        CREATE INDEX IF NOT EXISTS idx_agent_restarts_agent ON agent_restarts(agent_id, created_at);

        -- 6) 메타인지 리뷰 기록
        CREATE TABLE IF NOT EXISTS meta_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            week_start TEXT NOT NULL,
            capability_scores TEXT NOT NULL,
            service_scores TEXT NOT NULL,
            strengths TEXT,
            weaknesses TEXT,
            focus_areas TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        -- 7) 포트폴리오 수익 스냅샷
        CREATE TABLE IF NOT EXISTS revenue_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            blogs_revenue REAL DEFAULT 0,
            saas_revenue REAL DEFAULT 0,
            gumroad_revenue REAL DEFAULT 0,
            total_revenue REAL DEFAULT 0,
            goal_progress REAL DEFAULT 0,
            breakdown TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_revenue_snapshots_date ON revenue_snapshots(date);

        -- 8) A/B 테스트 (프롬프트 진화용)
        CREATE TABLE IF NOT EXISTS ab_tests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            skill_name TEXT NOT NULL,
            variant_a TEXT NOT NULL,
            variant_b TEXT NOT NULL,
            variant_a_score REAL,
            variant_b_score REAL,
            variant_a_count INTEGER DEFAULT 0,
            variant_b_count INTEGER DEFAULT 0,
            winner TEXT,
            status TEXT DEFAULT 'running',
            created_at TEXT DEFAULT (datetime('now')),
            completed_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_ab_tests_status ON ab_tests(status);

        -- v5.0 SOVEREIGN Phase 2: Discovery Engine + Universal Planner

        CREATE TABLE IF NOT EXISTS managed_services (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            category TEXT DEFAULT 'unknown',
            description TEXT,
            tech_stack TEXT DEFAULT '[]',
            port INTEGER,
            health_check TEXT,
            restart_command TEXT,
            project_path TEXT,
            dependencies TEXT DEFAULT '[]',
            status TEXT DEFAULT 'active',
            risk_level TEXT DEFAULT 'low',
            market_analysis TEXT,
            discovered_at TEXT DEFAULT (datetime('now')),
            last_checked TEXT,
            last_analysis TEXT
        );

        CREATE TABLE IF NOT EXISTS tool_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT,
            tool TEXT NOT NULL,
            input_summary TEXT,
            output_summary TEXT,
            success INTEGER,
            duration_ms INTEGER,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_tool_log_task ON tool_log(task_id);

        CREATE TABLE IF NOT EXISTS execution_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            plan_json TEXT NOT NULL,
            total_steps INTEGER,
            completed_steps INTEGER DEFAULT 0,
            replans INTEGER DEFAULT 0,
            status TEXT DEFAULT 'created',
            created_at TEXT DEFAULT (datetime('now')),
            completed_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_execution_plans_status ON execution_plans(status);

        -- v5.0 Phase 3: Feedback Queue
        CREATE TABLE IF NOT EXISTS feedback_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            task_type TEXT DEFAULT 'other',
            phase TEXT NOT NULL,
            check_after TEXT NOT NULL,
            check_method TEXT,
            check_input TEXT,
            status TEXT DEFAULT 'pending',
            score REAL,
            metadata TEXT DEFAULT '{}',
            created_at TEXT DEFAULT (datetime('now')),
            checked_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_feedback_status ON feedback_queue(status);
        CREATE INDEX IF NOT EXISTS idx_feedback_check ON feedback_queue(check_after);

        -- v5.0 Phase 4: Config 변경 이력 추적
        CREATE TABLE IF NOT EXISTS config_change_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            config_key TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT,
            reason TEXT NOT NULL,
            risk_level TEXT NOT NULL CHECK(risk_level IN ('SAFE', 'RISKY', 'DANGEROUS')),
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'approved', 'applied', 'rolled_back', 'rejected')),
            before_metric TEXT,
            after_metric TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            applied_at TEXT,
            approved_by TEXT
        );

        -- v5.0 Phase 4: 계층적 경험 메모리 (MUSE 패턴)
        -- strategic: 높은 추상화 교훈 ("PM2 서비스는 restart 후 안정화 시간 필요")
        -- procedural: 성공한 절차 패턴 ("nginx: test → reload → health check")
        -- tool: 도구 효과성 기록 ("shell_pipe가 PM2 작업에 최적")
        CREATE TABLE IF NOT EXISTS plan_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_type TEXT NOT NULL CHECK(memory_type IN ('strategic', 'procedural', 'tool')),
            content TEXT NOT NULL,
            source_task TEXT,
            source_plan_hash TEXT,
            relevance_tags TEXT,
            use_count INTEGER DEFAULT 0,
            last_used_at TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        """)
        self.conn.commit()

        # v5.0 마이그레이션: 하드코딩 0.8 제거
        self.conn.execute(
            "UPDATE plan_cache_v4 SET score = NULL WHERE score = 0.8"
        )
        self.conn.commit()

    # === 유틸리티 ===
    def _new_id(self, prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex[:12]}"

    def _kst_now(self) -> str:
        return datetime.now(config.KST).isoformat()

    def _kst_date(self) -> str:
        return datetime.now(config.KST).strftime("%Y-%m-%d")

    def _get_db(self):
        """SQLite connection 반환. 외부 모듈이 직접 쿼리할 때 사용."""
        return self.conn

    # === 태스크 (기존 APEX 호환) ===
    def create_task(self, title: str) -> str:
        task_id = self._new_id("task")
        self.conn.execute(
            "INSERT INTO tasks(id, title, status, created_at) VALUES(?,?,?,?)",
            (task_id, title[:500], "running", self._kst_now())
        )
        self.conn.commit()
        return task_id

    def log_iteration(self, task_id: str, iteration_num: int, thought: str,
                      action_type: str, action_input: str) -> str:
        iter_id = self._new_id("iter")
        self.conn.execute(
            "INSERT INTO iterations(id, task_id, iteration_num, thought, action_type, action_input, created_at) VALUES(?,?,?,?,?,?,?)",
            (iter_id, task_id, iteration_num, thought[:1000],
             action_type, action_input[:2000], self._kst_now())
        )
        self.conn.commit()
        return iter_id

    def update_iteration(self, iter_id: str, observation: str, success: bool) -> None:
        self.conn.execute(
            "UPDATE iterations SET observation=?, success=? WHERE id=?",
            (observation[:3000], 1 if success else 0, iter_id)
        )
        self.conn.commit()

    def log_reflection(self, task_id: str, what_went_wrong: str, key_insight: str) -> None:
        ref_id = self._new_id("ref")
        self.conn.execute(
            "INSERT INTO reflections(id, task_id, what_went_wrong, key_insight, created_at) VALUES(?,?,?,?,?)",
            (ref_id, task_id, what_went_wrong[:1000], key_insight[:1000], self._kst_now())
        )
        self.conn.commit()

    def complete_task(self, task_id: str, status: str, final_answer: str = "") -> None:
        self.conn.execute(
            "UPDATE tasks SET status=?, final_answer=?, completed_at=? WHERE id=?",
            (status, final_answer[:5000], self._kst_now(), task_id)
        )
        self.conn.commit()

    # === 데몬 큐 ===
    def enqueue(self, task_spec: str, priority: int = 1, mode: str = "react",
                source: str = "api") -> str:
        task_id = self._new_id("dtask")
        self.conn.execute(
            "INSERT INTO daemon_tasks(id, task_spec, priority, status, mode, source, created_at) VALUES(?,?,?,?,?,?,?)",
            (task_id, task_spec, priority, "pending", mode, source, self._kst_now())
        )
        self.conn.commit()
        return task_id

    def pop_next_pending(self) -> Optional[dict]:
        """가장 높은 우선순위 + 가장 오래된 pending 태스크."""
        row = self.conn.execute(
            "SELECT * FROM daemon_tasks WHERE status='pending' ORDER BY priority DESC, created_at ASC LIMIT 1"
        ).fetchone()
        if row:
            self.conn.execute(
                "UPDATE daemon_tasks SET status='running', started_at=? WHERE id=?",
                (self._kst_now(), row["id"])
            )
            self.conn.commit()
            return dict(row)
        return None

    def complete_daemon_task(self, task_id: str, status: str, result: str = "") -> None:
        self.conn.execute(
            "UPDATE daemon_tasks SET status=?, result=?, completed_at=? WHERE id=?",
            (status, result[:5000], self._kst_now(), task_id)
        )
        self.conn.commit()

    def count_pending(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) as cnt FROM daemon_tasks WHERE status='pending'").fetchone()
        return row["cnt"]

    def _mark_stale_running(self) -> None:
        """크래시 복구: running → pending."""
        self.conn.execute("UPDATE daemon_tasks SET status='pending' WHERE status='running'")
        self.conn.commit()

    # === 일일 예산 ===
    def get_daily_tokens(self) -> int:
        today = self._kst_date()
        row = self.conn.execute("SELECT total_tokens FROM daily_budget WHERE date=?", (today,)).fetchone()
        return row["total_tokens"] if row else 0

    def add_tokens(self, tokens: int) -> int:
        today = self._kst_date()
        now = self._kst_now()
        self.conn.execute("""
            INSERT INTO daily_budget(date, total_tokens, updated_at)
            VALUES(?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET total_tokens = total_tokens + ?, updated_at = ?
        """, (today, tokens, now, tokens, now))
        self.conn.commit()
        return self.get_daily_tokens()

    def increment_provider_calls(self, provider: str) -> None:
        today = self._kst_date()
        now = self._kst_now()
        col = f"{provider}_calls"
        allowed = ("cerebras_calls", "groq_calls", "gemini_pro_calls", "gemini_flash_calls")
        if col not in allowed:
            return
        self.conn.execute(f"""
            INSERT INTO daily_budget(date, {col}, updated_at)
            VALUES(?, 1, ?)
            ON CONFLICT(date) DO UPDATE SET {col} = {col} + 1, updated_at = ?
        """, (today, now, now))
        self.conn.commit()

    def get_provider_calls(self, provider: str) -> int:
        today = self._kst_date()
        col = f"{provider}_calls"
        allowed = ("cerebras_calls", "groq_calls", "gemini_pro_calls", "gemini_flash_calls")
        if col not in allowed:
            return 0
        row = self.conn.execute(f"SELECT {col} FROM daily_budget WHERE date=?", (today,)).fetchone()
        return row[0] if row else 0

    # === 이벤트 로그 ===
    def log_event(self, kind: str, task_id: str = "", raw_input: str = "",
                  output_preview: str = "", tier: str = "") -> str:
        event_id = f"evt_{uuid.uuid4().hex[:16]}"
        self.conn.execute(
            "INSERT INTO events(event_id, kind, task_id, raw_input, output_preview, tier, created_at) VALUES(?,?,?,?,?,?,?)",
            (event_id, kind, task_id, raw_input[:2000], output_preview[:500], tier, self._kst_now())
        )
        self.conn.commit()
        return event_id

    # === 신호 (능동적 판단 루프) ===
    def save_signal(self, kind: str, data: str) -> str:
        sig_id = self._new_id("sig")
        self.conn.execute(
            "INSERT INTO signals(id, kind, data, created_at) VALUES(?,?,?,?)",
            (sig_id, kind, data[:5000], self._kst_now())
        )
        self.conn.commit()
        return sig_id

    def get_recent_signals(self, hours: int = 6) -> list[dict]:
        cutoff = (datetime.now(config.KST) - timedelta(hours=hours)).isoformat()
        rows = self.conn.execute(
            "SELECT * FROM signals WHERE created_at > ? ORDER BY created_at DESC",
            (cutoff,)
        ).fetchall()
        return [dict(r) for r in rows]

    # === 태스크 이력 ===
    def get_task_history(self, task_id: str) -> dict:
        task = self.conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        iterations = self.conn.execute(
            "SELECT * FROM iterations WHERE task_id=? ORDER BY iteration_num", (task_id,)
        ).fetchall()
        reflections = self.conn.execute(
            "SELECT * FROM reflections WHERE task_id=?", (task_id,)
        ).fetchall()
        return {
            "task": dict(task) if task else None,
            "iterations": [dict(i) for i in iterations],
            "reflections": [dict(r) for r in reflections],
        }

    def get_recent_tasks(self, limit: int = 10) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    # === v3.3 Traces ===
    def log_trace(self, trace_id: str, span_type: str, provider: str = "",
                  model: str = "", input_tokens: int = 0, output_tokens: int = 0,
                  latency_ms: int = 0, status: str = "ok",
                  error_type: str = None, metadata: str = None) -> None:
        """LLM 호출 / 도구 실행 trace 기록."""
        self.conn.execute(
            "INSERT INTO traces(trace_id,span_type,provider,model,"
            "input_tokens,output_tokens,latency_ms,status,error_type,metadata,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (trace_id, span_type, provider or "", model or "",
             input_tokens, output_tokens, latency_ms, status,
             error_type, metadata, self._kst_now())
        )
        self.conn.commit()

    def get_provider_stats(self, hours: int = 24) -> list[dict]:
        """최근 N시간 프로바이더별 통계."""
        cutoff = (datetime.now(config.KST) - timedelta(hours=hours)).isoformat()
        rows = self.conn.execute("""
            SELECT provider,
                   COUNT(*) as calls,
                   SUM(input_tokens + output_tokens) as total_tokens,
                   CAST(AVG(latency_ms) AS INTEGER) as avg_latency,
                   SUM(CASE WHEN status != 'ok' THEN 1 ELSE 0 END) as errors
            FROM traces
            WHERE span_type = 'llm_call' AND created_at > ?
            GROUP BY provider
        """, (cutoff,)).fetchall()
        return [dict(r) for r in rows]

    # === v3.3 Plan Cache ===
    def cache_plan(self, keywords: str, task_pattern: str, plan_json: str) -> int:
        cur = self.conn.execute(
            """INSERT INTO plan_cache(keywords, task_pattern, plan_json, last_used, created_at)
               VALUES(?,?,?,?,?)""",
            (keywords, task_pattern, plan_json, self._kst_now(), self._kst_now())
        )
        self.conn.commit()
        return cur.lastrowid

    def get_cached_plan(self, keywords: str) -> Optional[dict]:
        row = self.conn.execute(
            """SELECT * FROM plan_cache WHERE keywords=?
               ORDER BY success_count DESC, last_used DESC LIMIT 1""",
            (keywords,)
        ).fetchone()
        if row:
            self.conn.execute(
                "UPDATE plan_cache SET last_used=? WHERE id=?",
                (self._kst_now(), row["id"])
            )
            self.conn.commit()
            return dict(row)
        return None

    def update_plan_stats(self, plan_id: int, success: bool) -> None:
        col = "success_count" if success else "fail_count"
        self.conn.execute(
            f"UPDATE plan_cache SET {col} = {col} + 1 WHERE id=?", (plan_id,)
        )
        self.conn.commit()

    # === v3.3 Biz Metrics ===
    def log_biz_metric(self, metric_type: str, metric_name: str,
                       value: float, unit: str = "", metadata: str = None) -> None:
        """비즈니스 지표 기록."""
        self.conn.execute(
            "INSERT INTO biz_metrics(metric_type,metric_name,value,unit,metadata,measured_at) "
            "VALUES(?,?,?,?,?,?)",
            (metric_type, metric_name, value, unit, metadata, self._kst_now())
        )
        self.conn.commit()

    # === v3.3 Signal Helpers ===
    def count_signals(self, kind: str, date_prefix: str = None) -> int:
        """특정 kind의 signal 수 카운트."""
        if date_prefix:
            row = self.conn.execute(
                "SELECT COUNT(*) FROM signals WHERE kind=? AND created_at LIKE ?",
                (kind, f"{date_prefix}%")
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT COUNT(*) FROM signals WHERE kind=?", (kind,)
            ).fetchone()
        return row[0] if row else 0

    def get_signals_by_date(self, date: str) -> list[dict]:
        """특정 날짜의 모든 signal 조회."""
        rows = self.conn.execute(
            "SELECT * FROM signals WHERE created_at LIKE ? ORDER BY created_at",
            (f"{date}%",)
        ).fetchall()
        return [dict(r) for r in rows]

    # === v3.3 Discoveries ===
    def save_discovery(self, discovery_type: str, source_skill: str, detail: str,
                       interpretation: str = None, affected_services: str = None,
                       impact_level: str = "medium") -> int:
        """발견 기록 저장."""
        cur = self.conn.execute(
            "INSERT INTO discoveries(discovery_type, source_skill, detail, "
            "interpretation, affected_services, impact_level) VALUES(?,?,?,?,?,?)",
            (discovery_type, source_skill, detail, interpretation, affected_services, impact_level)
        )
        self.conn.commit()
        return cur.lastrowid

    def get_pending_discoveries(self) -> list[dict]:
        """처리 대기 중인 발견 목록."""
        rows = self.conn.execute(
            "SELECT * FROM discoveries WHERE status IN ('new', 'processing') ORDER BY created_at"
        ).fetchall()
        return [dict(r) for r in rows]

    def update_discovery_status(self, discovery_id: int, status: str, actions_taken: str = None) -> None:
        """발견 상태 업데이트."""
        self.conn.execute(
            "UPDATE discoveries SET status=?, actions_taken=?, updated_at=datetime('now') WHERE id=?",
            (status, actions_taken, discovery_id)
        )
        self.conn.commit()

    # === v3.3 Evolutions ===
    def save_evolution(self, tech_name: str, tech_description: str = None,
                       source: str = None, git_backup_tag: str = None) -> int:
        """진화 시도 기록."""
        cur = self.conn.execute(
            "INSERT INTO evolutions(tech_name, tech_description, source, git_backup_tag) VALUES(?,?,?,?)",
            (tech_name, tech_description, source, git_backup_tag)
        )
        self.conn.commit()
        return cur.lastrowid

    def complete_evolution(self, evolution_id: int, status: str,
                           changes: str = None, test_results: str = None) -> None:
        """진화 완료 기록."""
        self.conn.execute(
            "UPDATE evolutions SET status=?, changes=?, test_results=?, "
            "completed_at=datetime('now') WHERE id=?",
            (status, changes, test_results, evolution_id)
        )
        self.conn.commit()

    def count_daily_evolutions(self) -> int:
        """오늘 진화 횟수."""
        today = self._kst_date()
        row = self.conn.execute(
            "SELECT COUNT(*) FROM evolutions WHERE created_at LIKE ? AND status='success'",
            (f"{today}%",)
        ).fetchone()
        return row[0] if row else 0

    # === v3.3 Phase 4 Part D+E: SaaS & Gumroad 헬퍼 ===

    def save_saas_health(self, product_name: str, active: int = 0, past_due: int = 0,
                         cancelled: int = 0, paused: int = 0, mrr_cents: int = 0,
                         total_revenue_cents: int = 0, total_orders: int = 0,
                         total_customers: int = 0, metadata: str = None) -> int:
        """SaaS 헬스 스냅샷 저장."""
        cur = self.conn.execute(
            """INSERT INTO saas_health(product_name, active_subs, past_due_subs,
               cancelled_subs, paused_subs, mrr_cents, arr_cents,
               total_revenue_cents, total_orders, total_customers, metadata, measured_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (product_name, active, past_due, cancelled, paused,
             mrr_cents, mrr_cents * 12, total_revenue_cents, total_orders,
             total_customers, metadata, self._kst_now())
        )
        self.conn.commit()
        return cur.lastrowid

    def get_latest_saas_health(self, product_name: str = None) -> list[dict]:
        """최신 SaaS 헬스 데이터. product_name=None이면 전체."""
        if product_name:
            rows = self.conn.execute(
                """SELECT * FROM saas_health WHERE product_name=?
                   ORDER BY measured_at DESC LIMIT 1""",
                (product_name,)
            ).fetchall()
        else:
            rows = self.conn.execute(
                """SELECT sh.* FROM saas_health sh
                   INNER JOIN (
                       SELECT product_name, MAX(measured_at) as max_at
                       FROM saas_health GROUP BY product_name
                   ) latest ON sh.product_name = latest.product_name
                   AND sh.measured_at = latest.max_at"""
            ).fetchall()
        return [dict(r) for r in rows]

    def save_gumroad_sale(self, sale_id: str, product_id: str, product_name: str,
                          email: str, price_cents: int, currency: str = "usd",
                          sale_timestamp: str = None, metadata: str = None) -> int:
        """Gumroad 판매 기록."""
        cur = self.conn.execute(
            """INSERT OR IGNORE INTO gumroad_sales(sale_id, product_id, product_name,
               email, price_cents, currency, sale_timestamp, metadata)
               VALUES(?,?,?,?,?,?,?,?)""",
            (sale_id, product_id, product_name, email, price_cents,
             currency, sale_timestamp or self._kst_now(), metadata)
        )
        self.conn.commit()
        return cur.lastrowid

    def get_gumroad_revenue(self, days: int = 30) -> dict:
        """최근 N일 Gumroad 수익 요약."""
        row = self.conn.execute(
            """SELECT COUNT(*) as sales, COALESCE(SUM(price_cents), 0) as total_cents
               FROM gumroad_sales
               WHERE refunded=0 AND created_at > datetime('now', ?)""",
            (f"-{days} days",)
        ).fetchone()
        return {"sales": row[0], "total_cents": row[1], "total_usd": row[1] / 100.0}

    def save_feature_request(self, product_name: str, title: str,
                             description: str = "", source: str = "manual",
                             category: str = "feature_request",
                             user_email: str = "") -> int:
        """피드백/기능요청 저장."""
        cur = self.conn.execute(
            """INSERT INTO feature_requests(product_name, source, category,
               title, description, user_email) VALUES(?,?,?,?,?,?)""",
            (product_name, source, category, title, description, user_email)
        )
        self.conn.commit()
        return cur.lastrowid

    def save_email_campaign(self, campaign_type: str, product_name: str,
                            recipient_email: str, subject: str,
                            trigger_event: str = "") -> int:
        """이메일 캠페인 기록."""
        cur = self.conn.execute(
            """INSERT INTO email_campaigns(campaign_type, product_name,
               recipient_email, subject, trigger_event) VALUES(?,?,?,?,?)""",
            (campaign_type, product_name, recipient_email, subject, trigger_event)
        )
        self.conn.commit()
        return cur.lastrowid

    def update_email_status(self, campaign_id: int, status: str) -> None:
        """이메일 상태 업데이트."""
        col = "sent_at" if status == "sent" else ("opened_at" if status == "opened" else "clicked_at")
        self.conn.execute(
            f"UPDATE email_campaigns SET status=?, {col}=? WHERE id=?",
            (status, self._kst_now(), campaign_id)
        )
        self.conn.commit()

    def save_launch(self, product_name: str, target_date: str,
                    launch_type: str = "new_product", channels: str = "") -> int:
        """런치 계획 저장."""
        cur = self.conn.execute(
            """INSERT INTO launches(product_name, launch_type, target_date, channels)
               VALUES(?,?,?,?)""",
            (product_name, launch_type, target_date, channels)
        )
        self.conn.commit()
        return cur.lastrowid

    def update_launch(self, launch_id: int, status: str = None,
                      pre_launch_done: str = None, launch_day_done: str = None,
                      post_launch_done: str = None, results: str = None) -> None:
        """런치 상태 업데이트."""
        updates = []
        params = []
        if status:
            updates.append("status=?")
            params.append(status)
        if pre_launch_done:
            updates.append("pre_launch_done=?")
            params.append(pre_launch_done)
        if launch_day_done:
            updates.append("launch_day_done=?")
            params.append(launch_day_done)
        if post_launch_done:
            updates.append("post_launch_done=?")
            params.append(post_launch_done)
        if results:
            updates.append("results=?")
            params.append(results)
        if updates:
            updates.append("updated_at=datetime('now')")
            params.append(launch_id)
            self.conn.execute(
                f"UPDATE launches SET {', '.join(updates)} WHERE id=?", tuple(params)
            )
            self.conn.commit()

    # === v4.0 plan_cache 메서드 ===

    def cache_plan_v4(self, task_pattern: str, skills_used: list,
                      procedure: str, steps: int, tokens: int,
                      score: float = None):
        """성공한 태스크의 절차를 캐싱. score는 실측값만 저장 (None=미검증)."""
        import json
        self.conn.execute("""
            INSERT INTO plan_cache_v4 (task_pattern, skills_used, procedure,
                                      steps, tokens, score, created_at, used_count)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'), 0)
        """, [task_pattern, json.dumps(skills_used), procedure, steps, tokens, score])
        self.conn.commit()

    def find_cached_plan_v4(self, task: str, threshold: float = 0.0) -> Optional[dict]:
        """유사 태스크의 캐싱된 절차 검색.

        score=NULL → 아직 미검증. 한번 써볼 가치는 있음.
        score<0.3 → 실패한 계획. 제외.
        """
        plans = self.conn.execute("""
            SELECT task_pattern, procedure, score, used_count
            FROM plan_cache_v4
            WHERE created_at > datetime('now', '-30 days')
            AND (score IS NULL OR score >= ?)
            ORDER BY
                CASE WHEN score IS NULL THEN 0.5 ELSE score END DESC,
                used_count DESC
            LIMIT 5
        """, [threshold]).fetchall()
        if not plans:
            return None
        return {
            'task_pattern': plans[0][0],
            'procedure': plans[0][1],
            'score': plans[0][2],  # None일 수 있음 = 미검증
            'used_count': plans[0][3]
        }

    def increment_plan_usage_v4(self, task_pattern: str):
        """plan_cache_v4 used_count 증가."""
        self.conn.execute("""
            UPDATE plan_cache_v4 SET used_count = used_count + 1,
            last_used = datetime('now')
            WHERE task_pattern = ?
        """, [task_pattern])
        self.conn.commit()

    def update_plan_score(self, task_pattern: str, measured_score: float):
        """plan_cache_v4 점수를 실측값으로 직접 교체.

        EMA 아님. 가장 최근 실측값이 진실.
        히스토리가 필요하면 feedback_queue에서 조회.
        """
        self.conn.execute("""
            UPDATE plan_cache_v4 SET score = ?
            WHERE task_pattern LIKE ?
        """, (measured_score, f"%{task_pattern[:50]}%"))
        self.conn.commit()

    # === v4.0 reflections 메서드 ===

    def save_reflection_v4(self, task_pattern: str, failure_reason: str,
                           lesson: str, suggested_approach: str):
        """실패 반성을 저장 (v4.0)."""
        self.conn.execute("""
            INSERT INTO reflections_v4 (task_pattern, failure_reason, lesson,
                                       suggested_approach, created_at)
            VALUES (?, ?, ?, ?, datetime('now'))
        """, [task_pattern, failure_reason, lesson, suggested_approach])
        self.conn.commit()

    def get_recent_reflections_v4(self, limit: int = 5) -> list:
        """최근 반성 조회 (v4.0)."""
        rows = self.conn.execute("""
            SELECT task_pattern, failure_reason, lesson, suggested_approach
            FROM reflections_v4
            WHERE created_at > datetime('now', '-30 days')
            ORDER BY created_at DESC
            LIMIT ?
        """, [limit]).fetchall()
        return [{'task_pattern': r[0], 'failure_reason': r[1],
                 'lesson': r[2], 'suggested_approach': r[3]} for r in rows]

    # === v4.0 known_services 메서드 ===

    def get_known_services(self) -> list:
        """등록된 서비스 목록."""
        rows = self.conn.execute(
            "SELECT name FROM known_services WHERE status = 'active'"
        ).fetchall()
        return [r[0] for r in rows]

    def register_service(self, name: str, type_: str, port: int = None,
                         domain: str = None, config_path: str = None, meta: dict = None):
        """새 서비스 등록."""
        import json
        self.conn.execute("""
            INSERT OR IGNORE INTO known_services (name, type, port, domain, config_path, meta)
            VALUES (?, ?, ?, ?, ?, ?)
        """, [name, type_, port, domain, config_path, json.dumps(meta or {})])
        self.conn.commit()

    # === v4.0 count/budget 유틸 ===

    def count_signals_v4(self, type_: str, days: int = 7) -> int:
        """특정 타입의 최근 시그널 수."""
        row = self.conn.execute("""
            SELECT COUNT(*) FROM signals
            WHERE kind = ? AND created_at > datetime('now', ? || ' days')
        """, [type_, f'-{days}']).fetchone()
        return row[0] if row else 0

    def get_monthly_usage(self, provider: str) -> int:
        """월간 토큰 사용량 조회."""
        row = self.conn.execute("""
            SELECT COALESCE(SUM(total_tokens), 0)
            FROM daily_budget
            WHERE date >= date('now', 'start of month')
        """).fetchone()
        return row[0] if row else 0

    # === v4.0 signal 헬퍼 (기존 save_signal 래퍼) ===

    def add_signal(self, type_: str, data: dict):
        """signal 저장 (dict 입력 지원)."""
        import json
        data_str = json.dumps(data, ensure_ascii=False) if isinstance(data, dict) else str(data)
        return self.save_signal(type_, data_str)

    # ========== v4.0 ULTIMATE 헬퍼 메서드 ==========

    # === task_queue (Goal → Auto-Execute) ===

    def enqueue_task(self, task_type: str, target_service: str, action: str,
                     parameters: dict = None, parent_goal: str = None,
                     sub_goal: str = None, priority: int = 50,
                     frequency: str = "once", next_run: str = None) -> int:
        """태스크 큐에 작업 등록."""
        import json
        cur = self.conn.execute("""
            INSERT INTO task_queue (task_type, target_service, action, parameters,
                                   parent_goal, sub_goal, priority, frequency,
                                   status, created_at, next_run)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
        """, [task_type, target_service, action,
              json.dumps(parameters or {}), parent_goal, sub_goal,
              priority, frequency, self._kst_now(), next_run or self._kst_now()])
        self.conn.commit()
        return cur.lastrowid

    def get_pending_tasks_queue(self, limit: int = 10) -> list:
        """우선순위 순으로 대기 태스크 조회."""
        rows = self.conn.execute("""
            SELECT * FROM task_queue
            WHERE status = 'pending' AND (next_run IS NULL OR next_run <= ?)
            ORDER BY priority DESC, created_at ASC
            LIMIT ?
        """, [self._kst_now(), limit]).fetchall()
        return [dict(r) for r in rows]

    def update_task_queue_status(self, task_id: int, status: str,
                                  result: str = None, error_log: str = None):
        """태스크 큐 상태 업데이트."""
        import json
        if status == 'done':
            self.conn.execute("""
                UPDATE task_queue SET status=?, result=?, completed_at=?
                WHERE id=?
            """, [status, json.dumps(result) if result else None,
                  self._kst_now(), task_id])
        elif status == 'failed':
            self.conn.execute("""
                UPDATE task_queue SET status=?, error_log=?, retry_count=retry_count+1
                WHERE id=?
            """, [status, error_log, task_id])
        else:
            self.conn.execute("UPDATE task_queue SET status=? WHERE id=?",
                             [status, task_id])
        self.conn.commit()

    def get_goal_tasks_from_queue(self, parent_goal: str) -> list:
        """특정 목표의 모든 태스크 조회."""
        rows = self.conn.execute("""
            SELECT * FROM task_queue WHERE parent_goal=?
            ORDER BY priority DESC, created_at ASC
        """, [parent_goal]).fetchall()
        return [dict(r) for r in rows]

    def pop_next_task(self) -> dict:
        """다음 실행할 태스크를 가져오고 running 상태로 변경."""
        row = self.conn.execute("""
            SELECT * FROM task_queue
            WHERE status = 'pending' AND (next_run IS NULL OR next_run <= ?)
            ORDER BY priority DESC, created_at ASC
            LIMIT 1
        """, [self._kst_now()]).fetchone()

        if not row:
            return None

        task = dict(row)
        self.conn.execute("""
            UPDATE task_queue SET status='running', started_at=?
            WHERE id=?
        """, [self._kst_now(), task['id']])
        self.conn.commit()
        return task

    def complete_task_queue_item(self, task_id: int, status: str, result: str = None):
        """태스크 큐 아이템 완료 처리."""
        import json
        if status == 'done':
            self.conn.execute("""
                UPDATE task_queue SET status=?, result=?, completed_at=?
                WHERE id=?
            """, [status, result, self._kst_now(), task_id])
        else:
            self.conn.execute("""
                UPDATE task_queue SET status=?, error_log=?, retry_count=retry_count+1
                WHERE id=?
            """, [status, result, task_id])
        self.conn.commit()

    # === boss_feedback (Quality Gate 캘리브레이션) ===

    def save_boss_feedback(self, task_id: str, result_type: str,
                           llm_score: float, boss_score: float = None,
                           boss_comment: str = None) -> int:
        """보스 피드백 저장."""
        cur = self.conn.execute("""
            INSERT INTO boss_feedback (task_id, result_type, llm_score,
                                       boss_score, boss_comment, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, [task_id, result_type, llm_score, boss_score,
              boss_comment, self._kst_now()])
        self.conn.commit()
        return cur.lastrowid

    def get_calibration_offset(self, result_type: str, limit: int = 10) -> float:
        """보스 피드백 기반 점수 보정값 계산."""
        rows = self.conn.execute("""
            SELECT llm_score, boss_score FROM boss_feedback
            WHERE result_type=? AND boss_score IS NOT NULL
            ORDER BY created_at DESC LIMIT ?
        """, [result_type, limit]).fetchall()
        if not rows:
            return 0.0
        avg_llm = sum(r[0] for r in rows) / len(rows)
        avg_boss = sum(r[1] for r in rows) / len(rows)
        return avg_boss - avg_llm

    # === supervised_agents (에이전트 감시) ===

    def register_agent(self, name: str, agent_type: str, **kwargs) -> int:
        """새 에이전트 등록."""
        import json
        cols = ['name', 'agent_type']
        vals = [name, agent_type]
        for key in ['container_name', 'workflow_id', 'process_name', 'cron_pattern',
                    'health_url', 'auto_recover', 'enabled', 'status', 'skill_ref',
                    'purpose', 'dependencies', 'discovered_at']:
            if key in kwargs:
                cols.append(key)
                val = kwargs[key]
                if key == 'dependencies' and isinstance(val, (list, dict)):
                    val = json.dumps(val)
                vals.append(val)

        placeholders = ','.join(['?'] * len(vals))
        col_str = ','.join(cols)
        cur = self.conn.execute(
            f"INSERT OR REPLACE INTO supervised_agents ({col_str}) VALUES ({placeholders})",
            vals
        )
        self.conn.commit()
        return cur.lastrowid

    def get_all_agents(self, enabled_only: bool = True) -> list:
        """모든 감시 대상 에이전트 조회."""
        if enabled_only:
            rows = self.conn.execute(
                "SELECT * FROM supervised_agents WHERE enabled=1"
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM supervised_agents").fetchall()
        return [dict(r) for r in rows]

    def get_known_agent_names(self, agent_type: str) -> list:
        """특정 타입의 알려진 에이전트 이름 목록."""
        rows = self.conn.execute(
            "SELECT name FROM supervised_agents WHERE agent_type=?",
            [agent_type]
        ).fetchall()
        return [r[0] for r in rows]

    def update_agent_status(self, agent_id: int, status: str, details: dict = None):
        """에이전트 상태 업데이트."""
        now = self._kst_now()
        if status == 'healthy':
            self.conn.execute("""
                UPDATE supervised_agents SET status=?, last_check=?, last_healthy=?
                WHERE id=?
            """, [status, now, now, agent_id])
        else:
            self.conn.execute("""
                UPDATE supervised_agents SET status=?, last_check=? WHERE id=?
            """, [status, now, agent_id])
        self.conn.commit()

    def count_recent_restarts(self, agent_id: int, hours: int = 24) -> int:
        """최근 N시간 내 재시작 횟수."""
        row = self.conn.execute("""
            SELECT COUNT(*) FROM agent_restarts
            WHERE agent_id=? AND created_at > datetime('now', ?)
        """, [agent_id, f'-{hours} hours']).fetchone()
        return row[0] if row else 0

    def log_restart(self, agent_id: int, command: str, success: bool,
                    error: str = None) -> int:
        """에이전트 재시작 로그."""
        cur = self.conn.execute("""
            INSERT INTO agent_restarts (agent_id, command, success, error)
            VALUES (?, ?, ?, ?)
        """, [agent_id, command, 1 if success else 0, error])
        self.conn.commit()
        return cur.lastrowid

    # === dynamic_skills (동적 스킬 상태) ===

    def register_dynamic_skill(self, skill_name: str, skill_path: str,
                                source: str, metadata: dict = None) -> int:
        """동적 스킬 등록."""
        import json
        cur = self.conn.execute("""
            INSERT OR IGNORE INTO dynamic_skills
            (skill_name, skill_path, source, status, metadata)
            VALUES (?, ?, ?, 'unverified', ?)
        """, [skill_name, skill_path, source, json.dumps(metadata or {})])
        self.conn.commit()
        return cur.lastrowid

    def increment_skill_success(self, skill_name: str) -> int:
        """스킬 성공 카운트 증가, 연속 성공 수 반환."""
        self.conn.execute("""
            UPDATE dynamic_skills SET
                success_count = success_count + 1,
                consecutive_successes = consecutive_successes + 1,
                last_used = datetime('now')
            WHERE skill_name=?
        """, [skill_name])
        self.conn.commit()
        row = self.conn.execute(
            "SELECT consecutive_successes FROM dynamic_skills WHERE skill_name=?",
            [skill_name]
        ).fetchone()
        return row[0] if row else 0

    def reset_skill_success(self, skill_name: str):
        """스킬 연속 성공 리셋 (실패 시)."""
        self.conn.execute("""
            UPDATE dynamic_skills SET
                failure_count = failure_count + 1,
                consecutive_successes = 0,
                last_used = datetime('now')
            WHERE skill_name=?
        """, [skill_name])
        self.conn.commit()

    def update_skill_status(self, skill_name: str, status: str):
        """스킬 상태 업데이트."""
        now = self._kst_now()
        if status == 'verified':
            self.conn.execute("""
                UPDATE dynamic_skills SET status=?, verified_at=? WHERE skill_name=?
            """, [status, now, skill_name])
        else:
            self.conn.execute(
                "UPDATE dynamic_skills SET status=? WHERE skill_name=?",
                [status, skill_name]
            )
        self.conn.commit()

    def get_skill_status(self, skill_name: str) -> Optional[dict]:
        """스킬 상태 조회."""
        row = self.conn.execute(
            "SELECT * FROM dynamic_skills WHERE skill_name=?", [skill_name]
        ).fetchone()
        return dict(row) if row else None

    # === meta_reviews (메타인지 리뷰) ===

    def save_meta_review(self, week_start: str, capability_scores: dict,
                         service_scores: dict, strengths: list = None,
                         weaknesses: list = None, focus_areas: list = None) -> int:
        """메타인지 리뷰 저장."""
        import json
        cur = self.conn.execute("""
            INSERT INTO meta_reviews (week_start, capability_scores, service_scores,
                                      strengths, weaknesses, focus_areas)
            VALUES (?, ?, ?, ?, ?, ?)
        """, [week_start, json.dumps(capability_scores), json.dumps(service_scores),
              json.dumps(strengths or []), json.dumps(weaknesses or []),
              json.dumps(focus_areas or [])])
        self.conn.commit()
        return cur.lastrowid

    def get_latest_meta_review(self) -> Optional[dict]:
        """최신 메타인지 리뷰 조회."""
        row = self.conn.execute("""
            SELECT * FROM meta_reviews ORDER BY created_at DESC LIMIT 1
        """).fetchone()
        return dict(row) if row else None

    # === revenue_snapshots (수익 스냅샷) ===

    def save_revenue_snapshot(self, blogs_revenue: float = 0, saas_revenue: float = 0,
                               gumroad_revenue: float = 0, goal_progress: float = 0,
                               breakdown: dict = None) -> int:
        """수익 스냅샷 저장."""
        import json
        total = blogs_revenue + saas_revenue + gumroad_revenue
        cur = self.conn.execute("""
            INSERT INTO revenue_snapshots (date, blogs_revenue, saas_revenue,
                                          gumroad_revenue, total_revenue,
                                          goal_progress, breakdown)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, [self._kst_date(), blogs_revenue, saas_revenue, gumroad_revenue,
              total, goal_progress, json.dumps(breakdown or {})])
        self.conn.commit()
        return cur.lastrowid

    def get_revenue_history(self, days: int = 30) -> list:
        """최근 수익 히스토리."""
        rows = self.conn.execute("""
            SELECT * FROM revenue_snapshots
            WHERE date > date('now', ?)
            ORDER BY date DESC
        """, [f'-{days} days']).fetchall()
        return [dict(r) for r in rows]

    def get_latest_revenue(self) -> Optional[dict]:
        """최신 수익 스냅샷."""
        row = self.conn.execute("""
            SELECT * FROM revenue_snapshots ORDER BY date DESC LIMIT 1
        """).fetchone()
        return dict(row) if row else None

    # === ab_tests (A/B 테스트) ===

    def register_ab_test(self, skill_name: str, variant_a: str,
                          variant_b: str) -> int:
        """A/B 테스트 등록."""
        cur = self.conn.execute("""
            INSERT INTO ab_tests (skill_name, variant_a, variant_b, status)
            VALUES (?, ?, ?, 'running')
        """, [skill_name, variant_a, variant_b])
        self.conn.commit()
        return cur.lastrowid

    def update_ab_test_score(self, test_id: int, variant: str, score: float):
        """A/B 테스트 점수 업데이트."""
        if variant == 'a':
            self.conn.execute("""
                UPDATE ab_tests SET
                    variant_a_score = COALESCE((variant_a_score * variant_a_count + ?) / (variant_a_count + 1), ?),
                    variant_a_count = variant_a_count + 1
                WHERE id=?
            """, [score, score, test_id])
        else:
            self.conn.execute("""
                UPDATE ab_tests SET
                    variant_b_score = COALESCE((variant_b_score * variant_b_count + ?) / (variant_b_count + 1), ?),
                    variant_b_count = variant_b_count + 1
                WHERE id=?
            """, [score, score, test_id])
        self.conn.commit()

    def complete_ab_test(self, test_id: int):
        """A/B 테스트 완료 + 승자 결정."""
        row = self.conn.execute(
            "SELECT variant_a_score, variant_b_score FROM ab_tests WHERE id=?",
            [test_id]
        ).fetchone()
        if row:
            winner = 'a' if (row[0] or 0) >= (row[1] or 0) else 'b'
            self.conn.execute("""
                UPDATE ab_tests SET status='completed', winner=?, completed_at=?
                WHERE id=?
            """, [winner, self._kst_now(), test_id])
            self.conn.commit()

    def get_running_ab_tests(self) -> list:
        """실행 중인 A/B 테스트 목록."""
        rows = self.conn.execute(
            "SELECT * FROM ab_tests WHERE status='running'"
        ).fetchall()
        return [dict(r) for r in rows]

    # === 추가 유틸리티 ===

    def get_capability_results(self, capability: str, days: int = 7) -> list:
        """역량별 최근 결과 조회 (plan_cache_v4에서)."""
        rows = self.conn.execute("""
            SELECT * FROM plan_cache_v4
            WHERE skills_used LIKE ? AND created_at > datetime('now', ?)
            ORDER BY created_at DESC
        """, [f'%{capability}%', f'-{days} days']).fetchall()
        return [dict(r) for r in rows]

    def get_service_results(self, service_name: str, days: int = 7) -> list:
        """서비스별 최근 결과 조회."""
        rows = self.conn.execute("""
            SELECT * FROM task_queue
            WHERE target_service=? AND created_at > datetime('now', ?)
            ORDER BY created_at DESC
        """, [service_name, f'-{days} days']).fetchall()
        return [dict(r) for r in rows]

    def count_similar_successes(self, target_type: str, action: str) -> int:
        """유사 성공 태스크 수."""
        row = self.conn.execute("""
            SELECT COUNT(*) FROM task_queue
            WHERE task_type=? AND action=? AND status='done'
        """, [target_type, action]).fetchone()
        return row[0] if row else 0

    # ========== v5.0 SOVEREIGN Phase 2 헬퍼 메서드 ==========

    # === managed_services 메서드 ===

    def register_managed_service(self, data: dict):
        """서비스 upsert (managed_services 테이블)."""
        import json as _json
        self.conn.execute("""
            INSERT INTO managed_services (name, category, description, tech_stack, port,
                health_check, restart_command, project_path, dependencies, risk_level)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                category=excluded.category, description=excluded.description,
                tech_stack=excluded.tech_stack, port=excluded.port,
                health_check=excluded.health_check, restart_command=excluded.restart_command,
                project_path=excluded.project_path, dependencies=excluded.dependencies,
                risk_level=excluded.risk_level, last_checked=datetime('now')
        """, (data.get("name"), data.get("category", "unknown"),
              data.get("description", ""),
              _json.dumps(data.get("tech_stack", [])) if isinstance(data.get("tech_stack"), list) else data.get("tech_stack", "[]"),
              data.get("port"),
              data.get("health_check", ""), data.get("restart_command", ""),
              data.get("project_path", ""),
              _json.dumps(data.get("dependencies", [])) if isinstance(data.get("dependencies"), list) else data.get("dependencies", "[]"),
              data.get("risk_level", "low")))
        self.conn.commit()

    def get_all_services(self) -> list:
        """모든 managed_services 조회."""
        rows = self.conn.execute(
            "SELECT * FROM managed_services WHERE status != 'deleted' ORDER BY name"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_service(self, name: str):
        """특정 managed_service 조회."""
        row = self.conn.execute(
            "SELECT * FROM managed_services WHERE name = ?", (name,)
        ).fetchone()
        return dict(row) if row else None

    def update_service_status(self, name: str, status: str):
        """managed_service 상태 업데이트."""
        self.conn.execute(
            "UPDATE managed_services SET status=?, last_checked=datetime('now') WHERE name=?",
            (status, name))
        self.conn.commit()

    # === tool_log 메서드 ===

    def log_tool_execution(self, task_id, tool, input_data, output, success, duration_ms):
        """도구 실행 로그 저장."""
        self.conn.execute(
            "INSERT INTO tool_log (task_id, tool, input_summary, output_summary, success, duration_ms) VALUES (?,?,?,?,?,?)",
            (task_id, tool, str(input_data)[:500], str(output)[:500], int(success), duration_ms))
        self.conn.commit()

    # === execution_plans 메서드 ===

    def save_execution_plan(self, task_id, plan_json, total_steps):
        """실행 계획 저장."""
        cur = self.conn.execute(
            "INSERT INTO execution_plans (task_id, plan_json, total_steps) VALUES (?,?,?)",
            (task_id, plan_json, total_steps))
        self.conn.commit()
        return cur.lastrowid

    def update_plan_progress(self, plan_id, completed_steps, status):
        """계획 진행 상태 업데이트."""
        self.conn.execute("""
            UPDATE execution_plans SET completed_steps=?, status=?,
            completed_at=CASE WHEN ?='completed' THEN datetime('now') ELSE completed_at END
            WHERE id=?""",
            (completed_steps, status, status, plan_id))
        self.conn.commit()

    # === find_similar_plans (plan_cache_v4 활용) ===

    def find_similar_plans(self, task: str, top_k: int = 3) -> list:
        """plan_cache_v4에서 유사 계획 검색 (키워드). NULL=미검증도 포함."""
        words = task.lower().split()[:5]
        results = []
        seen = set()
        for word in words:
            if len(word) < 3:
                continue
            rows = self.conn.execute(
                """SELECT * FROM plan_cache_v4
                   WHERE task_pattern LIKE ? AND (score IS NULL OR score >= 0.3)
                   ORDER BY CASE WHEN score IS NULL THEN 0.5 ELSE score END DESC
                   LIMIT ?""",
                (f"%{word}%", top_k)).fetchall()
            for r in rows:
                d = dict(r)
                if d["task_pattern"] not in seen:
                    seen.add(d["task_pattern"])
                    results.append(d)
        return results[:top_k]

    # === enqueue_simple_task 헬퍼 ===

    def enqueue_simple_task(self, title: str, source: str = "system", priority: int = 5):
        """daemon_tasks에 간단한 태스크 추가."""
        self.conn.execute(
            "INSERT INTO daemon_tasks (id, task_spec, source, priority, status, created_at) VALUES (?, ?, ?, ?, 'pending', ?)",
            (self._new_id("dtask"), title, source, priority, self._kst_now()))
        self.conn.commit()

    # ========== v5.0 Phase 3: feedback_queue 메서드 ==========

    def enqueue_feedback(self, task_id, task_type, phase, check_after,
                         check_method="", check_input="", metadata=None):
        """피드백 체크 큐에 등록."""
        import json as _json
        self.conn.execute("""
            INSERT INTO feedback_queue (task_id, task_type, phase, check_after,
                check_method, check_input, metadata) VALUES (?,?,?,?,?,?,?)
        """, (task_id, task_type, phase, check_after,
              check_method, check_input, _json.dumps(metadata or {})))
        self.conn.commit()

    def get_due_feedback(self):
        """due된 피드백 체크 조회."""
        rows = self.conn.execute("""
            SELECT * FROM feedback_queue
            WHERE status='pending' AND check_after <= datetime('now')
            ORDER BY check_after LIMIT 10
        """).fetchall()
        return [dict(r) for r in rows]

    def complete_feedback(self, fid, score):
        """피드백 체크 완료."""
        self.conn.execute("""
            UPDATE feedback_queue SET status='checked', score=?, checked_at=datetime('now')
            WHERE id=?
        """, (score, fid))
        self.conn.commit()

    def get_feedback_stats(self, days=30):
        """피드백 통계."""
        rows = self.conn.execute("""
            SELECT task_type, COUNT(*) as total, AVG(score) as avg_score,
                SUM(CASE WHEN score >= 0.8 THEN 1 ELSE 0 END) as good,
                SUM(CASE WHEN score < 0.3 THEN 1 ELSE 0 END) as bad
            FROM feedback_queue WHERE status='checked' AND checked_at > datetime('now', ?)
            GROUP BY task_type
        """, (f"-{days} days",)).fetchall()
        return [dict(r) for r in rows]

    # ========== v5.0 Phase 4: Config Change Log 메서드 ==========

    def propose_config_change(self, config_key: str, old_value: str,
                               new_value: str, reason: str,
                               risk_level: str) -> int:
        """config 변경 제안. SAFE는 바로 applied, RISKY/DANGEROUS는 pending."""
        status = 'applied' if risk_level == 'SAFE' else 'pending'
        cur = self.conn.execute("""
            INSERT INTO config_change_log
            (config_key, old_value, new_value, reason, risk_level, status, applied_at)
            VALUES (?, ?, ?, ?, ?, ?, CASE WHEN ? = 'SAFE' THEN datetime('now') ELSE NULL END)
        """, (config_key, old_value, new_value, reason, risk_level, status, risk_level))
        self.conn.commit()
        return cur.lastrowid

    def approve_config_change(self, change_id: int, approved_by: str = 'boss') -> bool:
        """보스가 RISKY/DANGEROUS 변경을 승인."""
        self.conn.execute("""
            UPDATE config_change_log
            SET status = 'approved', approved_by = ?, applied_at = datetime('now')
            WHERE id = ? AND status = 'pending'
        """, (approved_by, change_id))
        self.conn.commit()
        return self.conn.total_changes > 0

    def reject_config_change(self, change_id: int) -> bool:
        """보스가 변경을 거부."""
        self.conn.execute("""
            UPDATE config_change_log SET status = 'rejected' WHERE id = ? AND status = 'pending'
        """, (change_id,))
        self.conn.commit()
        return self.conn.total_changes > 0

    def rollback_config_change(self, change_id: int) -> dict | None:
        """적용된 변경을 롤백. old_value 반환."""
        row = self.conn.execute("""
            SELECT config_key, old_value FROM config_change_log
            WHERE id = ? AND status IN ('applied', 'approved')
        """, (change_id,)).fetchone()
        if not row:
            return None
        self.conn.execute("""
            UPDATE config_change_log SET status = 'rolled_back' WHERE id = ?
        """, (change_id,))
        self.conn.commit()
        return {"config_key": row[0], "old_value": row[1]}

    def get_pending_config_changes(self) -> list:
        """보스 승인 대기 중인 변경 목록."""
        rows = self.conn.execute("""
            SELECT id, config_key, old_value, new_value, reason, risk_level, created_at
            FROM config_change_log WHERE status = 'pending'
            ORDER BY created_at
        """).fetchall()
        return [{"id": r[0], "key": r[1], "old": r[2], "new": r[3],
                 "reason": r[4], "risk": r[5], "created": r[6]} for r in rows]

    def get_config_change_history(self, limit: int = 20) -> list:
        """최근 config 변경 이력."""
        rows = self.conn.execute("""
            SELECT id, config_key, old_value, new_value, reason, risk_level,
                   status, before_metric, after_metric, created_at, applied_at
            FROM config_change_log ORDER BY created_at DESC LIMIT ?
        """, (limit,)).fetchall()
        return [{"id": r[0], "key": r[1], "old": r[2], "new": r[3], "reason": r[4],
                 "risk": r[5], "status": r[6], "before": r[7], "after": r[8],
                 "created": r[9], "applied": r[10]} for r in rows]

    def update_config_metrics(self, change_id: int, before_metric: str, after_metric: str):
        """적용 전후 메트릭 기록 (효과 측정용)."""
        self.conn.execute("""
            UPDATE config_change_log SET before_metric = ?, after_metric = ?
            WHERE id = ?
        """, (before_metric, after_metric, change_id))
        self.conn.commit()

    # ========== v5.0 Phase 4: Plan Memory (MUSE 3계층) 메서드 ==========

    def store_memory(self, memory_type: str, content: str,
                     source_task: str = None, source_plan_hash: str = None,
                     relevance_tags: str = None) -> int:
        """경험 메모리 저장."""
        cur = self.conn.execute("""
            INSERT INTO plan_memory (memory_type, content, source_task, source_plan_hash, relevance_tags)
            VALUES (?, ?, ?, ?, ?)
        """, (memory_type, content, source_task, source_plan_hash, relevance_tags))
        self.conn.commit()
        return cur.lastrowid

    def search_memory(self, memory_type: str, keyword: str, limit: int = 5) -> list:
        """키워드로 관련 메모리 검색."""
        rows = self.conn.execute("""
            SELECT id, content, source_task, relevance_tags, use_count, created_at
            FROM plan_memory
            WHERE memory_type = ? AND (content LIKE ? OR relevance_tags LIKE ?)
            ORDER BY use_count DESC, created_at DESC
            LIMIT ?
        """, (memory_type, f"%{keyword}%", f"%{keyword}%", limit)).fetchall()
        return [{"id": r[0], "content": r[1], "source_task": r[2],
                 "tags": r[3], "use_count": r[4], "created": r[5]} for r in rows]

    def touch_memory(self, memory_id: int):
        """메모리 사용 시 use_count 증가 + last_used_at 갱신."""
        self.conn.execute("""
            UPDATE plan_memory SET use_count = use_count + 1, last_used_at = datetime('now')
            WHERE id = ?
        """, (memory_id,))
        self.conn.commit()

    def get_memory_stats(self) -> dict:
        """메모리 통계."""
        rows = self.conn.execute("""
            SELECT memory_type, COUNT(*), SUM(use_count)
            FROM plan_memory GROUP BY memory_type
        """).fetchall()
        return {r[0]: {"count": r[1], "total_uses": r[2] or 0} for r in rows}

    # === 리소스 관리 ===
    def close(self) -> None:
        if self.conn:
            self.conn.close()
            self.conn = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
