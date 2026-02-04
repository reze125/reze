"""Reflexion - 실패 기반 학습 엔진.

실패에서 교훈을 추출하고, 유사 작업 시 관련 교훈을 조회하여 적용합니다.
"""
import json
import uuid
import re
import sqlite3
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime

import logging
logger = logging.getLogger("REZE.reflexion")


@dataclass
class Lesson:
    """학습된 교훈."""
    lesson_id: str
    failure_id: str
    task_id: str
    failure_type: str
    tool_name: Optional[str]
    error_pattern: str
    lesson_text: str
    corrective_action: Optional[str]
    avoid_pattern: Optional[str]
    confidence: float = 0.5
    apply_count: int = 0
    success_count: int = 0
    tags: List[str] = field(default_factory=list)
    applicable_tools: List[str] = field(default_factory=list)


class ReflexionEngine:
    """실패 분석 및 교훈 관리."""

    def __init__(self, ssot=None, db_path: str = None):
        """
        Args:
            ssot: SSOT 인스턴스 (우선)
            db_path: DB 경로 (ssot 없을 때 사용)
        """
        self.ssot = ssot
        self.db_path = db_path

    def _get_conn(self):
        """DB 연결 획득."""
        if self.ssot:
            return self.ssot.conn
        if self.db_path:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            return conn
        raise ValueError("No database connection available")

    def _close_conn(self, conn):
        """ssot 사용 시 닫지 않음."""
        if not self.ssot and conn:
            conn.close()

    # === 교훈 추출 ===
    def extract_lesson(
        self,
        failure_id: str,
        task_id: str,
        failure_type: str,
        tool_name: Optional[str],
        error_message: str,
        context: Dict[str, Any],
        recovery_action: Optional[str] = None
    ) -> Optional[Lesson]:
        """
        실패에서 교훈 추출.

        Args:
            failure_id: failures_v6의 failure_id
            task_id: 작업 ID
            failure_type: 실패 유형
            tool_name: 실패한 도구
            error_message: 원본 오류 메시지
            context: 실패 컨텍스트
            recovery_action: 복구에 사용된 조치

        Returns:
            추출된 Lesson 또는 None
        """
        # 1. 오류 패턴 정규화
        error_pattern = self._normalize_error(error_message)

        # 2. 중복 교훈 확인
        existing = self._find_similar_lesson(failure_type, tool_name, error_pattern)
        if existing:
            # 기존 교훈 신뢰도 강화
            self._reinforce_lesson(existing.lesson_id)
            logger.debug(f"[Reflexion] Reinforced existing lesson: {existing.lesson_id}")
            return existing

        # 3. 교훈 생성
        lesson = Lesson(
            lesson_id=f"lesson_{uuid.uuid4().hex[:8]}",
            failure_id=failure_id,
            task_id=task_id,
            failure_type=failure_type,
            tool_name=tool_name,
            error_pattern=error_pattern,
            lesson_text=self._generate_lesson_text(failure_type, error_pattern, context),
            corrective_action=recovery_action,
            avoid_pattern=self._extract_avoid_pattern(error_message, context),
            tags=self._extract_tags(failure_type, tool_name, context),
            applicable_tools=[tool_name] if tool_name else []
        )

        # 4. 저장
        self._save_lesson(lesson)
        logger.info(f"[Reflexion] New lesson extracted: {lesson.lesson_id}")

        return lesson

    # === 교훈 조회 ===
    def get_relevant_lessons(
        self,
        task_description: str = "",
        tools: List[str] = None,
        failure_type: str = None,
        limit: int = 5
    ) -> List[Lesson]:
        """
        관련 교훈 조회.

        Args:
            task_description: 현재 작업 설명
            tools: 사용 예정 도구들
            failure_type: 특정 실패 유형 필터
            limit: 최대 반환 수

        Returns:
            관련성 높은 교훈 목록
        """
        conn = self._get_conn()
        try:
            # 기본 쿼리: 신뢰도 * (성공률 + 0.1) 순 정렬
            query = """
                SELECT * FROM failure_lessons
                WHERE confidence > 0.3
            """
            params = []

            if failure_type:
                query += " AND failure_type = ?"
                params.append(failure_type)

            if tools:
                # 도구 매칭 (JSON 배열에서)
                tool_conditions = " OR ".join(
                    "applicable_tools LIKE ?" for _ in tools
                )
                query += f" AND ({tool_conditions})"
                params.extend([f'%"{t}"%' for t in tools])

            query += """
                ORDER BY
                    confidence * (CAST(success_count AS REAL) / NULLIF(apply_count, 0) + 0.1) DESC,
                    updated_at DESC
                LIMIT ?
            """
            params.append(limit)

            cursor = conn.execute(query, params)
            rows = cursor.fetchall()

            return [self._row_to_lesson(row) for row in rows]
        finally:
            self._close_conn(conn)

    def get_all_lessons(self, limit: int = 100) -> List[Lesson]:
        """모든 교훈 조회 (관리용)."""
        conn = self._get_conn()
        try:
            rows = conn.execute("""
                SELECT * FROM failure_lessons
                ORDER BY updated_at DESC
                LIMIT ?
            """, (limit,)).fetchall()
            return [self._row_to_lesson(row) for row in rows]
        finally:
            self._close_conn(conn)

    def get_lesson_by_id(self, lesson_id: str) -> Optional[Lesson]:
        """특정 교훈 조회."""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM failure_lessons WHERE lesson_id = ?",
                (lesson_id,)
            ).fetchone()
            return self._row_to_lesson(row) if row else None
        finally:
            self._close_conn(conn)

    # === 교훈 적용 기록 ===
    def record_application(self, lesson_id: str, success: bool):
        """교훈 적용 결과 기록."""
        conn = self._get_conn()
        try:
            now = datetime.now().isoformat()
            if success:
                conn.execute("""
                    UPDATE failure_lessons
                    SET apply_count = apply_count + 1,
                        success_count = success_count + 1,
                        confidence = MIN(1.0, confidence + 0.1),
                        updated_at = ?
                    WHERE lesson_id = ?
                """, (now, lesson_id))
            else:
                conn.execute("""
                    UPDATE failure_lessons
                    SET apply_count = apply_count + 1,
                        confidence = MAX(0.1, confidence - 0.05),
                        updated_at = ?
                    WHERE lesson_id = ?
                """, (now, lesson_id))

            conn.commit()
            logger.debug(f"[Reflexion] Recorded application: {lesson_id}, success={success}")
        finally:
            self._close_conn(conn)

    # === 프롬프트용 포맷 ===
    def format_lessons_for_prompt(self, lessons: List[Lesson]) -> str:
        """교훈을 프롬프트 주입용으로 포맷."""
        if not lessons:
            return ""

        lines = ["## Past Lessons (from previous failures):"]
        for i, lesson in enumerate(lessons, 1):
            lines.append(f"\n### Lesson {i} (confidence: {lesson.confidence:.0%})")
            lines.append(f"- **Situation**: {lesson.failure_type} with {lesson.tool_name or 'unknown tool'}")
            lines.append(f"- **What went wrong**: {lesson.error_pattern}")
            lines.append(f"- **Lesson**: {lesson.lesson_text}")
            if lesson.corrective_action:
                lines.append(f"- **Recommended action**: {lesson.corrective_action}")
            if lesson.avoid_pattern:
                lines.append(f"- **Avoid**: {lesson.avoid_pattern}")

        return "\n".join(lines)

    # === 교훈 삭제 ===
    def delete_lesson(self, lesson_id: str) -> bool:
        """교훈 삭제."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "DELETE FROM failure_lessons WHERE lesson_id = ?",
                (lesson_id,)
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            self._close_conn(conn)

    # === 통계 ===
    def get_stats(self) -> Dict[str, Any]:
        """교훈 통계."""
        conn = self._get_conn()
        try:
            # 전체 수
            total = conn.execute("SELECT COUNT(*) FROM failure_lessons").fetchone()[0]

            # 유형별 수
            by_type = conn.execute("""
                SELECT failure_type, COUNT(*) as cnt
                FROM failure_lessons
                GROUP BY failure_type
                ORDER BY cnt DESC
            """).fetchall()

            # 평균 신뢰도
            avg_conf = conn.execute(
                "SELECT AVG(confidence) FROM failure_lessons"
            ).fetchone()[0] or 0

            # 총 적용 횟수
            total_applies = conn.execute(
                "SELECT SUM(apply_count) FROM failure_lessons"
            ).fetchone()[0] or 0

            # 총 성공 횟수
            total_success = conn.execute(
                "SELECT SUM(success_count) FROM failure_lessons"
            ).fetchone()[0] or 0

            return {
                "total_lessons": total,
                "by_type": {row[0]: row[1] for row in by_type},
                "avg_confidence": round(avg_conf, 3),
                "total_applications": total_applies,
                "total_successes": total_success,
                "success_rate": round(total_success / total_applies * 100, 1) if total_applies > 0 else 0
            }
        finally:
            self._close_conn(conn)

    # === 내부 헬퍼 ===
    def _normalize_error(self, error_message: str) -> str:
        """오류 메시지를 정규화된 패턴으로 변환."""
        if not error_message:
            return ""
        # 숫자, 경로, UUID 등 제거
        normalized = re.sub(r'\d+', 'N', error_message)
        normalized = re.sub(r'/[^\s]+', '/PATH', normalized)
        normalized = re.sub(
            r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}',
            'UUID', normalized, flags=re.IGNORECASE
        )
        # 앞 100자만 유지
        return normalized[:100]

    def _generate_lesson_text(
        self,
        failure_type: str,
        error_pattern: str,
        context: Dict[str, Any]
    ) -> str:
        """실패 유형에 따른 기본 교훈 생성."""
        templates = {
            "tool_error": f"Tool execution failed with pattern: {error_pattern}. Check tool parameters.",
            "timeout": "Operation timed out. Consider breaking into smaller steps or increasing timeout.",
            "validation": f"Input validation failed: {error_pattern}. Ensure proper data format.",
            "permission": "Permission denied. Check access rights before attempting.",
            "network": "Network error occurred. Implement retry logic or check connectivity.",
            "llm_error": "LLM call failed. Consider fallback provider or retry.",
        }
        return templates.get(failure_type, f"Operation failed: {error_pattern}")

    def _extract_avoid_pattern(self, error_message: str, context: Dict) -> Optional[str]:
        """피해야 할 패턴 추출."""
        if not error_message:
            return None
        error_lower = error_message.lower()
        if "not found" in error_lower:
            return "Verify resource exists before access"
        if "permission" in error_lower or "denied" in error_lower:
            return "Check permissions before operation"
        if "timeout" in error_lower:
            return "Use smaller batch sizes or async operations"
        if "invalid" in error_lower or "validation" in error_lower:
            return "Validate input format before sending"
        return None

    def _extract_tags(
        self,
        failure_type: str,
        tool_name: Optional[str],
        context: Dict
    ) -> List[str]:
        """컨텍스트에서 태그 추출."""
        tags = [failure_type]
        if tool_name:
            tags.append(tool_name)
        context_str = str(context).lower()
        if "file" in context_str:
            tags.append("file_operation")
        if "http" in context_str or "url" in context_str:
            tags.append("network")
        if "database" in context_str or "sql" in context_str:
            tags.append("database")
        return tags

    def _find_similar_lesson(
        self,
        failure_type: str,
        tool_name: Optional[str],
        error_pattern: str
    ) -> Optional[Lesson]:
        """유사한 기존 교훈 검색."""
        conn = self._get_conn()
        try:
            query = """
                SELECT * FROM failure_lessons
                WHERE failure_type = ? AND error_pattern = ?
            """
            params = [failure_type, error_pattern]

            if tool_name:
                query += " AND tool_name = ?"
                params.append(tool_name)

            row = conn.execute(query, params).fetchone()
            return self._row_to_lesson(row) if row else None
        finally:
            self._close_conn(conn)

    def _reinforce_lesson(self, lesson_id: str):
        """기존 교훈 신뢰도 강화."""
        conn = self._get_conn()
        try:
            conn.execute("""
                UPDATE failure_lessons
                SET confidence = MIN(1.0, confidence + 0.05),
                    updated_at = ?
                WHERE lesson_id = ?
            """, (datetime.now().isoformat(), lesson_id))
            conn.commit()
        finally:
            self._close_conn(conn)

    def _save_lesson(self, lesson: Lesson):
        """교훈 저장."""
        conn = self._get_conn()
        try:
            now = datetime.now().isoformat()
            conn.execute("""
                INSERT INTO failure_lessons (
                    lesson_id, failure_id, task_id, failure_type, tool_name,
                    error_pattern, lesson_text, corrective_action, avoid_pattern,
                    confidence, tags, applicable_tools, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                lesson.lesson_id, lesson.failure_id, lesson.task_id,
                lesson.failure_type, lesson.tool_name, lesson.error_pattern,
                lesson.lesson_text, lesson.corrective_action, lesson.avoid_pattern,
                lesson.confidence,
                json.dumps(lesson.tags),
                json.dumps(lesson.applicable_tools),
                now, now
            ))
            conn.commit()
        finally:
            self._close_conn(conn)

    def _row_to_lesson(self, row) -> Lesson:
        """DB 행을 Lesson으로 변환."""
        return Lesson(
            lesson_id=row["lesson_id"],
            failure_id=row["failure_id"],
            task_id=row["task_id"],
            failure_type=row["failure_type"],
            tool_name=row["tool_name"],
            error_pattern=row["error_pattern"],
            lesson_text=row["lesson_text"],
            corrective_action=row["corrective_action"],
            avoid_pattern=row["avoid_pattern"],
            confidence=row["confidence"],
            apply_count=row["apply_count"],
            success_count=row["success_count"],
            tags=json.loads(row["tags"]) if row["tags"] else [],
            applicable_tools=json.loads(row["applicable_tools"]) if row["applicable_tools"] else []
        )
