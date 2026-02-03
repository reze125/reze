"""
ADDON DAEMON — 독립 스케줄러. PM2에 reze-addon으로 등록.
"""

import os, sys, json, time, signal, logging, traceback
from datetime import datetime
import schedule

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from addon_db import AddonDB

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(os.path.join(LOG_DIR,"addon_daemon.log")), logging.StreamHandler()])
logger = logging.getLogger("reze-addon")


def run_module(mod_name, func_name):
    db = AddonDB(); start = time.time()
    logger.info(f"[START] {mod_name}.{func_name}")
    try:
        if mod_name == "memory_tier":
            from memory_tier import TwoTierMemory; m = TwoTierMemory(); r = m.consolidate(); m.close()
        elif mod_name == "dspy_optimizer":
            from dspy_optimizer import DSPyOptimizer; m = DSPyOptimizer(); r = m.optimize_all(); m.close()
        elif mod_name == "self_modifier":
            from self_modifier import SelfModifier; m = SelfModifier(); r = m.check_and_evolve(); m.close()
        elif mod_name == "tool_discovery":
            from tool_discovery import ToolDiscovery; m = ToolDiscovery(); r = m.scan_and_discover(); m.close()
        elif mod_name == "curiosity_engine":
            from curiosity_engine import CuriosityEngine; m = CuriosityEngine(); r = m.explore(); m.close()
        else:
            r = {"error": f"Unknown: {mod_name}"}
        ms = int((time.time()-start)*1000)
        logger.info(f"[DONE] {mod_name} ({ms}ms) -> {str(r)[:200]}")
    except Exception as e:
        logger.error(f"[FAIL] {mod_name}: {e}"); logger.error(traceback.format_exc())
        db.log_run(mod_name, "failed", str(e), int((time.time()-start)*1000))
    finally:
        db.close()


def setup_schedules():
    schedule.every().day.at("03:00").do(run_module, "memory_tier", "consolidate")
    schedule.every().sunday.at("04:00").do(run_module, "dspy_optimizer", "optimize_all")
    schedule.every().monday.at("02:00").do(run_module, "self_modifier", "check_and_evolve")
    schedule.every().thursday.at("02:00").do(run_module, "self_modifier", "check_and_evolve")
    schedule.every(12).hours.do(run_module, "tool_discovery", "scan_and_discover")
    schedule.every(6).hours.do(run_module, "curiosity_engine", "explore")
    logger.info("Schedules registered")


def print_status():
    db = AddonDB()
    print("\n" + "="*50 + "\n  REZE ADDON STATUS\n" + "="*50)
    for r in db.conn.execute("SELECT module,status,duration_ms,timestamp FROM addon_runs ORDER BY timestamp DESC LIMIT 10").fetchall():
        e = "[OK]" if r["status"]=="success" else "[FAIL]" if r["status"]=="failed" else "[SKIP]"
        print(f"  {e} {r['timestamp'][:16]} | {r['module']} | {r['status']} | {r['duration_ms']}ms")
    core = db.conn.execute("SELECT block_name,token_count FROM core_memory").fetchall()
    if core: print("\nCore Memory:"); [print(f"  {c['block_name']}: {c['token_count']}tok") for c in core]
    tools = db.conn.execute("SELECT COUNT(*) as t, SUM(verified) as v FROM tool_registry").fetchone()
    print(f"\nTools: {tools['t'] or 0} total ({tools['v'] or 0} verified)")
    db.close()


running = True
def sig(s,f): global running; running = False
signal.signal(signal.SIGTERM, sig); signal.signal(signal.SIGINT, sig)

def main():
    db = AddonDB(); db.init_tables(); db.close()
    logger.info("REZE ADDON DAEMON started")
    setup_schedules()
    while running: schedule.run_pending(); time.sleep(30)
    logger.info("Shutdown complete")


if __name__ == "__main__":
    if "--status" in sys.argv: print_status()
    elif "--run" in sys.argv:
        idx = sys.argv.index("--run")+1
        if idx < len(sys.argv):
            mp = {"memory_consolidate":("memory_tier","consolidate"), "dspy_optimize":("dspy_optimizer","optimize_all"),
                  "self_evolve":("self_modifier","check_and_evolve"), "tool_scan":("tool_discovery","scan_and_discover"),
                  "curiosity":("curiosity_engine","explore")}
            t = sys.argv[idx]
            if t in mp:
                db=AddonDB(); db.init_tables(); db.close()
                run_module(*mp[t])
            else: print(f"Available: {list(mp.keys())}")
    elif "--init" in sys.argv:
        db=AddonDB(); db.init_tables(); db.close()
    else: main()
