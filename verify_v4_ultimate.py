#!/usr/bin/env python3
"""
REZE v4.0 ULTIMATE Verification Script
- 모든 v4.0 ULTIMATE 컴포넌트 체크
- SSOT 테이블 확인
- 모듈 임포트 테스트
"""

import sys
import sqlite3
from pathlib import Path

# Colors for terminal output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"

def check_mark(ok: bool) -> str:
    return f"{GREEN}✓{RESET}" if ok else f"{RED}✗{RESET}"

def main():
    print("=" * 60)
    print("REZE v4.0 ULTIMATE Verification")
    print("=" * 60)

    errors = []
    warnings = []

    # 1. Required files check
    print("\n[1] Checking required files...")
    required_files = [
        "capability_engine.py",
        "autonomous_ops.py",
        "goal_execution_bridge.py",
        "agent_supervisor.py",
        "saas_operations.py",
        "gumroad_operations.py",
        "growth_engine.py",
        "meta_cognition.py",
        "prompt_evolver.py",
        "configs/services.yaml",
    ]

    base_dir = Path(__file__).parent
    for f in required_files:
        path = base_dir / f
        exists = path.exists()
        print(f"  {check_mark(exists)} {f}")
        if not exists:
            errors.append(f"Missing file: {f}")

    # 2. Module import check
    print("\n[2] Checking module imports...")
    modules_to_check = [
        ("capability_engine", "CapabilityEngine"),
        ("autonomous_ops", "AutonomousLoop"),
        ("goal_execution_bridge", "GoalExecutionBridge"),
        ("agent_supervisor", "AgentSupervisor"),
        ("saas_operations", "SaaSOperations"),
        ("gumroad_operations", "GumroadOperations"),
        ("growth_engine", "CrossPortfolioGrowth"),
        ("meta_cognition", "MetaCognitionReview"),
        ("prompt_evolver", "PromptEvolver"),
    ]

    for module_name, class_name in modules_to_check:
        try:
            module = __import__(module_name)
            cls = getattr(module, class_name, None)
            ok = cls is not None
            print(f"  {check_mark(ok)} {module_name}.{class_name}")
            if not ok:
                errors.append(f"Class not found: {module_name}.{class_name}")
        except Exception as e:
            print(f"  {check_mark(False)} {module_name} - {str(e)[:50]}")
            errors.append(f"Import error: {module_name} - {e}")

    # 3. SSOT tables check
    print("\n[3] Checking SSOT tables...")
    db_path = base_dir / "reze.db"

    required_tables = [
        "task_queue",
        "boss_feedback",
        "supervised_agents",
        "dynamic_skills",
        "agent_restarts",
        "meta_reviews",
        "revenue_snapshots",
        "ab_tests",
    ]

    if db_path.exists():
        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()

            for table in required_tables:
                cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'")
                exists = cursor.fetchone() is not None
                print(f"  {check_mark(exists)} {table}")
                if not exists:
                    warnings.append(f"Table not found (will be created on first run): {table}")

            conn.close()
        except Exception as e:
            print(f"  {check_mark(False)} Database check failed: {e}")
            warnings.append(f"Database check failed: {e}")
    else:
        print(f"  {YELLOW}⚠{RESET} Database not found (will be created on first run)")
        warnings.append("Database not found - will be created on first run")

    # 4. Config check
    print("\n[4] Checking services.yaml...")
    config_path = base_dir / "configs" / "services.yaml"
    if config_path.exists():
        try:
            import yaml
            with open(config_path) as f:
                config = yaml.safe_load(f)

            sections = ["blogs", "saas", "gumroad", "infrastructure", "goals"]
            for section in sections:
                exists = section in config
                print(f"  {check_mark(exists)} {section} section")
                if not exists:
                    warnings.append(f"Missing section in services.yaml: {section}")
        except Exception as e:
            print(f"  {check_mark(False)} Config parsing failed: {e}")
            errors.append(f"Config parsing failed: {e}")
    else:
        print(f"  {check_mark(False)} services.yaml not found")
        errors.append("services.yaml not found")

    # 5. Daemon integration check
    print("\n[5] Checking daemon integration...")
    daemon_path = base_dir / "reze_daemon.py"
    if daemon_path.exists():
        content = daemon_path.read_text()

        checks = [
            ("v4.0 ULTIMATE imports", "from capability_engine import"),
            ("AutonomousLoop init", "state.autonomous_loop"),
            ("CapabilityEngine init", "state.capability_engine"),
            ("AgentSupervisor init", "state.agent_supervisor"),
            ("autonomous_loop_job", "autonomous_loop_job"),
            ("meta_review_job", "meta_review_job"),
            ("prompt_evolution_job", "prompt_evolution_job"),
        ]

        for name, pattern in checks:
            exists = pattern in content
            print(f"  {check_mark(exists)} {name}")
            if not exists:
                errors.append(f"Daemon missing: {name}")
    else:
        print(f"  {check_mark(False)} reze_daemon.py not found")
        errors.append("reze_daemon.py not found")

    # 6. REZECore capability integration check
    print("\n[6] Checking REZECore integration...")
    core_path = base_dir / "reze_core.py"
    if core_path.exists():
        content = core_path.read_text()

        checks = [
            ("capability_engine param", "capability_engine=None"),
            ("CAPABILITIES constant", "CAPABILITIES = ["),
            ("identify_required_capabilities", "async def identify_required_capabilities"),
            ("run_with_capabilities", "async def run_with_capabilities"),
        ]

        for name, pattern in checks:
            exists = pattern in content
            print(f"  {check_mark(exists)} {name}")
            if not exists:
                warnings.append(f"REZECore missing (optional): {name}")
    else:
        print(f"  {check_mark(False)} reze_core.py not found")
        errors.append("reze_core.py not found")

    # Summary
    print("\n" + "=" * 60)
    print("VERIFICATION SUMMARY")
    print("=" * 60)

    if errors:
        print(f"\n{RED}ERRORS ({len(errors)}):{RESET}")
        for e in errors:
            print(f"  - {e}")

    if warnings:
        print(f"\n{YELLOW}WARNINGS ({len(warnings)}):{RESET}")
        for w in warnings:
            print(f"  - {w}")

    if not errors and not warnings:
        print(f"\n{GREEN}All checks passed!{RESET}")
        print("\nREZE v4.0 ULTIMATE is ready to run.")
    elif not errors:
        print(f"\n{YELLOW}All critical checks passed with {len(warnings)} warnings.{RESET}")
        print("\nREZE v4.0 ULTIMATE should work, but review warnings.")
    else:
        print(f"\n{RED}VERIFICATION FAILED with {len(errors)} errors.{RESET}")
        print("\nPlease fix the errors before running REZE v4.0 ULTIMATE.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
