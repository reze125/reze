"""
기존 APScheduler 크론잡 44개를 schedules 테이블로 이관.
이관 후 reze-daemon 중지, reze-fish 시작.
"""

import sqlite3
import json
from pathlib import Path

# 기존 daemon/orchestrator.py의 스케줄러 잡 목록
# 형식: {"name": "job_id", "cron_expr": "HH:MM [DOW]", "job_type": "...", "config": {...}}
# DOW: 0=월, 1=화, 2=수, 3=목, 4=금, 5=토, 6=일

CRON_JOBS = [
    # === 인터벌 잡 (fish에서는 매 heartbeat 체크로 대체) ===
    # health_check: interval=1h → fish가 매 5분마다 체크
    # discovery_scan: interval=30m → fish가 idle 30분 후 자발적 행동
    # daemon_task_processor: interval=5m → fish가 매 heartbeat 체크
    # task_queue_processor: interval=10m → fish가 매 heartbeat 체크
    # agent_supervisor_scan: interval=30m → fish가 idle 30분 후 자발적 행동

    # === AI Tools Lab 블로그 (10시) ===
    {"name": "blog_ai_news", "cron_expr": "10:00 0", "job_type": "blog",
     "config": json.dumps({"blog": "aitoolslab", "type": "news"})},
    {"name": "blog_ai_compare", "cron_expr": "10:00 2", "job_type": "blog",
     "config": json.dumps({"blog": "aitoolslab", "type": "compare"})},
    {"name": "blog_ai_discovery", "cron_expr": "10:00 1,5", "job_type": "blog",
     "config": json.dumps({"blog": "aitoolslab", "type": "discovery"})},
    {"name": "blog_ai_top", "cron_expr": "10:00 3", "job_type": "blog",
     "config": json.dumps({"blog": "aitoolslab", "type": "top"})},
    {"name": "blog_ai_review", "cron_expr": "10:00 4", "job_type": "blog",
     "config": json.dumps({"blog": "aitoolslab", "type": "review"})},

    # === 일일 리포트 ===
    {"name": "daily_report", "cron_expr": "21:00", "job_type": "report",
     "config": json.dumps({"type": "daily_summary"})},
    {"name": "goal_progress", "cron_expr": "21:00", "job_type": "report",
     "config": json.dumps({"type": "goal_progress"})},

    # === 모닝 루틴 ===
    {"name": "trend_scan", "cron_expr": "08:00", "job_type": "research",
     "config": json.dumps({"type": "trend_scan"})},
    {"name": "saas_ops_daily", "cron_expr": "08:00", "job_type": "saas",
     "config": json.dumps({"type": "saas_ops"})},
    {"name": "gumroad_ops_daily", "cron_expr": "08:15", "job_type": "saas",
     "config": json.dumps({"type": "gumroad_ops"})},
    {"name": "launch_check", "cron_expr": "08:30", "job_type": "saas",
     "config": json.dumps({"type": "launch_check"})},
    {"name": "portfolio_dashboard", "cron_expr": "09:00", "job_type": "report",
     "config": json.dumps({"type": "portfolio_dashboard"})},

    # === 주간 잡 (월요일) ===
    {"name": "self_review", "cron_expr": "09:00 0", "job_type": "self",
     "config": json.dumps({"type": "self_review"})},
    {"name": "competitor_check", "cron_expr": "09:00 0", "job_type": "research",
     "config": json.dumps({"type": "competitor_check"})},
    {"name": "weekly_goal_review", "cron_expr": "09:30 0", "job_type": "report",
     "config": json.dumps({"type": "weekly_goal_review"})},
    {"name": "landing_weekly_review", "cron_expr": "10:00 0", "job_type": "saas",
     "config": json.dumps({"type": "landing_review"})},
    {"name": "blog_market_research", "cron_expr": "08:00 0", "job_type": "research",
     "config": json.dumps({"type": "blog_market_research"})},
    {"name": "self_improvement_research", "cron_expr": "03:00 0", "job_type": "self",
     "config": json.dumps({"type": "self_improvement"})},

    # === 주간 잡 (수요일) ===
    {"name": "keyword_scan", "cron_expr": "09:00 2", "job_type": "research",
     "config": json.dumps({"type": "keyword_scan"})},
    {"name": "cross_sell_analysis", "cron_expr": "11:00 2", "job_type": "saas",
     "config": json.dumps({"type": "cross_sell"})},
    {"name": "competitor_research_wed", "cron_expr": "06:00 2", "job_type": "research",
     "config": json.dumps({"type": "competitor_research"})},

    # === 주간 잡 (금요일) ===
    {"name": "self_assessment", "cron_expr": "15:00 4", "job_type": "self",
     "config": json.dumps({"type": "self_assessment"})},

    # === 주간 잡 (토요일) ===
    {"name": "security_scan", "cron_expr": "03:00 5", "job_type": "health",
     "config": json.dumps({"type": "security_scan"})},
    {"name": "competitor_research_sat", "cron_expr": "06:00 5", "job_type": "research",
     "config": json.dumps({"type": "competitor_research"})},

    # === 주간 잡 (일요일) ===
    {"name": "strategic_thinking", "cron_expr": "20:00 6", "job_type": "self",
     "config": json.dumps({"type": "strategic_thinking"})},
    {"name": "weekly_report", "cron_expr": "21:00 6", "job_type": "report",
     "config": json.dumps({"type": "weekly_report"})},
    {"name": "meta_review", "cron_expr": "22:00 6", "job_type": "self",
     "config": json.dumps({"type": "meta_review"})},
    {"name": "prompt_evolution", "cron_expr": "23:00 6", "job_type": "self",
     "config": json.dumps({"type": "prompt_evolution"})},
    {"name": "weekly_skill_evolution", "cron_expr": "04:00 6", "job_type": "self",
     "config": json.dumps({"type": "skill_evolution"})},
    {"name": "blog_weekly_review", "cron_expr": "09:00 6", "job_type": "blog",
     "config": json.dumps({"type": "blog_weekly_review"})},

    # === 월간 잡 (매월 1일) ===
    {"name": "cost_review", "cron_expr": "09:00", "job_type": "report",
     "config": json.dumps({"type": "cost_review", "monthly": True, "day": 1})},
    {"name": "feature_monthly_report", "cron_expr": "10:00", "job_type": "report",
     "config": json.dumps({"type": "feature_monthly", "monthly": True, "day": 1})},
    {"name": "saas_monthly_report", "cron_expr": "10:30", "job_type": "report",
     "config": json.dumps({"type": "saas_monthly", "monthly": True, "day": 1})},

    # === 기타 일일 ===
    {"name": "saas_daily_check", "cron_expr": "07:30", "job_type": "saas",
     "config": json.dumps({"type": "saas_daily_check"})},
    {"name": "gumroad_daily_check", "cron_expr": "07:45", "job_type": "saas",
     "config": json.dumps({"type": "gumroad_daily_check"})},
    {"name": "churn_detection", "cron_expr": "10:00", "job_type": "saas",
     "config": json.dumps({"type": "churn_detection"})},
    {"name": "dynamic_skill_verification", "cron_expr": "14:00", "job_type": "self",
     "config": json.dumps({"type": "skill_verification"})},

    # === 블로그 자동화 ===
    {"name": "blog_daily_schedule", "cron_expr": "00:05", "job_type": "blog",
     "config": json.dumps({"type": "daily_schedule"})},
    {"name": "blog_competitor_crawl", "cron_expr": "06:00", "job_type": "blog",
     "config": json.dumps({"type": "competitor_crawl"})},
    {"name": "blog_auto_improve", "cron_expr": "22:00", "job_type": "blog",
     "config": json.dumps({"type": "auto_improve"})},
]


