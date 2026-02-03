"""
MODULE 1: 2-Tier Memory (MemGPT/Letta 패턴)
Core Memory (RAM) <-> Archival Memory (Disk/Qdrant) + Sleep-Time Consolidation
"""

import json
import os
import hashlib
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from addon_db import AddonDB, SSOTReader


class CoreMemoryBlock:
    def __init__(self, name: str, content: str = "", max_tokens: int = 500):
        self.name = name
        self.content = content
        self.max_tokens = max_tokens

    def to_prompt(self) -> str:
        return f"<{self.name}>\n{self.content}\n</{self.name}>" if self.content else ""

    def estimate_tokens(self) -> int:
        return len(self.content) // 4


class TwoTierMemory:
    def __init__(self):
        self.db = AddonDB()
        self.ssot = SSOTReader()
        self.core_blocks: Dict[str, CoreMemoryBlock] = {}
        self._load_core_from_db()

    def _load_core_from_db(self):
        rows = self.db.conn.execute("SELECT * FROM core_memory").fetchall()
        for row in rows:
            self.core_blocks[row["block_name"]] = CoreMemoryBlock(
                name=row["block_name"], content=row["content"], max_tokens=row["max_tokens"])
        for name, max_t in [("current_goals",400),("active_issues",300),("service_summary",500),("boss_context",400),("recent_learnings",400)]:
            if name not in self.core_blocks:
                self.core_blocks[name] = CoreMemoryBlock(name, "", max_t)
                self._save_core_block(name)

    def _save_core_block(self, block_name: str):
        block = self.core_blocks[block_name]
        self.db.conn.execute("""
            INSERT INTO core_memory (block_name, content, token_count, max_tokens, updated_at, version)
            VALUES (?, ?, ?, ?, datetime('now'), 1)
            ON CONFLICT(block_name) DO UPDATE SET
                content=excluded.content, token_count=excluded.token_count,
                updated_at=datetime('now'), version=version+1
        """, (block.name, block.content, block.estimate_tokens(), block.max_tokens))
        self.db.conn.commit()

    def memory_replace(self, block_name: str, old_text: str, new_text: str) -> bool:
        if block_name not in self.core_blocks: return False
        block = self.core_blocks[block_name]
        if old_text not in block.content: return False
        block.content = block.content.replace(old_text, new_text, 1)
        self._save_core_block(block_name)
        self._log_op("replace", block_name, f"'{old_text[:50]}' -> '{new_text[:50]}'")
        return True

    def memory_insert(self, block_name: str, text: str) -> bool:
        if block_name not in self.core_blocks: return False
        block = self.core_blocks[block_name]
        new_content = block.content + "\n" + text if block.content else text
        if len(new_content) // 4 > block.max_tokens:
            self.archive_to_archival(block_name, block.content, importance=0.5)
            block.content = text
        else:
            block.content = new_content
        self._save_core_block(block_name)
        self._log_op("insert", block_name, text[:100])
        return True

    def memory_rethink(self, block_name: str, new_content: str) -> bool:
        if block_name not in self.core_blocks: return False
        old = self.core_blocks[block_name].content
        if old: self.archive_to_archival(block_name, old, importance=0.3)
        self.core_blocks[block_name].content = new_content
        self._save_core_block(block_name)
        self._log_op("rethink", block_name, f"full rewrite ({len(new_content)} chars)")
        return True

    def get_core_context(self) -> str:
        parts = ["<core_memory>"]
        total = 0
        for name, block in self.core_blocks.items():
            prompt = block.to_prompt()
            if prompt:
                parts.append(prompt)
                total += block.estimate_tokens()
        parts.append("</core_memory>")
        parts.append(f"<!-- core_memory: ~{total} tokens -->")
        return "\n".join(parts)

    def archive_to_archival(self, category: str, content: str, importance: float = 0.5):
        eid = hashlib.md5(f"{category}:{content[:100]}:{time.time()}".encode()).hexdigest()
        self.db.conn.execute("""
            INSERT INTO archival_memory (category, content, embedding_id, importance_score)
            VALUES (?, ?, ?, ?)""", (category, content, eid, importance))
        self.db.conn.commit()
        try: self._embed_to_qdrant(eid, content, {"category": category, "importance": importance})
        except: pass
        self._log_op("archive", category, f"importance={importance}")

    def search_archival(self, query: str, top_k: int = 5, category: str = None) -> List[dict]:
        try:
            r = self._search_qdrant(query, top_k, category)
            if r: return r
        except: pass
        where = "WHERE content LIKE ?"
        params = [f"%{query}%"]
        if category: where += " AND category = ?"; params.append(category)
        rows = self.db.conn.execute(f"""
            SELECT * FROM archival_memory {where}
            ORDER BY importance_score DESC, created_at DESC LIMIT ?
        """, params + [top_k]).fetchall()
        for row in rows:
            self.db.conn.execute("UPDATE archival_memory SET access_count=access_count+1, last_accessed=datetime('now') WHERE id=?", (row["id"],))
        self.db.conn.commit()
        self._log_op("search", None, f"query='{query[:50]}' results={len(rows)}")
        return [dict(r) for r in rows]

    def consolidate(self) -> dict:
        start = time.time()
        report = {"synced": 0, "compressed": 0, "decayed": 0}
        report["synced"] = self._sync_from_ssot()
        report["compressed"] = self._compress_old_archival(days=7)
        report["decayed"] = self._decay_unused_memories(days=14)
        self.db.log_run("memory_tier.consolidate", "success", json.dumps(report), int((time.time()-start)*1000))
        return report

    def _sync_from_ssot(self) -> int:
        synced = 0
        if self.ssot.available:
            plans = self.ssot.get_plan_cache(limit=5)
            if plans:
                txt = "\n".join([f"- [{p.get('category','general')}] {p.get('content','')[:100]}" for p in plans])
                self.memory_rethink("current_goals", txt); synced += 1
            refs = self.ssot.get_reflections(limit=5)
            if refs:
                txt = "\n".join([f"- {r.get('lesson','')[:100]}" for r in refs])
                self.memory_rethink("recent_learnings", txt); synced += 1
        return synced

    def _compress_old_archival(self, days=7) -> int:
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        rows = self.db.conn.execute("""
            SELECT id, content FROM archival_memory
            WHERE created_at < ? AND compressed=0 AND length(content)>500
            ORDER BY importance_score ASC LIMIT 10""", (cutoff,)).fetchall()
        compressed = 0
        for row in rows:
            summary = self._llm_compress(row["content"])
            if summary:
                self.db.conn.execute("UPDATE archival_memory SET content=?, compressed=1 WHERE id=?", (summary, row["id"]))
                compressed += 1
        self.db.conn.commit()
        return compressed

    def _decay_unused_memories(self, days=14) -> int:
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        r = self.db.conn.execute("""
            UPDATE archival_memory SET importance_score=MAX(0.1, importance_score*0.8)
            WHERE (last_accessed IS NULL OR last_accessed < ?) AND importance_score > 0.1""", (cutoff,))
        self.db.conn.commit()
        return r.rowcount

    def heartbeat_should_continue(self, last_action_result: str) -> dict:
        lower = last_action_result.lower()
        if any(k in lower for k in ["error","failed","partial","timeout","warning"]):
            return {"continue": True, "reason": "Action had issues", "suggested_action": "diagnose_and_retry"}
        elif any(k in lower for k in ["success","complete","done","ok","applied"]):
            return {"continue": False, "reason": "Completed", "suggested_action": "none"}
        return {"continue": True, "reason": "Ambiguous result", "suggested_action": "verify_deeper"}

    def _log_op(self, op, block=None, detail=""):
        self.db.conn.execute("INSERT INTO memory_ops_log (operation, block_name, detail) VALUES (?,?,?)", (op, block, detail))
        self.db.conn.commit()

    def _embed_to_qdrant(self, id, text, metadata):
        import httpx
        from qdrant_client import QdrantClient
        from qdrant_client.models import PointStruct
        emb = httpx.post("http://localhost:11434/api/embeddings", json={"model":"nomic-embed-text","prompt":text[:2000]}, timeout=30).json().get("embedding",[])
        if not emb: return
        QdrantClient(host="localhost",port=6333).upsert(collection_name="reze_archival_memory",
            points=[PointStruct(id=id, vector=emb, payload={"text":text[:2000], **metadata})])

    def _search_qdrant(self, query, top_k, category=None):
        import httpx
        from qdrant_client import QdrantClient
        qv = httpx.post("http://localhost:11434/api/embeddings", json={"model":"nomic-embed-text","prompt":query}, timeout=30).json().get("embedding",[])
        if not qv: return []
        client = QdrantClient(host="localhost",port=6333)
        fc = None
        if category:
            from qdrant_client.models import Filter, FieldCondition, MatchValue
            fc = Filter(must=[FieldCondition(key="category", match=MatchValue(value=category))])
        results = client.search(collection_name="reze_archival_memory", query_vector=qv, limit=top_k, query_filter=fc)
        return [{"content":r.payload.get("text",""), "score":r.score} for r in results]

    def _llm_compress(self, text: str) -> Optional[str]:
        try:
            from groq_rotator import get_groq
            return get_groq().chat(
                messages=[{"role":"system","content":"Compress into 2-3 key sentences. Keep facts."},
                          {"role":"user","content":text[:3000]}],
                model="llama-3.1-8b-instant", max_tokens=200, temperature=0.1)
        except Exception as e:
            print(f"LLM 압축 실패: {e}"); return None

    def close(self):
        self.db.close()


if __name__ == "__main__":
    import sys
    if "--test" in sys.argv:
        print("=== 2-Tier Memory 테스트 ===")
        mem = TwoTierMemory()
        mem.memory_insert("current_goals", "월수익 $5K 달성")
        mem.memory_insert("active_issues", "Gumroad Stripe 인증 차단")
        mem.memory_insert("service_summary", "Docker 19개 가동, 블로그 2개 활성, SaaS 5개")
        print(mem.get_core_context())
        mem.archive_to_archival("learnings", "Groq가 Claude보다 95% 저렴", 0.8)
        r = mem.search_archival("비용")
        print(f"Archival 검색: {len(r)}건")
        hb = mem.heartbeat_should_continue("ERROR: nginx failed")
        print(f"Heartbeat: continue={hb['continue']}")
        mem.close()
        print("완료")
