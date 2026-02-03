"""
REZE Accelerated Learning Engine.
교훈을 75배 빠르게 축적. 패턴 자동 추출.
"""

import json
from datetime import datetime, timedelta

import logging
logger = logging.getLogger("REZE.learning")


class AcceleratedLearning:

    def __init__(self, call_llm_fn, store_signal_fn, get_db_fn):
        self.call_llm = call_llm_fn
        self.store_signal = store_signal_fn
        self.get_db = get_db_fn

    async def schedule_verification(self, discovery_id: int, discovery_type: str):
        """
        발견 유형에 따라 검증 시간을 설정.
        instant(5분) / fast(6시간) / daily(24시간) / weekly(7일)
        """
        from reze_permissions import get_verification_delay

        delay = get_verification_delay(discovery_type)
        speed = delay["speed"]

        if "verify_after_minutes" in delay:
            minutes = delay["verify_after_minutes"]
        elif "verify_after_hours" in delay:
            minutes = delay["verify_after_hours"] * 60
        elif "verify_after_days" in delay:
            minutes = delay["verify_after_days"] * 24 * 60
        else:
            minutes = 6 * 60  # 기본 6시간

        verify_at = datetime.now() + timedelta(minutes=minutes)

        db = self.get_db()
        db.execute(
            "UPDATE discoveries SET verification_date=?, status='acted' WHERE id=?",
            (verify_at.strftime("%Y-%m-%d %H:%M:%S"), discovery_id)
        )
        db.commit()

        logger.info(f"Discovery #{discovery_id} verify: {speed} ({minutes}min)")
        return {"speed": speed, "verify_at": verify_at.isoformat()}

    async def verify_due(self):
        """검증 시간이 된 발견들을 모두 검증."""
        db = self.get_db()

        due = db.execute(
            """SELECT id, discovery_type, detail, interpretation,
                      actions_taken, created_at
               FROM discoveries
               WHERE status = 'acted'
               AND verification_date <= datetime('now')
               AND verification_result IS NULL"""
        ).fetchall()

        for row in due:
            disc = {
                "id": row[0], "type": row[1], "detail": row[2],
                "interpretation": row[3], "actions": row[4], "created_at": row[5]
            }
            try:
                await self._verify_one(disc)
            except Exception as e:
                logger.error(f"Verify #{disc['id']} failed: {e}")

    async def _verify_one(self, disc: dict) -> dict:
        """하나의 발견에 대해 검증 실행."""
        elapsed = self._time_since(disc.get("created_at", ""))

        prompt = f"""
REZE 학습 검증.

발견: {disc['detail']}
해석: {disc.get('interpretation', '')}
행동: {disc.get('actions', '[]')}
경과: {elapsed}

1. 행동이 효과적이었는가?
2. 교훈은?
3. 다음에 비슷한 상황이면?

JSON:
{{"effective": true/false, "lesson": "한 줄 교훈", "next_time": "다음 행동", "confidence": 0.0-1.0}}
JSON만 반환.
"""
        result = await self.call_llm(prompt, role="reasoning")

        # JSON 파싱
        text = result.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]

        try:
            verification = json.loads(text.strip())
        except:
            verification = {"effective": None, "lesson": result[:200], "confidence": 0.3}

        # SSOT 업데이트
        db = self.get_db()
        db.execute(
            """UPDATE discoveries
               SET verification_result=?, status='verified', updated_at=datetime('now')
               WHERE id=?""",
            (json.dumps(verification, ensure_ascii=False), disc["id"])
        )
        db.commit()

        # 교훈 저장
        if verification.get("lesson"):
            self.store_signal("lesson_learned", json.dumps({
                "discovery_id": disc["id"],
                "lesson": verification["lesson"],
                "next_time": verification.get("next_time", ""),
                "confidence": verification.get("confidence", 0.5),
                "effective": verification.get("effective")
            }))

        logger.info(f"Verified #{disc['id']}: effective={verification.get('effective')}")
        return verification

    async def meta_learn(self) -> dict:
        """
        교훈에서 패턴 추출 -> 원칙 생성.
        교훈 30개 이상이면 실행.
        """
        from reze_permissions import META_LEARNING_THRESHOLD

        db = self.get_db()

        lessons = db.execute(
            """SELECT data FROM signals
               WHERE kind = 'lesson_learned'
               AND created_at > datetime('now', '-30 days')
               ORDER BY created_at DESC"""
        ).fetchall()

        lesson_list = []
        for row in lessons:
            try:
                lesson_list.append(json.loads(row[0]))
            except:
                pass

        if len(lesson_list) < META_LEARNING_THRESHOLD:
            logger.info(f"Meta-learn: {len(lesson_list)}/{META_LEARNING_THRESHOLD} (not enough)")
            return {"skipped": True, "count": len(lesson_list)}

        prompt = f"""
REZE 메타학습. 최근 교훈 {len(lesson_list)}개를 분석하라.

교훈:
{json.dumps(lesson_list, ensure_ascii=False, indent=2)[:6000]}

분석:
1. 반복되는 성공 패턴 (이렇게 하면 잘 된다)
2. 반복되는 실패 패턴 (이렇게 하면 안 된다)
3. 일반화 가능한 원칙 (항상 적용)
4. 프로세스 변경 제안
5. 새 규칙 제안

JSON:
{{
    "success_patterns": ["패턴"],
    "failure_patterns": ["패턴"],
    "principles": ["원칙"],
    "process_changes": [{{"what": "설명", "priority": 1-5, "is_auto": true}}],
    "new_rules": ["규칙"],
    "stats": {{"total": {len(lesson_list)}, "effective_rate": "비율"}}
}}
JSON만 반환.
"""
        result = await self.call_llm(prompt, role="reasoning")

        # JSON 파싱
        text = result.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]

        try:
            meta = json.loads(text.strip())
        except:
            meta = {"raw": result[:500]}

        # 패턴/원칙 저장
        self.store_signal("meta_learning", json.dumps({
            "lessons_analyzed": len(lesson_list),
            "patterns": len(meta.get("success_patterns", [])) + len(meta.get("failure_patterns", [])),
            "principles": meta.get("principles", []),
            "new_rules": meta.get("new_rules", []),
        }))

        # 자동 프로세스 변경은 태스크로
        for change in meta.get("process_changes", []):
            if change.get("is_auto", True):
                self.store_signal("meta_task", json.dumps({
                    "description": f"[메타학습] {change['what']}",
                    "priority": change.get("priority", 3)
                }))

        logger.info(f"Meta-learn: {len(meta.get('principles', []))} principles from {len(lesson_list)} lessons")
        return meta

    def _time_since(self, created_at: str) -> str:
        try:
            created = datetime.fromisoformat(created_at.replace(" ", "T"))
            diff = datetime.now() - created
            if diff.total_seconds() < 3600:
                return f"{int(diff.total_seconds() / 60)}분"
            elif diff.total_seconds() < 86400:
                return f"{int(diff.total_seconds() / 3600)}시간"
            return f"{diff.days}일"
        except:
            return "unknown"
