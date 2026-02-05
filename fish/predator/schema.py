"""
Phase 5 Wave 1: PREDATOR EVOLUTION Schema
REZE v6.0 SOVEREIGN - 포식자 진화 아키텍처

5단계 파이프라인: 흡수 → 소화 → 학습 → 적용 → 검증

실행: python -m fish.predator.schema
"""

import sqlite3
import logging
from pathlib import Path
from typing import Tuple

logger = logging.getLogger("reze.predator.schema")

# ═══════════════════════════════════════════════════════════════
# Phase 5 테이블 정의 (9개 테이블)
# ═══════════════════════════════════════════════════════════════

PREDATOR_TABLES = [
    # ─────────────────────────────────────────
    # 1. RSS 소스 관리
    # ─────────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS rss_sources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_id TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        url TEXT UNIQUE NOT NULL,
        category TEXT NOT NULL,
        language TEXT DEFAULT 'en',
        priority INTEGER DEFAULT 5,
        last_fetched_at TEXT,
        fetch_interval_minutes INTEGER DEFAULT 60,
        total_items_absorbed INTEGER DEFAULT 0,
        error_count INTEGER DEFAULT 0,
        active BOOLEAN DEFAULT 1,
        created_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_rss_sources_category ON rss_sources(category)",
    "CREATE INDEX IF NOT EXISTS idx_rss_sources_active ON rss_sources(active)",

    # ─────────────────────────────────────────
    # 2. 흡수된 원본 데이터 (Stage 1: Absorb)
    # ─────────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS absorbed_raw (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        absorb_id TEXT UNIQUE NOT NULL,
        source_id TEXT NOT NULL,
        guid TEXT NOT NULL,
        title TEXT NOT NULL,
        link TEXT NOT NULL,
        published_at TEXT,
        summary TEXT,
        content TEXT,
        author TEXT,
        tags TEXT,
        digest_status TEXT DEFAULT 'pending',
        created_at TEXT NOT NULL,
        UNIQUE(source_id, guid)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_absorbed_source ON absorbed_raw(source_id)",
    "CREATE INDEX IF NOT EXISTS idx_absorbed_status ON absorbed_raw(digest_status)",
    "CREATE INDEX IF NOT EXISTS idx_absorbed_published ON absorbed_raw(published_at)",

    # ─────────────────────────────────────────
    # 3. 소화된 인사이트 (Stage 2: Digest)
    # ─────────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS digested_insights (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        insight_id TEXT UNIQUE NOT NULL,
        absorb_id TEXT NOT NULL,
        source_id TEXT NOT NULL,
        insight_type TEXT NOT NULL,
        summary TEXT NOT NULL,
        key_points TEXT,
        relevance_score REAL DEFAULT 0.5,
        actionability_score REAL DEFAULT 0.5,
        novelty_score REAL DEFAULT 0.5,
        combined_score REAL DEFAULT 0.5,
        domains TEXT,
        entities TEXT,
        learn_status TEXT DEFAULT 'pending',
        created_at TEXT NOT NULL,
        FOREIGN KEY (absorb_id) REFERENCES absorbed_raw(absorb_id)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_insight_type ON digested_insights(insight_type)",
    "CREATE INDEX IF NOT EXISTS idx_insight_score ON digested_insights(combined_score)",
    "CREATE INDEX IF NOT EXISTS idx_insight_learn ON digested_insights(learn_status)",

    # ─────────────────────────────────────────
    # 4. 학습된 패턴 (Stage 3: Learn)
    # ─────────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS learned_patterns (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pattern_id TEXT UNIQUE NOT NULL,
        insight_ids TEXT NOT NULL,
        pattern_type TEXT NOT NULL,
        description TEXT NOT NULL,
        pattern_data TEXT,
        confidence REAL DEFAULT 0.5,
        examples_count INTEGER DEFAULT 1,
        last_reinforced_at TEXT,
        apply_status TEXT DEFAULT 'pending',
        created_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_pattern_type ON learned_patterns(pattern_type)",
    "CREATE INDEX IF NOT EXISTS idx_pattern_confidence ON learned_patterns(confidence)",
    "CREATE INDEX IF NOT EXISTS idx_pattern_apply ON learned_patterns(apply_status)",

    # ─────────────────────────────────────────
    # 5. 적용된 액션 (Stage 4: Apply)
    # ─────────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS applied_actions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        action_id TEXT UNIQUE NOT NULL,
        pattern_id TEXT NOT NULL,
        action_type TEXT NOT NULL,
        target TEXT NOT NULL,
        description TEXT,
        payload TEXT,
        verify_status TEXT DEFAULT 'pending',
        applied_at TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (pattern_id) REFERENCES learned_patterns(pattern_id)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_action_type ON applied_actions(action_type)",
    "CREATE INDEX IF NOT EXISTS idx_action_verify ON applied_actions(verify_status)",
    "CREATE INDEX IF NOT EXISTS idx_action_pattern ON applied_actions(pattern_id)",

    # ─────────────────────────────────────────
    # 6. 검증 결과 (Stage 5: Verify)
    # ─────────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS verified_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        verify_id TEXT UNIQUE NOT NULL,
        action_id TEXT NOT NULL,
        pattern_id TEXT NOT NULL,
        success BOOLEAN DEFAULT 0,
        metrics TEXT,
        feedback TEXT,
        improvement_applied BOOLEAN DEFAULT 0,
        verified_at TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (action_id) REFERENCES applied_actions(action_id),
        FOREIGN KEY (pattern_id) REFERENCES learned_patterns(pattern_id)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_verify_success ON verified_results(success)",
    "CREATE INDEX IF NOT EXISTS idx_verify_action ON verified_results(action_id)",

    # ─────────────────────────────────────────
    # 7. PREDATOR 사이클 로그
    # ─────────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS predator_cycles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cycle_id TEXT UNIQUE NOT NULL,
        stage TEXT NOT NULL,
        items_processed INTEGER DEFAULT 0,
        items_success INTEGER DEFAULT 0,
        items_failed INTEGER DEFAULT 0,
        duration_sec REAL,
        energy_used REAL DEFAULT 0,
        error_message TEXT,
        created_at TEXT NOT NULL,
        completed_at TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_cycle_stage ON predator_cycles(stage)",
    "CREATE INDEX IF NOT EXISTS idx_cycle_created ON predator_cycles(created_at)",

    # ─────────────────────────────────────────
    # 8. 흡수 에러 로그
    # ─────────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS absorption_errors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        error_id TEXT UNIQUE NOT NULL,
        source_id TEXT NOT NULL,
        error_type TEXT NOT NULL,
        error_message TEXT NOT NULL,
        retry_count INTEGER DEFAULT 0,
        resolved BOOLEAN DEFAULT 0,
        created_at TEXT NOT NULL,
        resolved_at TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_absorb_error_source ON absorption_errors(source_id)",
    "CREATE INDEX IF NOT EXISTS idx_absorb_error_resolved ON absorption_errors(resolved)",

    # ─────────────────────────────────────────
    # 9. PREDATOR 메트릭스
    # ─────────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS predator_metrics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        metric_date TEXT NOT NULL,
        stage TEXT NOT NULL,
        metric_name TEXT NOT NULL,
        metric_value REAL NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(metric_date, stage, metric_name)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_pred_metrics_date ON predator_metrics(metric_date)",
    "CREATE INDEX IF NOT EXISTS idx_pred_metrics_stage ON predator_metrics(stage)",
]


