"""
Phase 3-4 DB 마이그레이션
REZE v6.0 SOVEREIGN - Self-Evolution Architecture

실행: python -m fish.evolve.migrations
"""

import sqlite3
import logging
from pathlib import Path

logger = logging.getLogger("reze.evolve.migrations")

MIGRATIONS = [
    # ═══════════════════════════════════════════
    # Wave 0: 인프라 테이블
    # ═══════════════════════════════════════════

    # 샌드박스 실행 기록
    """CREATE TABLE IF NOT EXISTS sandbox_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        patch_id TEXT NOT NULL,
        target_file TEXT NOT NULL,
        exit_code INTEGER,
        test_passed BOOLEAN DEFAULT 0,
        stdout TEXT,
        stderr TEXT,
        duration_sec REAL,
        created_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_sandbox_runs_patch ON sandbox_runs(patch_id)",

    # 체크포인트
    """CREATE TABLE IF NOT EXISTS checkpoints (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        checkpoint_id TEXT UNIQUE NOT NULL,
        module TEXT NOT NULL,
        action TEXT NOT NULL,
        files_backed TEXT,
        created_at TEXT NOT NULL,
        rolled_back BOOLEAN DEFAULT 0,
        rolled_back_at TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_checkpoints_module ON checkpoints(module)",

    # 승인 요청
    """CREATE TABLE IF NOT EXISTS approval_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id TEXT UNIQUE NOT NULL,
        module TEXT NOT NULL,
        action TEXT NOT NULL,
        risk_level TEXT NOT NULL,
        description TEXT,
        payload TEXT,
        status TEXT DEFAULT 'pending',
        created_at TEXT NOT NULL,
        resolved_at TEXT,
        boss_note TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_approval_status ON approval_requests(status)",
    "CREATE INDEX IF NOT EXISTS idx_approval_risk ON approval_requests(risk_level)",

    # 보스 알림
    """CREATE TABLE IF NOT EXISTS boss_notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id TEXT NOT NULL,
        module TEXT NOT NULL,
        action TEXT NOT NULL,
        risk_level TEXT NOT NULL,
        description TEXT,
        urgent BOOLEAN DEFAULT 0,
        created_at TEXT NOT NULL,
        read BOOLEAN DEFAULT 0,
        read_at TEXT
    )""",

    # 멱등성 로그
    """CREATE TABLE IF NOT EXISTS idempotency_log (
        operation_key TEXT PRIMARY KEY,
        result TEXT,
        created_at TEXT NOT NULL
    )""",

    # 진화 쿨다운
    """CREATE TABLE IF NOT EXISTS evolution_cooldowns (
        module TEXT PRIMARY KEY,
        last_run TEXT NOT NULL
    )""",

    # 진화 세션 로그
    """CREATE TABLE IF NOT EXISTS evolution_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        energy_available REAL,
        energy_used REAL,
        modules_executed TEXT,
        modules_skipped TEXT,
        results_summary TEXT,
        created_at TEXT NOT NULL
    )""",

    # ═══════════════════════════════════════════
    # Phase 3: 진화 모듈 테이블
    # ═══════════════════════════════════════════

    # 진화 로그 (Self-Code Evolution)
    """CREATE TABLE IF NOT EXISTS evolution_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        module TEXT NOT NULL,
        action TEXT NOT NULL,
        target_file TEXT,
        opportunity_type TEXT,
        explanation TEXT,
        lines_changed INTEGER DEFAULT 0,
        approval_status TEXT,
        checkpoint_id TEXT,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_evo_log_module ON evolution_log(module)",

    # 대기 중 패치 (승인 대기)
    """CREATE TABLE IF NOT EXISTS pending_patches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id TEXT UNIQUE NOT NULL,
        target_file TEXT NOT NULL,
        patched_code TEXT NOT NULL,
        explanation TEXT,
        created_at TEXT NOT NULL
    )""",

    # 발견된 도구 (Tool Discovery)
    """CREATE TABLE IF NOT EXISTS discovered_tools (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        url TEXT UNIQUE NOT NULL,
        title TEXT,
        domain TEXT NOT NULL,
        api_endpoint TEXT,
        auth_type TEXT DEFAULT 'none',
        rate_limit TEXT,
        usefulness_score REAL DEFAULT 0,
        status TEXT DEFAULT 'discovered',
        discovered_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_tools_domain ON discovered_tools(domain)",
    "CREATE INDEX IF NOT EXISTS idx_tools_status ON discovered_tools(status)",

    # 스킬 (도구 등록)
    """CREATE TABLE IF NOT EXISTS skills (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        skill_id TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        domain TEXT NOT NULL,
        endpoint TEXT,
        auth_type TEXT DEFAULT 'none',
        description TEXT,
        discovered_by TEXT,
        status TEXT DEFAULT 'active',
        created_at TEXT NOT NULL
    )""",

    # Self-Play 분석
    """CREATE TABLE IF NOT EXISTS self_play_analyses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pair_id TEXT NOT NULL,
        success_factors TEXT,
        failure_causes TEXT,
        prompt_improvement TEXT,
        confidence REAL DEFAULT 0,
        created_at TEXT NOT NULL
    )""",

    # 실험 큐 (Self-Play → Experiment 연동)
    """CREATE TABLE IF NOT EXISTS experiment_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        experiment_type TEXT NOT NULL,
        variant_a TEXT NOT NULL,
        variant_b TEXT NOT NULL,
        hypothesis TEXT,
        source_module TEXT,
        status TEXT DEFAULT 'queued',
        created_at TEXT NOT NULL,
        started_at TEXT,
        completed_at TEXT,
        result TEXT
    )""",

    # 예측 (World Model)
    """CREATE TABLE IF NOT EXISTS predictions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        prediction_id TEXT UNIQUE NOT NULL,
        action_type TEXT NOT NULL,
        niche TEXT,
        strategy TEXT,
        keyword TEXT,
        title TEXT,
        predicted_outcome TEXT NOT NULL,
        confidence REAL,
        model_version TEXT,
        created_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_predictions_action ON predictions(action_type)",

    # 예측 평가
    """CREATE TABLE IF NOT EXISTS prediction_evaluations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        prediction_id TEXT NOT NULL,
        actual_outcome TEXT NOT NULL,
        prediction_error REAL,
        evaluated_at TEXT NOT NULL
    )""",

    # 모델 보정
    """CREATE TABLE IF NOT EXISTS model_calibration (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        model_version TEXT NOT NULL,
        prediction_error REAL,
        recorded_at TEXT NOT NULL
    )""",

    # 태스크 플랜 (Sub-Agent)
    """CREATE TABLE IF NOT EXISTS task_plans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        plan_id TEXT UNIQUE NOT NULL,
        parent_task TEXT,
        mode TEXT NOT NULL,
        subtask_count INTEGER DEFAULT 0,
        completed_count INTEGER DEFAULT 0,
        failed_count INTEGER DEFAULT 0,
        created_at TEXT NOT NULL,
        finished_at TEXT
    )""",

    # 판단 기록 (Metacognition)
    """CREATE TABLE IF NOT EXISTS decision_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        decision_id TEXT UNIQUE NOT NULL,
        domain TEXT NOT NULL,
        decision TEXT NOT NULL,
        confidence REAL NOT NULL,
        reasoning TEXT,
        metadata TEXT,
        outcome TEXT,
        actual_score REAL,
        created_at TEXT NOT NULL,
        evaluated_at TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_decision_domain ON decision_log(domain)",
    "CREATE INDEX IF NOT EXISTS idx_decision_outcome ON decision_log(outcome)",

    # 호기심 제안 (Curiosity)
    """CREATE TABLE IF NOT EXISTS curiosity_suggestions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        niche TEXT NOT NULL,
        strategy TEXT NOT NULL,
        curiosity_type TEXT NOT NULL,
        score REAL NOT NULL,
        reason TEXT,
        plan TEXT,
        status TEXT DEFAULT 'suggested',
        created_at TEXT NOT NULL,
        tried_at TEXT,
        result TEXT
    )""",

    # ═══════════════════════════════════════════
    # Phase 4: 추가 모듈 테이블
    # ═══════════════════════════════════════════

    # 진화 실행 (Evolutionary Coding)
    """CREATE TABLE IF NOT EXISTS evolution_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT UNIQUE NOT NULL,
        target TEXT NOT NULL,
        generation INTEGER DEFAULT 0,
        population_size INTEGER DEFAULT 5,
        best_variant_id TEXT,
        best_fitness REAL,
        status TEXT DEFAULT 'running',
        created_at TEXT NOT NULL
    )""",

    # 진화 변이
    """CREATE TABLE IF NOT EXISTS evolution_variants (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        variant_id TEXT UNIQUE NOT NULL,
        run_id TEXT NOT NULL,
        generation INTEGER NOT NULL,
        content TEXT NOT NULL,
        parent_ids TEXT,
        fitness REAL,
        status TEXT DEFAULT 'created',
        created_at TEXT NOT NULL,
        evaluated_at TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_variants_run ON evolution_variants(run_id, generation)",

    # 프롬프트 사용 로그 (Evo Coding 가동 조건용)
    """CREATE TABLE IF NOT EXISTS prompt_usage_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        prompt_name TEXT NOT NULL,
        prompt_version TEXT,
        used_for TEXT,
        quality_result REAL,
        created_at TEXT NOT NULL
    )""",

    # 에러 로그 (Self-Healing)
    """CREATE TABLE IF NOT EXISTS error_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        error_id TEXT UNIQUE NOT NULL,
        module TEXT NOT NULL,
        error_type TEXT NOT NULL,
        error_message TEXT NOT NULL,
        stack_trace TEXT,
        severity TEXT DEFAULT 'ERROR',
        context TEXT,
        healing_status TEXT DEFAULT 'detected',
        root_cause TEXT,
        fix_attempted TEXT,
        created_at TEXT NOT NULL,
        healed_at TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_error_module ON error_log(module)",
    "CREATE INDEX IF NOT EXISTS idx_error_severity ON error_log(severity)",
    "CREATE INDEX IF NOT EXISTS idx_error_healing ON error_log(healing_status)",

    # 치유 이력
    """CREATE TABLE IF NOT EXISTS healing_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        error_type TEXT NOT NULL,
        module TEXT NOT NULL,
        root_cause TEXT,
        fix_applied TEXT,
        success BOOLEAN DEFAULT 0,
        created_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_healing_type ON healing_history(error_type, module)",

    # 치유 큐
    """CREATE TABLE IF NOT EXISTS healing_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        error_id TEXT UNIQUE NOT NULL,
        priority INTEGER DEFAULT 1,
        created_at TEXT NOT NULL
    )""",

    # 경험 기억 (Lifelong Learning)
    """CREATE TABLE IF NOT EXISTS experience_memory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        experience_id TEXT UNIQUE NOT NULL,
        exp_type TEXT NOT NULL,
        summary TEXT NOT NULL,
        details TEXT,
        lesson TEXT,
        tags TEXT,
        search_text TEXT,
        usefulness_score REAL DEFAULT 0.5,
        access_count INTEGER DEFAULT 0,
        archived BOOLEAN DEFAULT 0,
        created_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_exp_type ON experience_memory(exp_type)",
    "CREATE INDEX IF NOT EXISTS idx_exp_archived ON experience_memory(archived)",
    "CREATE INDEX IF NOT EXISTS idx_exp_usefulness ON experience_memory(usefulness_score)",

    # ═══════════════════════════════════════════
    # hunt_log 테이블 (기존 hunt_memory와 별도, 분석용)
    # ═══════════════════════════════════════════
    """CREATE TABLE IF NOT EXISTS hunt_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        hunt_id TEXT UNIQUE,
        niche TEXT,
        strategy TEXT,
        keyword TEXT,
        title TEXT,
        prompt_used TEXT,
        status TEXT DEFAULT 'pending',
        quality_score REAL,
        traffic_result INTEGER,
        created_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_hunt_log_niche ON hunt_log(niche)",
    "CREATE INDEX IF NOT EXISTS idx_hunt_log_strategy ON hunt_log(strategy)",
    "CREATE INDEX IF NOT EXISTS idx_hunt_log_status ON hunt_log(status)",

    # blog_config (niches 설정)
    """CREATE TABLE IF NOT EXISTS blog_config (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        niche TEXT UNIQUE NOT NULL,
        blog TEXT NOT NULL,
        active BOOLEAN DEFAULT 1,
        config TEXT,
        created_at TEXT NOT NULL
    )""",
]


def run_migrations(db_path: str = None):
    """모든 마이그레이션 실행"""
    if db_path is None:
        db_path = Path.home() / "reze-agent" / "reze_data" / "ssot.sqlite"

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    success_count = 0
    error_count = 0

    for i, sql in enumerate(MIGRATIONS):
        try:
            conn.execute(sql)
            success_count += 1
        except Exception as e:
            error_count += 1
            # Ignore "already exists" errors
            if "already exists" not in str(e).lower():
                logger.warning(f"Migration {i+1} warning: {e}")

    conn.commit()
    conn.close()

    print(f"✅ Migrations complete: {success_count} success, {error_count} warnings")
    return success_count, error_count


if __name__ == "__main__":
    import sys
    db_path = sys.argv[1] if len(sys.argv) > 1 else None
    run_migrations(db_path)
