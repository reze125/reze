"""CoALA - Cognitive Architectures for Language Agents.

4계층 메모리 아키텍처:
1. Working Memory: 현재 태스크 컨텍스트 (휘발성)
2. Episodic Memory: 과거 경험 기록 (영구)
3. Semantic Memory: 일반화된 지식 (영구)
4. Procedural Memory: 성공 패턴/스킬 (Voyager 연동)
"""
import logging
import json
import uuid
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger("REZE.coala")


@dataclass
class WorkingMemory:
    """현재 태스크 컨텍스트 (휘발성)."""
    task_id: str
    task: str
    start_time: datetime = field(default_factory=datetime.now)
    current_plan: List[str] = field(default_factory=list)
    tool_history: List[Dict] = field(default_factory=list)
    observations: List[str] = field(default_factory=list)
    activated_episodes: List[Dict] = field(default_factory=list)
    activated_knowledge: List[Dict] = field(default_factory=list)
    activated_skills: List[Dict] = field(default_factory=list)  # Procedural (Voyager)
    scratchpad: Dict[str, Any] = field(default_factory=dict)

    def add_tool_result(self, tool: str, input_data: Any, output: str, success: bool):
        """도구 실행 결과 추가."""
        self.tool_history.append({
            "tool": tool,
            "input": str(input_data)[:300],
            "output": output[:300],
            "success": success,
            "timestamp": datetime.now().isoformat()
        })
        # 최근 10개만 유지
        if len(self.tool_history) > 10:
            self.tool_history = self.tool_history[-10:]

    def add_observation(self, obs: str):
        """관찰 추가."""
        self.observations.append(obs[:500])
        if len(self.observations) > 5:
            self.observations = self.observations[-5:]

    def get_context_snapshot(self) -> Dict:
        """현재 상태 스냅샷."""
        return {
            "task_id": self.task_id,
            "task": self.task,
            "elapsed_ms": int((datetime.now() - self.start_time).total_seconds() * 1000),
            "tools_used": [t["tool"] for t in self.tool_history],
            "last_observation": self.observations[-1] if self.observations else None,
            "activated_count": len(self.activated_episodes) + len(self.activated_knowledge) + len(self.activated_skills)
        }


@dataclass
class Episode:
    """에피소드 (경험 기록)."""
    episode_id: str
    task_id: str
    task_summary: str
    tools_used: List[str]
    outcome: str  # success/failure/partial
    outcome_summary: str
    context_snapshot: Dict
    duration_ms: int
    tokens_used: int


@dataclass
class Knowledge:
    """시맨틱 지식."""
    knowledge_id: str
    category: str  # tool_rule, domain_knowledge, pattern, constraint
    subject: str
    knowledge: str
    confidence: float
    use_count: int


