"""
MODULE 2: DSPy 프롬프트 자동 최적화. boss_feedback 데이터 기반.
"""

import os
import json
import time
from datetime import datetime
from typing import Optional, List, Dict
from addon_db import AddonDB, SSOTReader


class DSPyOptimizer:
    MODULES = {
        "blog_article_gen": {
            "signature": "topic, competitors, keywords, style_guide -> article",
            "description": "SEO 최적화 블로그 글 생성",
            "metric": "boss_feedback_score",
        },
        "saas_analysis": {
            "signature": "service_data, metrics, competitors -> analysis_report",
            "description": "SaaS 서비스 분석 리포트",
            "metric": "actionability_score",
        },
        "task_decomposition": {
            "signature": "goal, constraints, current_state -> subtasks",
            "description": "목표 -> 하위 태스크 분해",
            "metric": "completion_rate",
        },
        "competitor_research": {
            "signature": "service, market_data -> insights, opportunities",
            "description": "경쟁사 분석",
            "metric": "insight_usefulness",
        },
    }

    def __init__(self, config=None):
        self.db = AddonDB()
        self.ssot = SSOTReader()
        self.cache_dir = config.get("cache_dir", "/home/reze/reze-agent/addon/dspy_cache") if config else "/home/reze/reze-agent/addon/dspy_cache"
        os.makedirs(self.cache_dir, exist_ok=True)

    def collect_training_data(self, module_name: str) -> List[dict]:
        data = []
        rows = self.db.conn.execute("""
            SELECT input_data, output_data, score FROM dspy_training_data
            WHERE module_name=? AND score IS NOT NULL ORDER BY score DESC LIMIT 50
        """, (module_name,)).fetchall()
        for row in rows:
            try: data.append({"input":json.loads(row["input_data"]),"output":json.loads(row["output_data"]) if row["output_data"] else None,"score":row["score"]})
            except: continue
        if self.ssot.available and module_name in ("blog_article_gen","saas_analysis"):
            for fb in self.ssot.get_boss_feedback(limit=30):
                try:
                    fd = dict(fb) if hasattr(fb,'keys') else fb
                    if fd.get("score"):
                        data.append({"input":{"topic":fd.get("target","")}, "output":{"result":fd.get("output","")}, "score":float(fd.get("score",0))})
                except: continue
        return data

    def add_training_example(self, module_name, input_data, output_data=None, score=None, source="auto"):
        self.db.conn.execute("INSERT INTO dspy_training_data (module_name,input_data,output_data,score,source) VALUES (?,?,?,?,?)",
            (module_name, json.dumps(input_data, ensure_ascii=False),
             json.dumps(output_data, ensure_ascii=False) if output_data else None, score, source))
        self.db.conn.commit()

    def optimize_module(self, module_name: str) -> dict:
        start = time.time()
        mod = self.MODULES.get(module_name)
        if not mod: return {"status":"error","detail":f"Unknown: {module_name}"}
        data = self.collect_training_data(module_name)
        if len(data) < 3: return {"status":"skipped","detail":f"훈련 데이터 부족: {len(data)}개"}
        try:
            import dspy
            from groq_rotator import get_groq
            lm = dspy.LM(model="groq/llama-3.3-70b-versatile", api_key=get_groq().next_key(), max_tokens=4096, temperature=0.3)
            dspy.configure(lm=lm)
            sig_str = mod["signature"]
            inp_fields = [f.strip() for f in sig_str.split("->")[0].split(",")]
            out_fields = [f.strip() for f in sig_str.split("->")[1].split(",")]

            class OptModule(dspy.Module):
                def __init__(self): super().__init__(); self.generate = dspy.ChainOfThought(sig_str)
                def forward(self, **kw): return self.generate(**kw)

            module = OptModule()
            trainset = []
            for td in data:
                if td["output"]:
                    kw = {f:str(td["input"].get(f,"")) for f in inp_fields}
                    kw.update({f:str(td["output"].get(f,"")) for f in out_fields})
                    trainset.append(dspy.Example(**kw).with_inputs(*inp_fields))
            if len(trainset) < 3: return {"status":"skipped","detail":"유효 훈련셋 부족"}

            def metric_fn(ex, pred, trace=None):
                for f in out_fields:
                    g, p = set(getattr(ex,f,"").lower().split()), set(getattr(pred,f,"").lower().split())
                    if g: return len(g&p)/len(g)
                return 0.0

            from dspy.teleprompt import BootstrapFewShot
            opt = BootstrapFewShot(metric=metric_fn, max_bootstrapped_demos=4, max_labeled_demos=min(8,len(trainset)))
            optimized = opt.compile(module, trainset=trainset)
            save_path = os.path.join(self.cache_dir, f"{module_name}_optimized.json")
            optimized.save(save_path)

            bs = self._eval(module, trainset[:5], metric_fn)
            os_ = self._eval(optimized, trainset[:5], metric_fn)
            self.db.conn.execute("""
                INSERT INTO dspy_programs (module_name,signature,current_program_path,baseline_score,optimized_score,optimization_count,last_optimized,status)
                VALUES (?,?,?,?,?,1,datetime('now'),'active')
                ON CONFLICT(module_name) DO UPDATE SET current_program_path=excluded.current_program_path,
                    baseline_score=excluded.baseline_score, optimized_score=excluded.optimized_score,
                    optimization_count=optimization_count+1, last_optimized=datetime('now'), status='active'
            """, (module_name, sig_str, save_path, bs, os_))
            self.db.conn.commit()
            imp = ((os_-bs)/max(bs,0.01))*100
            return {"status":"success","module":module_name,"baseline":round(bs,3),"optimized":round(os_,3),
                    "improvement":f"+{imp:.1f}%","save_path":save_path,"duration_ms":int((time.time()-start)*1000)}
        except ImportError: return {"status":"error","detail":"dspy 미설치"}
        except Exception as e:
            self.db.log_run("dspy_optimizer","failed",str(e))
            return {"status":"error","detail":str(e)}

    def optimize_all(self) -> List[dict]:
        results = []
        for m in self.MODULES:
            print(f"DSPy {m}..."); r = self.optimize_module(m); results.append(r)
            print(f"   -> {r['status']}: {r.get('improvement', r.get('detail',''))}")
        return results

    def get_optimized_prompt(self, module_name: str, default_prompt: str = "") -> str:
        try:
            row = self.db.conn.execute("SELECT current_program_path FROM dspy_programs WHERE module_name=? AND status='active'", (module_name,)).fetchone()
            if row and row["current_program_path"] and os.path.exists(row["current_program_path"]):
                with open(row["current_program_path"]) as f: pd = json.load(f)
                parts = [default_prompt, "\n--- Optimized ---"]
                demos = pd.get("generate",{}).get("demos",[])
                if demos:
                    parts.append("\nExamples:")
                    for i,d in enumerate(demos[:4],1): parts.append(f"\nEx {i}:\n{json.dumps(d,indent=2,ensure_ascii=False)}")
                return "\n".join(parts)
        except: pass
        return default_prompt

    def get_optimization_status(self) -> List[dict]:
        rows = self.db.conn.execute("SELECT * FROM dspy_programs").fetchall()
        return [dict(r) for r in rows]

    def _eval(self, module, examples, metric_fn):
        scores = []
        for ex in examples:
            try:
                kw = {k:getattr(ex,k) for k in ex.inputs().keys()}
                scores.append(metric_fn(ex, module(**kw)))
            except: scores.append(0.0)
        return sum(scores)/max(len(scores),1)

    def close(self): self.db.close()


if __name__ == "__main__":
    import sys
    opt = DSPyOptimizer()
    if "--test" in sys.argv:
        print("=== DSPy 테스트 ===")
        opt.add_training_example("blog_article_gen", {"topic":"AI Tools 2026"}, {"article":"# AI Tools..."}, score=0.85, source="test")
        print(f"모듈: {len(opt.get_optimization_status())}개")
        p = opt.get_optimized_prompt("blog_article_gen", "Write a blog.")
        print(f"프롬프트: {len(p)} chars")
        print("완료")
    opt.close()