def run_predator_migrations(db_path: str = None, enable_wal: bool = True) -> Tuple[int, int]:
    """
    Phase 5 PREDATOR 테이블 마이그레이션 실행

    Args:
        db_path: DB 경로 (기본: ~/reze-agent/reze_data/ssot.sqlite)
        enable_wal: WAL 모드 활성화 (기본: True)

    Returns:
        (success_count, error_count)
    """
    if db_path is None:
        db_path = Path.home() / "reze-agent" / "reze_data" / "ssot.sqlite"

    conn = sqlite3.connect(str(db_path))

    # WAL 모드 활성화 (concurrent writes 지원)
    if enable_wal:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        logger.info("📝 WAL mode enabled")

    conn.row_factory = sqlite3.Row

    success_count = 0
    error_count = 0

    for i, sql in enumerate(PREDATOR_TABLES):
        try:
            conn.execute(sql)
            success_count += 1
        except Exception as e:
            error_count += 1
            if "already exists" not in str(e).lower():
                logger.warning(f"Migration {i+1} warning: {e}")

    conn.commit()

    # 테이블 확인
    cursor = conn.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name LIKE '%rss%' OR name LIKE '%absorbed%'
           OR name LIKE '%digest%' OR name LIKE '%learned%'
           OR name LIKE '%applied%' OR name LIKE '%verified%'
           OR name LIKE '%predator%' OR name LIKE '%absorption%'
        ORDER BY name
    """)
    tables = [row[0] for row in cursor.fetchall()]

    conn.close()

    logger.info(f"✅ PREDATOR migrations complete: {success_count} success, {error_count} warnings")
    logger.info(f"📊 Tables created: {tables}")

    return success_count, error_count


def verify_schema(db_path: str = None) -> dict:
    """스키마 검증"""
    if db_path is None:
        db_path = Path.home() / "reze-agent" / "reze_data" / "ssot.sqlite"

    conn = sqlite3.connect(str(db_path))

    expected_tables = [
        "rss_sources",
        "absorbed_raw",
        "digested_insights",
        "learned_patterns",
        "applied_actions",
        "verified_results",
        "predator_cycles",
        "absorption_errors",
        "predator_metrics"
    ]

    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    existing = {row[0] for row in cursor.fetchall()}

    # WAL 모드 확인
    wal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]

    conn.close()

    missing = [t for t in expected_tables if t not in existing]
    found = [t for t in expected_tables if t in existing]

    return {
        "expected": len(expected_tables),
        "found": len(found),
        "missing": missing,
        "tables": found,
        "wal_mode": wal_mode == "wal"
    }


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) > 1 and sys.argv[1] == "--verify":
        result = verify_schema()
        print(f"\n🔍 Schema Verification:")
        print(f"   Expected: {result['expected']} tables")
        print(f"   Found: {result['found']} tables")
        print(f"   WAL Mode: {'✅' if result['wal_mode'] else '❌'}")
        if result['missing']:
            print(f"   Missing: {result['missing']}")
        else:
            print("   ✅ All tables present!")
    else:
        db_path = sys.argv[1] if len(sys.argv) > 1 else None
        run_predator_migrations(db_path)
