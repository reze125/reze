"""
MODULE 5: Curiosity Engine (AgentEvolver). 빈 시간에 호기심 탐색->인사이트 자동 저장.
"""

import os, json, time, random
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from addon_db import AddonDB, SSOTReader


class CuriosityEngine:
    TEMPLATES = {
        "traffic_anomaly": {
            "templates": ["{blog} 최근 트래픽 변동 원인?", "{blog} 인기 글 공통점?"],
            "targets":"blogs", "value":0.8
        },
        "competitor_change": {
            "templates": ["{service} 경쟁사 최근 변경사항?", "{service} 새 경쟁자?"],
            "targets":"all", "value":0.7
        },
        "user_behavior": {
            "templates": ["{saas} 가장 많이 쓰는 기능?", "{saas} 이탈 패턴?"],
            "targets":"saas", "value":0.9
        },
        "cost_optimization": {
            "templates": ["Docker 컨테이너 리소스 낭비?", "API 비용 최적화 방법?"],
            "targets":"infra", "value":0.6
        },
        "new_opportunity": {
            "templates": ["크로스셀링 기회?", "새 수익 모델?"],
            "targets":"all", "value":0.9
        },
    }

    def __init__(self, config=None):
        self.db = AddonDB()
        self.ssot = SSOTReader()
        self.max_per_day = 5
        self.services = {
            "blogs":["ai-tools-lab","nocode-tools-lab"],
            "saas":["postpilot","quotepilot","browserpilot","agenthub","rag-service"],
            "all":["postpilot","quotepilot","ai-tools-lab","nocode-tools-lab"],
            "infra":["docker-host"], "tech":["reze-system"]
        }

    def generate_questions(self, max_q=5) -> List[dict]:
        recent = {r["category"] for r in self.db.conn.execute("SELECT category FROM curiosity_questions WHERE created_at > datetime('now','-3 days')").fetchall()}
        cats = sorted([(c,s, s["value"]*(1.5 if c not in recent else 1.0)) for c,s in self.TEMPLATES.items()], key=lambda x:x[2], reverse=True)
        qs = []
        for cat, spec, pri in cats[:max_q]:
            tpl = random.choice(spec["templates"])
            pool = self.services.get(spec["targets"], self.services["all"])
            tgt = random.choice(pool) if pool else "general"
            q = tpl.format(blog=tgt, service=tgt, saas=tgt)
            cur = self.db.conn.execute("INSERT INTO curiosity_questions (category,question,target_service,status) VALUES (?,?,?,'pending')", (cat,q,tgt))
            qs.append({"id":cur.lastrowid,"category":cat,"question":q,"target":tgt,"priority":round(pri,2)})
        self.db.conn.commit()
        return qs

    def investigate_question(self, qid) -> dict:
        row = self.db.conn.execute("SELECT * FROM curiosity_questions WHERE id=?", (qid,)).fetchone()
        if not row: return {"status":"error"}
        self.db.conn.execute("UPDATE curiosity_questions SET status='exploring' WHERE id=?", (qid,))
        self.db.conn.commit()
        try:
            from groq_rotator import get_groq
            ctx = self._context(row["category"], row["target_service"])
            content = get_groq().chat(messages=[
                {"role":"system","content":'Answer as $500/hr consultant. Return JSON: {"answer":"...","insight_value":0.0-1.0,"action":"..."}'},
                {"role":"user","content":json.dumps({"question":row["question"],"category":row["category"],"context":ctx}, ensure_ascii=False)}
            ], max_tokens=2000, temperature=0.4)
            if not content:
                self.db.conn.execute("UPDATE curiosity_questions SET status='pending' WHERE id=?", (qid,))
                self.db.conn.commit(); return {"status":"error","reason":"No LLM response"}
            try:
                js = content.split("```json")[1].split("```")[0] if "```json" in content else content
                finding = json.loads(js)
            except: finding = {"answer":content,"insight_value":0.5,"action":"none"}
            iv = float(finding.get("insight_value",0.5))
            self.db.conn.execute("UPDATE curiosity_questions SET status='answered',answer=?,insight_value=?,follow_up_action=?,answered_at=datetime('now') WHERE id=?",
                (json.dumps(finding, ensure_ascii=False), iv, finding.get("action",""), qid))
            self.db.conn.execute("INSERT INTO exploration_log (question_id,findings) VALUES (?,?)", (qid, json.dumps(finding, ensure_ascii=False)))
            self.db.conn.commit()
            return {"status":"answered","insight_value":iv,"action":finding.get("action","")}
        except Exception as e:
            self.db.conn.execute("UPDATE curiosity_questions SET status='pending' WHERE id=?", (qid,)); self.db.conn.commit()
            return {"status":"error","reason":str(e)}

    def promote_insights(self) -> int:
        rows = self.db.conn.execute("SELECT * FROM curiosity_questions WHERE status='answered' AND insight_value>=0.7 AND follow_up_action IS NOT NULL ORDER BY insight_value DESC LIMIT 5").fetchall()
        pending = []
        for r in rows:
            pending.append({"source":"curiosity","category":r["category"],"question":r["question"],
                            "answer":(r["answer"] or "")[:500],"action":r["follow_up_action"],"value":r["insight_value"]})
            self.db.conn.execute("UPDATE curiosity_questions SET status='archived' WHERE id=?", (r["id"],))
        if pending:
            fp = os.path.join(os.environ.get("REZE_HOME","/home/reze/reze-agent"), "addon/pending_insights.json")
            existing = []
            if os.path.exists(fp):
                try:
                    with open(fp) as f: existing = json.load(f)
                except: pass
            existing.extend(pending)
            with open(fp,"w") as f: json.dump(existing, f, ensure_ascii=False, indent=2)
        self.db.conn.commit()
        return len(pending)

    def explore(self) -> dict:
        start = time.time()
        rpt = {"generated":0,"answered":0,"promoted":0,"high_value":[]}
        today_cnt = self.db.conn.execute("SELECT COUNT(*) as c FROM curiosity_questions WHERE created_at LIKE ?",
            (f"{datetime.now().strftime('%Y-%m-%d')}%",)).fetchone()["c"]
        remaining = max(0, self.max_per_day - today_cnt)
        if not remaining:
            self.db.log_run("curiosity","skipped","일일 한도"); return {"status":"skipped"}
        qs = self.generate_questions(min(remaining,3)); rpt["generated"] = len(qs)
        for q in qs:
            r = self.investigate_question(q["id"])
            if r.get("status")=="answered":
                rpt["answered"]+=1
                if r.get("insight_value",0) >= 0.7: rpt["high_value"].append(q["question"][:60])
        rpt["promoted"] = self.promote_insights()
        self.db.log_run("curiosity","success",json.dumps(rpt),int((time.time()-start)*1000))
        return rpt

    def _context(self, cat, target):
        parts = [f"Target: {target}"]
        if self.ssot.available:
            plans = self.ssot.get_plan_cache(3)
            if plans: parts.append("Plans: " + "; ".join([str(p.get("content",""))[:80] for p in plans]))
        return "\n".join(parts)

    def close(self): self.db.close()


if __name__ == "__main__":
    import sys
    ce = CuriosityEngine()
    if "--test" in sys.argv:
        print("=== Curiosity 테스트 ===")
        qs = ce.generate_questions(3)
        for q in qs: print(f"  [{q['category']}] {q['question']}")
        print("완료")
    ce.close()
