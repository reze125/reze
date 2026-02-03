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
        """)
        self.conn.commit()

    # === 유틸리티 ===
    def _new_id(self, prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex[:12]}"

    def _kst_now(self) -> str:
        return datetime.now(config.KST).isoformat()

    def _kst_date(self) -> str:
        return datetime.now(config.KST).strftime("%Y-%m-%d")

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

    # === 리소스 관리 ===
    def close(self) -> None:
        if self.conn:
            self.conn.close()
            self.conn = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
