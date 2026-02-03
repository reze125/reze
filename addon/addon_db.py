"""
ADDON 전용 DB. 기존 SSOT 수정 0줄. 읽기 전용 접근만.
"""

import sqlite3
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ADDON_DB_PATH = os.environ.get("REZE_ADDON_DB", "/home/reze/reze-agent/addon/data/addon.db")
SSOT_DB_PATH = os.environ.get("REZE_SSOT_DB", "/home/reze/reze-agent/reze.db")


class AddonDB:
    def __init__(self, db_path: str = None):
        self.db_path = db_path or ADDON_DB_PATH
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")

    def init_tables(self):
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS core_memory (
            block_name TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            token_count INTEGER DEFAULT 0,
            max_tokens INTEGER DEFAULT 500,
            updated_at TEXT DEFAULT (datetime('now')),
            version INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS archival_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            content TEXT NOT NULL,
            embedding_id TEXT,
            importance_score REAL DEFAULT 0.5,
            access_count INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            last_accessed TEXT,
            compressed INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS memory_ops_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            operation TEXT NOT NULL,
            block_name TEXT,
            detail TEXT,
            timestamp TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS dspy_programs (
            module_name TEXT PRIMARY KEY,
            signature TEXT NOT NULL,
            current_program_path TEXT,
            baseline_score REAL,
            optimized_score REAL,
            optimization_count INTEGER DEFAULT 0,
            last_optimized TEXT,
            status TEXT DEFAULT 'pending'
        );
        CREATE TABLE IF NOT EXISTS dspy_training_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            module_name TEXT NOT NULL,
            input_data TEXT NOT NULL,
            output_data TEXT,
            score REAL,
            source TEXT DEFAULT 'auto',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS modification_archive (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_file TEXT NOT NULL,
            original_hash TEXT NOT NULL,
            modified_hash TEXT,
            diff_text TEXT,
            reason TEXT,
            utility_score REAL,
            quality_before REAL,
            quality_after REAL,
            status TEXT DEFAULT 'proposed',
            created_at TEXT DEFAULT (datetime('now')),
            applied_at TEXT,
            parent_id INTEGER,
            FOREIGN KEY (parent_id) REFERENCES modification_archive(id)
        );
        CREATE TABLE IF NOT EXISTS modification_sandbox (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            archive_id INTEGER NOT NULL,
            test_command TEXT,
            test_output TEXT,
            test_passed INTEGER,
            execution_time_ms INTEGER,
            timestamp TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (archive_id) REFERENCES modification_archive(id)
        );
        CREATE TABLE IF NOT EXISTS discovered_services (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            service_type TEXT NOT NULL,
            service_name TEXT NOT NULL,
            service_meta TEXT,
            discovered_at TEXT DEFAULT (datetime('now')),
            status TEXT DEFAULT 'new',
            UNIQUE(service_type, service_name)
        );
        CREATE TABLE IF NOT EXISTS tool_registry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tool_name TEXT UNIQUE NOT NULL,
            tool_type TEXT DEFAULT 'mcp',
            description TEXT,
            code_path TEXT,
            source_service TEXT,
            verification_count INTEGER DEFAULT 0,
            verified INTEGER DEFAULT 0,
            usage_count INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            last_used TEXT
        );
        CREATE TABLE IF NOT EXISTS curiosity_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            question TEXT NOT NULL,
            target_service TEXT,
            status TEXT DEFAULT 'pending',
            answer TEXT,
            insight_value REAL,
            follow_up_action TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            answered_at TEXT
        );
        CREATE TABLE IF NOT EXISTS exploration_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id INTEGER,
            search_queries TEXT,
            sources TEXT,
            findings TEXT,
            timestamp TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (question_id) REFERENCES curiosity_questions(id)
        );
        CREATE TABLE IF NOT EXISTS addon_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            module TEXT NOT NULL,
            status TEXT DEFAULT 'running',
            detail TEXT,
            duration_ms INTEGER,
            timestamp TEXT DEFAULT (datetime('now'))
        );
        """)
        self.conn.commit()
        tables = self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        print(f"Addon DB 초기화 완료: {self.db_path}")
        print(f"   테이블 {len(tables)}개: {[t['name'] for t in tables]}")

    def read_ssot(self, query: str, params: tuple = ()):
        try:
            ssot_conn = sqlite3.connect(f"file:{SSOT_DB_PATH}?mode=ro", uri=True)
            ssot_conn.row_factory = sqlite3.Row
            result = ssot_conn.execute(query, params).fetchall()
            ssot_conn.close()
            return result
        except Exception as e:
            print(f"SSOT 읽기 실패: {e}")
            return []

    def log_run(self, module: str, status: str, detail: str = "", duration_ms: int = 0):
        self.conn.execute(
            "INSERT INTO addon_runs (module, status, detail, duration_ms) VALUES (?, ?, ?, ?)",
            (module, status, detail, duration_ms))
        self.conn.commit()

    def close(self):
        self.conn.close()


class SSOTReader:
    def __init__(self):
        self.available = os.path.exists(SSOT_DB_PATH)

    def get_plan_cache(self, limit=20):
        db = AddonDB()
        return db.read_ssot("SELECT * FROM plan_cache ORDER BY created_at DESC LIMIT ?", (limit,))

    def get_reflections(self, limit=20):
        db = AddonDB()
        return db.read_ssot("SELECT * FROM reflections ORDER BY created_at DESC LIMIT ?", (limit,))

    def get_boss_feedback(self, limit=20):
        db = AddonDB()
        return db.read_ssot("SELECT * FROM boss_feedback ORDER BY created_at DESC LIMIT ?", (limit,))

    def get_dynamic_skills(self):
        db = AddonDB()
        return db.read_ssot("SELECT * FROM dynamic_skills WHERE status='active'")

    def get_service_config(self):
        config_path = os.path.join(os.environ.get("REZE_HOME", "/home/reze/reze-agent"), "configs/services.yaml")
        try:
            import yaml
            with open(config_path) as f:
                return yaml.safe_load(f)
        except Exception as e:
            print(f"서비스 설정 읽기 실패: {e}")
            return {}


if __name__ == "__main__":
    if "--init" in sys.argv:
        db = AddonDB()
        db.init_tables()
        db.close()
    else:
        print("사용법: python3 addon_db.py --init")