class CoALAMemory:
    """CoALA 3계층 메모리 관리자."""

    # 카테고리 정의
    CATEGORIES = {
        "tool_rule": "도구 사용 규칙",
        "domain_knowledge": "도메인 지식",
        "pattern": "성공/실패 패턴",
        "constraint": "제약 조건"
    }

    def __init__(self, ssot):
        """
        Args:
            ssot: SSOT 인스턴스
        """
        self.ssot = ssot
        self.working: Optional[WorkingMemory] = None

    # === Working Memory ===

    def init_working(self, task_id: str, task: str) -> WorkingMemory:
        """새 태스크를 위한 Working Memory 초기화."""
        self.working = WorkingMemory(task_id=task_id, task=task)

        # 관련 에피소드/지식 활성화
        self.working.activated_episodes = self.retrieve_episodes(task, limit=3)
        self.working.activated_knowledge = self.retrieve_knowledge(task, limit=5)

        # Procedural Memory: Voyager 스킬 검색
        self.working.activated_skills = self.retrieve_procedural_skills(task, limit=3)

        logger.debug(
            f"[CoALA] Working memory initialized: "
            f"{len(self.working.activated_episodes)} episodes, "
            f"{len(self.working.activated_knowledge)} knowledge, "
            f"{len(self.working.activated_skills)} procedural skills"
        )
        return self.working

    def clear_working(self):
        """Working Memory 정리."""
        self.working = None

    def get_working_context(self) -> str:
        """LLM 프롬프트에 주입할 Working Memory 컨텍스트."""
        if not self.working:
            return ""

        lines = []

        # 활성화된 관련 경험
        if self.working.activated_episodes:
            lines.append("## 관련 과거 경험")
            for ep in self.working.activated_episodes[:2]:
                outcome_icon = "✓" if ep['outcome'] == 'success' else "✗"
                lines.append(f"- [{outcome_icon}] {ep['task_summary'][:100]}")
                if ep.get('outcome_summary'):
                    lines.append(f"  → {ep['outcome_summary'][:100]}")

        # 활성화된 지식
        if self.working.activated_knowledge:
            lines.append("\n## 관련 지식")
            for k in self.working.activated_knowledge[:3]:
                lines.append(f"- [{k['subject']}] {k['knowledge'][:150]}")

        # 활성화된 스킬 (Procedural Memory)
        if self.working.activated_skills:
            lines.append("\n## 재사용 가능 스킬")
            for skill in self.working.activated_skills[:2]:
                lines.append(f"- [{skill['name']}] {skill.get('description', '')[:100]}")
                if skill.get('code_snippet'):
                    lines.append(f"  코드: {skill['code_snippet'][:150]}...")

        return "\n".join(lines) if lines else ""

    # === Episodic Memory ===

    def store_episode(
        self,
        task_id: str,
        task_summary: str,
        tools_used: List[str],
        outcome: str,
        outcome_summary: str = "",
        context_snapshot: Dict = None,
        duration_ms: int = 0,
        tokens_used: int = 0
    ) -> str:
        """에피소드 저장."""
        episode_id = f"ep_{uuid.uuid4().hex[:10]}"

        self.ssot.conn.execute("""
            INSERT INTO episodic_memory
            (episode_id, task_id, task_summary, tools_used, outcome,
             outcome_summary, context_snapshot, duration_ms, tokens_used)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            episode_id, task_id, task_summary,
            json.dumps(tools_used, ensure_ascii=False),
            outcome, outcome_summary,
            json.dumps(context_snapshot or {}, ensure_ascii=False),
            duration_ms, tokens_used
        ))
        self.ssot.conn.commit()

        logger.info(f"[CoALA] Stored episode: {episode_id} ({outcome})")
        return episode_id

    def retrieve_episodes(
        self,
        query: str,
        outcome: str = None,
        limit: int = 5
    ) -> List[Dict]:
        """관련 에피소드 검색."""
        words = query.lower().split()[:5]
        results = []
        seen_ids = set()

        for word in words:
            if len(word) < 3:
                continue

            sql = """
                SELECT episode_id, task_summary, tools_used, outcome,
                       outcome_summary, created_at
                FROM episodic_memory
                WHERE task_summary LIKE ?
            """
            params = [f"%{word}%"]

            if outcome:
                sql += " AND outcome = ?"
                params.append(outcome)

            sql += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)

            rows = self.ssot.conn.execute(sql, params).fetchall()
            for r in rows:
                if r[0] not in seen_ids:
                    seen_ids.add(r[0])
                    results.append({
                        "episode_id": r[0],
                        "task_summary": r[1],
                        "tools_used": json.loads(r[2]),
                        "outcome": r[3],
                        "outcome_summary": r[4],
                        "created_at": r[5]
                    })

        return results[:limit]

    def get_recent_episodes(self, limit: int = 10) -> List[Dict]:
        """최근 에피소드 조회."""
        rows = self.ssot.conn.execute("""
            SELECT episode_id, task_summary, tools_used, outcome,
                   outcome_summary, duration_ms, tokens_used, created_at
            FROM episodic_memory
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,)).fetchall()

        return [
            {
                "episode_id": r[0],
                "task_summary": r[1],
                "tools_used": json.loads(r[2]),
                "outcome": r[3],
                "outcome_summary": r[4],
                "duration_ms": r[5],
                "tokens_used": r[6],
                "created_at": r[7]
            }
            for r in rows
        ]

    def get_episode(self, episode_id: str) -> Optional[Dict]:
        """특정 에피소드 조회."""
        row = self.ssot.conn.execute("""
            SELECT episode_id, task_id, task_summary, tools_used, outcome,
                   outcome_summary, context_snapshot, duration_ms, tokens_used, created_at
            FROM episodic_memory
            WHERE episode_id = ?
        """, (episode_id,)).fetchone()

        if not row:
            return None

        return {
            "episode_id": row[0],
            "task_id": row[1],
            "task_summary": row[2],
            "tools_used": json.loads(row[3]),
            "outcome": row[4],
            "outcome_summary": row[5],
            "context_snapshot": json.loads(row[6]) if row[6] else {},
            "duration_ms": row[7],
            "tokens_used": row[8],
            "created_at": row[9]
        }

    # === Semantic Memory ===

    def store_knowledge(
        self,
        category: str,
        subject: str,
        knowledge: str,
        confidence: float = 0.5,
        source_episodes: List[str] = None
    ) -> str:
        """시맨틱 지식 저장."""
        knowledge_id = f"kn_{uuid.uuid4().hex[:10]}"

        self.ssot.conn.execute("""
            INSERT INTO semantic_memory
            (knowledge_id, category, subject, knowledge, confidence, source_episodes)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            knowledge_id, category, subject, knowledge, confidence,
            json.dumps(source_episodes or [], ensure_ascii=False)
        ))
        self.ssot.conn.commit()

        logger.info(f"[CoALA] Stored knowledge: {knowledge_id} ({category}:{subject})")
        return knowledge_id

    def retrieve_knowledge(
        self,
        query: str,
        category: str = None,
        subject: str = None,
        limit: int = 5
    ) -> List[Dict]:
        """관련 지식 검색."""
        conditions = ["1=1"]
        params = []

        if category:
            conditions.append("category = ?")
            params.append(category)

        if subject:
            conditions.append("subject LIKE ?")
            params.append(f"%{subject}%")

        # 키워드 검색
        words = query.lower().split()[:5]
        word_conditions = []
        for word in words:
            if len(word) >= 2:
                word_conditions.append("(knowledge LIKE ? OR subject LIKE ?)")
                params.extend([f"%{word}%", f"%{word}%"])

        if word_conditions:
            conditions.append(f"({' OR '.join(word_conditions)})")

        sql = f"""
            SELECT knowledge_id, category, subject, knowledge, confidence, use_count
            FROM semantic_memory
            WHERE {' AND '.join(conditions)}
            ORDER BY confidence DESC, use_count DESC
            LIMIT ?
        """
        params.append(limit)

        rows = self.ssot.conn.execute(sql, params).fetchall()

        results = []
        for r in rows:
            results.append({
                "knowledge_id": r[0],
                "category": r[1],
                "subject": r[2],
                "knowledge": r[3],
                "confidence": r[4],
                "use_count": r[5]
            })
            # 사용 카운트 증가
            self.ssot.conn.execute("""
                UPDATE semantic_memory
                SET use_count = use_count + 1, last_used_at = datetime('now')
                WHERE knowledge_id = ?
            """, (r[0],))

        self.ssot.conn.commit()
        return results

    def get_knowledge(self, knowledge_id: str) -> Optional[Dict]:
        """특정 지식 조회."""
        row = self.ssot.conn.execute("""
            SELECT knowledge_id, category, subject, knowledge, confidence,
                   source_episodes, use_count, created_at
            FROM semantic_memory
            WHERE knowledge_id = ?
        """, (knowledge_id,)).fetchone()

        if not row:
            return None

        return {
            "knowledge_id": row[0],
            "category": row[1],
            "subject": row[2],
            "knowledge": row[3],
            "confidence": row[4],
            "source_episodes": json.loads(row[5]) if row[5] else [],
            "use_count": row[6],
            "created_at": row[7]
        }

    def update_knowledge_confidence(self, knowledge_id: str, delta: float):
        """지식 신뢰도 업데이트."""
        self.ssot.conn.execute("""
            UPDATE semantic_memory
            SET confidence = MAX(0.1, MIN(1.0, confidence + ?)),
                updated_at = datetime('now')
            WHERE knowledge_id = ?
        """, (delta, knowledge_id))
        self.ssot.conn.commit()

    def get_knowledge_by_subject(self, subject: str) -> List[Dict]:
        """특정 주제의 지식 조회."""
        rows = self.ssot.conn.execute("""
            SELECT knowledge_id, category, subject, knowledge, confidence
            FROM semantic_memory
            WHERE subject = ?
            ORDER BY confidence DESC
        """, (subject,)).fetchall()

        return [
            {
                "knowledge_id": r[0],
                "category": r[1],
                "subject": r[2],
                "knowledge": r[3],
                "confidence": r[4]
            }
            for r in rows
        ]

    def get_knowledge_by_category(self, category: str, limit: int = 10) -> List[Dict]:
        """특정 카테고리의 지식 조회."""
        rows = self.ssot.conn.execute("""
            SELECT knowledge_id, category, subject, knowledge, confidence, use_count
            FROM semantic_memory
            WHERE category = ?
            ORDER BY confidence DESC, use_count DESC
            LIMIT ?
        """, (category, limit)).fetchall()

        return [
            {
                "knowledge_id": r[0],
                "category": r[1],
                "subject": r[2],
                "knowledge": r[3],
                "confidence": r[4],
                "use_count": r[5]
            }
            for r in rows
        ]

    # === Episodic → Semantic 추상화 ===

    def extract_knowledge_from_episodes(self, min_episodes: int = 3) -> int:
        """유사 에피소드에서 시맨틱 지식 추출 (간단한 규칙 기반)."""
        # 추출되지 않은 성공 에피소드 조회
        rows = self.ssot.conn.execute("""
            SELECT episode_id, task_summary, tools_used, outcome_summary
            FROM episodic_memory
            WHERE outcome = 'success' AND lessons_extracted = 0
            ORDER BY created_at DESC
            LIMIT 50
        """).fetchall()

        if len(rows) < min_episodes:
            return 0

        # 도구별로 그룹화
        by_tool = {}
        for r in rows:
            tools = json.loads(r[2])
            for tool in tools:
                if tool not in by_tool:
                    by_tool[tool] = []
                by_tool[tool].append({
                    "episode_id": r[0],
                    "task": r[1],
                    "outcome": r[3]
                })

        extracted = 0
        for tool, episodes in by_tool.items():
            if len(episodes) >= min_episodes:
                # 도구별 성공 패턴 추출
                knowledge = f"{tool} 도구는 {len(episodes)}건의 태스크에서 성공적으로 사용됨"
                self.store_knowledge(
                    category="pattern",
                    subject=tool,
                    knowledge=knowledge,
                    confidence=min(0.9, 0.5 + len(episodes) * 0.05),
                    source_episodes=[ep["episode_id"] for ep in episodes]
                )
                extracted += 1

                # 추출 완료 마킹
                for ep in episodes:
                    self.ssot.conn.execute("""
                        UPDATE episodic_memory SET lessons_extracted = 1
                        WHERE episode_id = ?
                    """, (ep["episode_id"],))

        self.ssot.conn.commit()
        logger.info(f"[CoALA] Extracted {extracted} knowledge from episodes")
        return extracted

    # === 통계 ===

    def get_stats(self) -> Dict[str, Any]:
        """메모리 통계."""
        ep_row = self.ssot.conn.execute("""
            SELECT COUNT(*),
                   SUM(CASE WHEN outcome = 'success' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN outcome = 'failure' THEN 1 ELSE 0 END)
            FROM episodic_memory
        """).fetchone()

        sem_row = self.ssot.conn.execute("""
            SELECT COUNT(*), SUM(use_count), AVG(confidence)
            FROM semantic_memory
        """).fetchone()

        return {
            "episodic": {
                "total": ep_row[0] or 0,
                "success": ep_row[1] or 0,
                "failure": ep_row[2] or 0
            },
            "semantic": {
                "total": sem_row[0] or 0,
                "total_uses": sem_row[1] or 0,
                "avg_confidence": round(sem_row[2] or 0, 2)
            },
            "working": {
                "active": self.working is not None,
                "tools_used": len(self.working.tool_history) if self.working else 0
            }
        }

    def cleanup_old_episodes(self, days: int = 90) -> int:
        """오래된 에피소드 정리."""
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()

        cursor = self.ssot.conn.execute(
            "DELETE FROM episodic_memory WHERE created_at < ? AND lessons_extracted = 1",
            (cutoff,)
        )
        deleted = cursor.rowcount
        self.ssot.conn.commit()

        if deleted > 0:
            logger.info(f"[CoALA] Cleaned up {deleted} old episodes")
        return deleted

    # === Procedural Memory (Voyager 연동) ===

    def retrieve_procedural_skills(self, task: str, limit: int = 3) -> List[Dict]:
        """
        Voyager 스킬 라이브러리에서 관련 스킬 검색.

        Procedural Memory = 성공한 작업 패턴/스킬
        Voyager의 voyager_skills 테이블과 연동하여 4계층 메모리 완성.

        Args:
            task: 현재 태스크
            limit: 반환할 최대 스킬 수

        Returns:
            List[Dict]: [{name, description, code_snippet, use_count, success_rate}, ...]
        """
        try:
            from manus.voyager import VoyagerEngine

            voyager = VoyagerEngine(ssot=self.ssot)

            # 유사 스킬 검색
            skill = voyager.find_similar_skill(task, threshold=0.3)
            if not skill:
                return []

            # 단일 스킬을 리스트로 반환
            return [{
                "skill_id": skill.skill_id,
                "name": skill.name,
                "description": skill.description,
                "code_snippet": skill.code[:200] if skill.code else "",
                "use_count": skill.use_count,
                "success_rate": skill.success_rate
            }]

        except Exception as e:
            logger.warning(f"[CoALA] Procedural memory retrieval failed: {e}")
            return []

    def store_procedural_skill(
        self,
        task: str,
        code: str,
        description: str = ""
    ) -> Optional[str]:
        """
        새 스킬을 Procedural Memory(Voyager)에 저장.

        Args:
            task: 원래 태스크
            code: 성공한 코드
            description: 스킬 설명

        Returns:
            skill_id 또는 None
        """
        try:
            from manus.voyager import VoyagerEngine

            voyager = VoyagerEngine(ssot=self.ssot)
            skill = voyager.save_skill(
                task=task,
                code=code,
                description=description
            )
            logger.info(f"[CoALA] Stored procedural skill: {skill.skill_id}")
            return skill.skill_id

        except Exception as e:
            logger.warning(f"[CoALA] Procedural skill storage failed: {e}")
            return None