def migrate(db_path: str = None):
    """크론잡 이관"""
    if db_path is None:
        db_path = Path.home() / "reze-agent" / "reze_data" / "ssot.sqlite"

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # 스키마 생성
    schema_path = Path(__file__).parent / "schema.sql"
    if schema_path.exists():
        with open(schema_path) as f:
            c.executescript(f.read())
        print("✅ Schema created/verified")

    # 기존 데이터 확인
    existing = c.execute("SELECT name FROM schedules").fetchall()
    existing_names = {row[0] for row in existing}

    # 이관
    added = 0
    skipped = 0
    for job in CRON_JOBS:
        if job["name"] not in existing_names:
            c.execute(
                """INSERT INTO schedules (name, cron_expr, job_type, config)
                   VALUES (?, ?, ?, ?)""",
                (job["name"], job["cron_expr"], job["job_type"], job["config"])
            )
            added += 1
            print(f"  + {job['name']}: {job['cron_expr']}")
        else:
            skipped += 1

    conn.commit()
    conn.close()

    print(f"\n✅ Migration complete: {added} added, {skipped} already existed")
    print(f"   Total jobs in schedules table: {len(existing_names) + added}")


def list_jobs(db_path: str = None):
    """현재 등록된 잡 목록 출력"""
    if db_path is None:
        db_path = Path.home() / "reze-agent" / "reze_data" / "ssot.sqlite"

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        "SELECT name, cron_expr, job_type, enabled, last_run FROM schedules ORDER BY cron_expr"
    ).fetchall()

    print(f"\n📋 Registered schedules ({len(rows)} jobs):\n")
    print(f"{'Name':<30} {'Cron':<15} {'Type':<10} {'Enabled':<8} {'Last Run':<20}")
    print("-" * 90)

    for row in rows:
        enabled = "✅" if row["enabled"] else "❌"
        last_run = row["last_run"][:16] if row["last_run"] else "-"
        print(f"{row['name']:<30} {row['cron_expr']:<15} {row['job_type']:<10} {enabled:<8} {last_run:<20}")

    conn.close()


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "list":
        list_jobs()
    else:
        migrate()
