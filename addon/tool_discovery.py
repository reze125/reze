"""
MODULE 4: Active Tool Discovery (MCP-Zero + Alita). 새 서비스 발견->도구 자동 생성.
"""

import os, json, time, subprocess
from datetime import datetime
from typing import Optional, Dict, List
from addon_db import AddonDB


class ToolDiscovery:
    def __init__(self, config=None):
        self.db = AddonDB()
        self.reze_home = os.environ.get("REZE_HOME", "/home/reze/reze-agent")
        self.registry_dir = config.get("registry_dir", f"{self.reze_home}/addon/tool_registry") if config else f"{self.reze_home}/addon/tool_registry"
        os.makedirs(self.registry_dir, exist_ok=True)
        self.verification_attempts = 3

    def scan_environment(self) -> List[dict]:
        discovered = self._scan_docker() + self._scan_pm2() + self._scan_cron()
        new = []
        for s in discovered:
            try:
                self.db.conn.execute("INSERT OR IGNORE INTO discovered_services (service_type,service_name,service_meta) VALUES (?,?,?)",
                    (s["type"], s["name"], json.dumps(s.get("meta",{}))))
                if self.db.conn.total_changes > 0: new.append(s)
            except: pass
        self.db.conn.commit()
        return new

    def _scan_docker(self):
        try:
            r = subprocess.run(["docker","ps","--format","{{.Names}}\t{{.Image}}\t{{.Ports}}\t{{.Status}}"],
                capture_output=True, text=True, timeout=10)
            if r.returncode: return []
            svcs = []
            for line in r.stdout.strip().split("\n"):
                if not line.strip(): continue
                p = line.split("\t")
                svcs.append({"type":"docker","name":p[0],"meta":{"image":p[1] if len(p)>1 else "","ports":p[2] if len(p)>2 else ""}})
            return svcs
        except: return []

    def _scan_pm2(self):
        try:
            r = subprocess.run(["pm2","jlist"], capture_output=True, text=True, timeout=10)
            if r.returncode: return []
            return [{"type":"pm2","name":p.get("name","?"),"meta":{"status":p.get("pm2_env",{}).get("status","")}} for p in json.loads(r.stdout)]
        except: return []

    def _scan_cron(self):
        try:
            r = subprocess.run(["crontab","-l"], capture_output=True, text=True, timeout=5)
            if r.returncode: return []
            return [{"type":"cron","name":f"cron_{hash(l)%10000}","meta":{"schedule":l}} for l in r.stdout.strip().split("\n") if l.strip() and not l.startswith("#")]
        except: return []

    def analyze_tool_needs(self, service) -> List[dict]:
        try:
            from groq_rotator import get_groq
            content = get_groq().chat(messages=[
                {"role":"system","content":"Given a service, determine needed management tools. Return JSON array: [{name, description, priority}]. ONLY JSON."},
                {"role":"user","content":json.dumps(service, indent=2)}
            ], max_tokens=2000, temperature=0.2)
            if not content: return []
            js = content.split("```json")[1].split("```")[0] if "```json" in content else content.split("```")[1].split("```")[0] if "```" in content else content
            r = json.loads(js)
            return r if isinstance(r, list) else r.get("tools",[])
        except: return []

    def find_existing_tool(self, desc):
        kw = set(desc.lower().split())
        rows = self.db.conn.execute("SELECT * FROM tool_registry WHERE verified=1").fetchall()
        best, bs = None, 0.0
        for r in rows:
            dw = set((r["description"] or "").lower().split())
            if dw:
                ov = len(kw & dw)/max(len(kw),1)
                if ov > bs and ov > 0.3: bs, best = ov, dict(r)
        return best

    def generate_tool(self, spec, service):
        tn, td = spec.get("name","unnamed"), spec.get("description","")
        ex = self.find_existing_tool(td)
        if ex: return {"status":"reused","tool_name":ex["tool_name"]}
        try:
            from groq_rotator import get_groq
            content = get_groq().chat(messages=[
                {"role":"system","content":"Generate standalone Python tool. Single file, stdlib+httpx only. Include __main__. Return in ```python``` block."},
                {"role":"user","content":json.dumps({"tool_name":tn,"description":td,"service":service}, indent=2)}
            ], max_tokens=3000, temperature=0.2)
            if not content: return {"status":"error","reason":"No response"}
            if "```python" not in content: return {"status":"error","reason":"No code block"}
            code = content.split("```python")[1].split("```")[0].strip()
            safe = "".join(c if c.isalnum() or c=="_" else "_" for c in tn)
            tp = os.path.join(self.registry_dir, f"{safe}.py")
            with open(tp,"w") as f: f.write(code)
            self.db.conn.execute("INSERT INTO tool_registry (tool_name,tool_type,description,code_path,source_service,verification_count) VALUES (?,'script',?,?,?,0) ON CONFLICT(tool_name) DO UPDATE SET code_path=excluded.code_path",
                (tn, td, tp, service.get("name","")))
            self.db.conn.commit()
            return {"status":"created","tool_name":tn,"code_path":tp}
        except Exception as e: return {"status":"error","reason":str(e)}

    def verify_tool(self, tn):
        row = self.db.conn.execute("SELECT * FROM tool_registry WHERE tool_name=?", (tn,)).fetchone()
        if not row or not row["code_path"] or not os.path.exists(row["code_path"]): return {"status":"error"}
        try:
            r = subprocess.run(["python3","-c",f"import ast; ast.parse(open('{row['code_path']}').read())"], capture_output=True, text=True, timeout=10)
            if r.returncode: return {"status":"failed","reason":r.stderr[:200]}
        except: return {"status":"failed"}
        nc = (row["verification_count"] or 0)+1
        v = 1 if nc >= self.verification_attempts else 0
        self.db.conn.execute("UPDATE tool_registry SET verification_count=?, verified=? WHERE tool_name=?", (nc, v, tn))
        self.db.conn.commit()
        return {"status":"verified" if v else f"pass_{nc}/{self.verification_attempts}"}

    def scan_and_discover(self) -> dict:
        start = time.time()
        rpt = {"scanned":0,"new":0,"created":0,"reused":0,"errors":[]}
        new = self.scan_environment(); rpt["new"] = len(new)
        pending = self.db.conn.execute("SELECT * FROM discovered_services WHERE status='new' LIMIT 5").fetchall()
        all_svc = new + [dict(r) for r in pending]; rpt["scanned"] = len(all_svc)
        for s in all_svc:
            sd = s if isinstance(s,dict) else dict(s)
            sn = sd.get("name") or sd.get("service_name","?")
            needs = self.analyze_tool_needs(sd)
            if not needs:
                self.db.conn.execute("UPDATE discovered_services SET status='analyzed' WHERE service_name=?", (sn,)); continue
            for ts in needs[:3]:
                r = self.generate_tool(ts, sd)
                if r.get("status")=="created": rpt["created"]+=1; self.verify_tool(r["tool_name"])
                elif r.get("status")=="reused": rpt["reused"]+=1
                else: rpt["errors"].append(f"{sn}: {r.get('reason','')[:80]}")
            self.db.conn.execute("UPDATE discovered_services SET status='tools_created' WHERE service_name=?", (sn,))
        self.db.conn.commit()
        self.db.log_run("tool_discovery","success",json.dumps(rpt),int((time.time()-start)*1000))
        return rpt

    def close(self): self.db.close()


if __name__ == "__main__":
    import sys
    td = ToolDiscovery()
    if "--test" in sys.argv:
        print("=== Tool Discovery 테스트 ===")
        svcs = td.scan_environment()
        print(f"서비스: {len(svcs)}개")
        for s in svcs[:5]: print(f"  [{s['type']}] {s['name']}")
        inv = td.db.conn.execute("SELECT * FROM tool_registry").fetchall()
        print(f"도구: {len(inv)}개")
        print("완료")
    td.close()
