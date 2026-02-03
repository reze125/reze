"""
MODULE 3: Self-Modification (DGM + SICA). 자기 스킬 코드 수정->테스트->적용/롤백.
"""

import os, json, time, hashlib, shutil, subprocess, difflib
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from pathlib import Path
from addon_db import AddonDB, SSOTReader


class SelfModifier:
    PROTECTED_FILES = {"autonomous_ops.py","reze_daemon.py","ssot.py","reze_core.py","addon_daemon.py","addon_db.py"}
    MODIFIABLE_PATTERNS = ["skills/*.py","prompts/*.yaml","configs/services.yaml"]

    def __init__(self, config=None):
        self.db = AddonDB()
        self.ssot = SSOTReader()
        self.reze_home = os.environ.get("REZE_HOME", "/home/reze/reze-agent")
        self.archive_dir = config.get("archive_dir", f"{self.reze_home}/addon/archive") if config else f"{self.reze_home}/addon/archive"
        os.makedirs(self.archive_dir, exist_ok=True)
        self.utility_weights = {"quality":0.5,"cost":0.3,"speed":0.2}
        self.max_daily_mods = 3
        self.sandbox_timeout = 60

    def identify_weak_skills(self) -> List[dict]:
        weak = []
        if self.ssot.available:
            for skill in self.ssot.get_dynamic_skills():
                sd = dict(skill) if hasattr(skill,'keys') else skill
                score = float(sd.get("quality_score",0) or 0)
                usage = int(sd.get("usage_count",0) or 0)
                if score < 0.6 or (usage > 5 and score < 0.7):
                    weak.append({"name":sd.get("name","?"),"file_path":sd.get("file_path",""),
                                 "quality_score":score,"usage_count":usage,"weakness":"low_quality" if score<0.6 else "degrading"})
        prev = self.db.conn.execute("SELECT target_file, COUNT(*) as c FROM modification_archive WHERE status='rolled_back' GROUP BY target_file HAVING c>=2").fetchall()
        for r in prev:
            weak.append({"name":os.path.basename(r["target_file"]),"file_path":r["target_file"],
                         "quality_score":0.0,"usage_count":0,"weakness":"repeated_failure"})
        return weak

    def generate_modification(self, file_path, weakness, context="") -> Optional[dict]:
        if not self._is_modifiable(file_path): return {"status":"blocked","reason":f"Protected: {file_path}"}
        if not self._check_daily_limit(): return {"status":"blocked","reason":"일일 한도 초과"}
        full = os.path.join(self.reze_home, file_path)
        if not os.path.exists(full): return {"status":"error","reason":f"Not found: {full}"}
        with open(full) as f: orig = f.read()
        orig_hash = hashlib.sha256(orig.encode()).hexdigest()
        try:
            from groq_rotator import get_groq
            response = get_groq().chat(messages=[
                {"role":"system","content":self._sys_prompt()},
                {"role":"user","content":self._usr_prompt(file_path, orig, weakness, context)}
            ], max_tokens=4096, temperature=0.2)
            if not response: return {"status":"error","reason":"LLM 응답 없음"}
        except Exception as e: return {"status":"error","reason":str(e)}
        modified = self._extract_code(response, orig)
        if not modified or modified == orig: return {"status":"no_change"}
        diff = "\n".join(difflib.unified_diff(orig.splitlines(), modified.splitlines(), fromfile=f"a/{file_path}", tofile=f"b/{file_path}", lineterm=""))
        mod_hash = hashlib.sha256(modified.encode()).hexdigest()
        cur = self.db.conn.execute("INSERT INTO modification_archive (target_file,original_hash,modified_hash,diff_text,reason,status) VALUES (?,?,?,?,?,'proposed')",
            (file_path, orig_hash, mod_hash, diff, weakness))
        self.db.conn.commit()
        return {"status":"proposed","archive_id":cur.lastrowid,"file_path":file_path,"modified_code":modified}

    def test_in_sandbox(self, archive_id, modified_code) -> dict:
        row = self.db.conn.execute("SELECT * FROM modification_archive WHERE id=?", (archive_id,)).fetchone()
        if not row: return {"passed":False,"reason":"Not found"}
        sd = os.path.join(self.archive_dir, f"sandbox_{archive_id}"); os.makedirs(sd, exist_ok=True)
        sf = os.path.join(sd, os.path.basename(row["target_file"]))
        with open(sf,"w") as f: f.write(modified_code)
        tests = [self._test_syntax(sf), self._test_imports(sf)]
        ok = all(t["passed"] for t in tests)
        self.db.conn.execute("INSERT INTO modification_sandbox (archive_id,test_command,test_output,test_passed,execution_time_ms) VALUES (?,?,?,?,?)",
            (archive_id, json.dumps([t["test"] for t in tests]), json.dumps(tests), 1 if ok else 0, sum(t.get("time_ms",0) for t in tests)))
        self.db.conn.execute("UPDATE modification_archive SET status=? WHERE id=?", ("testing" if ok else "rejected", archive_id))
        self.db.conn.commit(); shutil.rmtree(sd, ignore_errors=True)
        return {"passed":ok,"tests":tests}

    def evaluate_utility(self, archive_id, quality_after, cost_tokens=0, time_ms=0) -> float:
        q = quality_after
        c = min(1.0/(max(cost_tokens/1000,0.1)), 1.0)
        s = min(1.0/(max(time_ms/10000,0.1)), 1.0)
        u = self.utility_weights["quality"]*q + self.utility_weights["cost"]*c + self.utility_weights["speed"]*s
        self.db.conn.execute("UPDATE modification_archive SET utility_score=?, quality_after=? WHERE id=?", (u, quality_after, archive_id))
        self.db.conn.commit()
        return u

    def apply_modification(self, archive_id, modified_code) -> dict:
        row = self.db.conn.execute("SELECT * FROM modification_archive WHERE id=? AND status='testing'", (archive_id,)).fetchone()
        if not row: return {"status":"error","reason":"Not in testing"}
        full = os.path.join(self.reze_home, row["target_file"])
        bak = os.path.join(self.archive_dir, f"{os.path.basename(row['target_file'])}.v{archive_id}.bak")
        if os.path.exists(full): shutil.copy2(full, bak)
        with open(full,"w") as f: f.write(modified_code)
        self.db.conn.execute("UPDATE modification_archive SET status='applied', applied_at=datetime('now') WHERE id=?", (archive_id,))
        self.db.conn.commit()
        return {"status":"applied","backup":bak}

    def rollback(self, archive_id) -> dict:
        row = self.db.conn.execute("SELECT * FROM modification_archive WHERE id=? AND status='applied'", (archive_id,)).fetchone()
        if not row: return {"status":"error"}
        bak = os.path.join(self.archive_dir, f"{os.path.basename(row['target_file'])}.v{archive_id}.bak")
        if os.path.exists(bak):
            shutil.copy2(bak, os.path.join(self.reze_home, row["target_file"]))
            self.db.conn.execute("UPDATE modification_archive SET status='rolled_back' WHERE id=?", (archive_id,))
            self.db.conn.commit(); return {"status":"rolled_back"}
        return {"status":"error","reason":"Backup not found"}

    def check_and_evolve(self) -> List[dict]:
        start = time.time(); results = []
        weak = self.identify_weak_skills()
        if not weak: self.db.log_run("self_modifier","skipped","No weak skills"); return [{"status":"skipped"}]
        for skill in weak[:self.max_daily_mods]:
            mod = self.generate_modification(skill["file_path"], skill["weakness"])
            if mod.get("status") != "proposed": results.append({"skill":skill["name"],**mod}); continue
            test = self.test_in_sandbox(mod["archive_id"], mod["modified_code"])
            if not test["passed"]: results.append({"skill":skill["name"],"status":"test_failed"}); continue
            u = self.evaluate_utility(mod["archive_id"], 0.7, 2000, test.get("total_time_ms",0))
            if u > 0.5:
                self.apply_modification(mod["archive_id"], mod["modified_code"])
                results.append({"skill":skill["name"],"status":"applied","utility":round(u,3)})
            else:
                self.db.conn.execute("UPDATE modification_archive SET status='rejected' WHERE id=?", (mod["archive_id"],))
                self.db.conn.commit()
                results.append({"skill":skill["name"],"status":"rejected","utility":round(u,3)})
        self.db.log_run("self_modifier","success",json.dumps(results),int((time.time()-start)*1000))
        return results

    def _is_modifiable(self, fp):
        if os.path.basename(fp) in self.PROTECTED_FILES: return False
        for p in self.MODIFIABLE_PATTERNS:
            if p.endswith("*.py") and fp.startswith(p.replace("/*.py","/")):  return True
            if p.endswith("*.yaml") and fp.startswith(p.replace("/*.yaml","/")): return True
            if fp == p: return True
        return False

    def _check_daily_limit(self):
        c = self.db.conn.execute("SELECT COUNT(*) as c FROM modification_archive WHERE status='applied' AND applied_at LIKE ?",
            (f"{datetime.now().strftime('%Y-%m-%d')}%",)).fetchone()["c"]
        return c < self.max_daily_mods

    def _sys_prompt(self):
        return "You are a code improvement expert. Given a Python file and weakness, generate improved version. Keep same interfaces. Return ONLY complete file in ```python``` block."

    def _usr_prompt(self, fp, code, weakness, ctx):
        return f"File: {fp}\nWeakness: {weakness}\nContext: {ctx}\n\n```python\n{code[:6000]}\n```\n\nGenerate improved version."

    def _extract_code(self, resp, fallback):
        if "```python" in resp:
            s = resp.index("```python")+len("```python"); return resp[s:resp.index("```",s)].strip()
        return fallback

    def _test_syntax(self, fp):
        s = time.time()
        try:
            r = subprocess.run(["python3","-c",f"import ast; ast.parse(open('{fp}').read())"], capture_output=True, text=True, timeout=10)
            return {"test":"syntax","passed":r.returncode==0,"output":r.stderr[:200] if r.returncode else "OK","time_ms":int((time.time()-s)*1000)}
        except: return {"test":"syntax","passed":False,"output":"Timeout","time_ms":10000}

    def _test_imports(self, fp):
        s = time.time()
        try:
            r = subprocess.run(["python3","-c",f"exec(open('{fp}').read())"], capture_output=True, text=True, timeout=self.sandbox_timeout)
            return {"test":"imports","passed":r.returncode==0 or "ModuleNotFoundError" not in r.stderr,"output":r.stderr[:200],"time_ms":int((time.time()-s)*1000)}
        except: return {"test":"imports","passed":False,"output":"Timeout"}

    def close(self): self.db.close()


if __name__ == "__main__":
    import sys
    sm = SelfModifier()
    if "--test" in sys.argv:
        print("=== Self-Modifier 테스트 ===")
        print(f"저성능 스킬: {len(sm.identify_weak_skills())}개")
        print(f"Protected: {sm.PROTECTED_FILES}")
        print(f"skills/x.py -> {sm._is_modifiable('skills/x.py')}")
        print(f"reze_daemon.py -> {sm._is_modifiable('reze_daemon.py')}")
        print("완료")
    sm.close()
