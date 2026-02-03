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
        """)
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
                      procedure: str, steps: int, tokens: int, score: float):
        """성공한 태스크의 절차를 캐싱 (v4.0)."""
        import json
        self.conn.execute("""
            INSERT INTO plan_cache_v4 (task_pattern, skills_used, procedure,
                                      steps, tokens, score, created_at, used_count)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'), 0)
        """, [task_pattern, json.dumps(skills_used), procedure, steps, tokens, score])
        self.conn.commit()

    def find_cached_plan_v4(self, task: str, threshold: float = 0.6) -> Optional[dict]:
        """유사 태스크의 캐싱된 절차 검색 (v4.0)."""
        plans = self.conn.execute("""
            SELECT task_pattern, procedure, score, used_count
            FROM plan_cache_v4
            WHERE created_at > datetime('now', '-30 days')
            AND score >= ?
            ORDER BY score DESC, used_count DESC
            LIMIT 5
        """, [threshold]).fetchall()
        if not plans:
            return None
        return {
            'task_pattern': plans[0][0],
            'procedure': plans[0][1],
            'score': plans[0][2],
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

    # === 리소스 관리 ===
    def close(self) -> None:
        if self.conn:
            self.conn.close()
            self.conn = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
