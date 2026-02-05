"""
Checkpoint Manager — REZE v6.0 SOVEREIGN
진화 행동 전후 스냅샷 및 롤백

모든 진화 행동은 되돌릴 수 있어야 합니다.
코드 변경 전 파일 백업 + DB 스냅샷을 생성합니다.
"""

import json
import shutil
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List

logger = logging.getLogger("reze.evolve.checkpoint")

REZE_ROOT = Path.home() / "reze-agent"
CHECKPOINT_DIR = REZE_ROOT / "data" / "checkpoints"


class CheckpointManager:
    """
    체크포인트 관리자.
    파일 백업 + DB 스냅샷 생성 및 롤백.
    """

    def __init__(self, ssot):
        """
        Args:
            ssot: SSOT 인스턴스 (conn 속성 필요)
        """
        self.ssot = ssot
        self.conn = ssot.conn if hasattr(ssot, 'conn') else ssot
        CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)

    def create(
        self,
        module: str,
        action: str,
        files: List[str] = None,
        tables: List[str] = None,
        metadata: dict = None
    ) -> str:
        """
        체크포인트 생성.

        Args:
            module: 진화 모듈명
            action: 수행할 액션 설명
            files: 백업할 파일 경로 리스트 (상대 경로)
            tables: 스냅샷할 DB 테이블 리스트
            metadata: 추가 메타데이터

        Returns:
            checkpoint_id
        """
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        cp_id = f"cp_{module}_{ts}"
        cp_dir = CHECKPOINT_DIR / cp_id
        cp_dir.mkdir(parents=True, exist_ok=True)

        backed_files = []
        db_snapshot = {}

        # 1. 파일 백업
        if files:
            for f in files:
                src = REZE_ROOT / f
                if src.exists():
                    # 디렉토리 구조 유지
                    dst = cp_dir / f
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                    backed_files.append(f)
                    logger.debug("Checkpoint: backed up %s", f)

        # 2. DB 테이블 스냅샷
        if tables:
            for table in tables:
                try:
                    rows = self.conn.execute(
                        f"SELECT * FROM {table} ORDER BY rowid DESC LIMIT 100"
                    ).fetchall()
                    # Row 객체를 dict로 변환
                    db_snapshot[table] = [
                        dict(r) if hasattr(r, 'keys') else list(r)
                        for r in rows
                    ]
                except Exception as e:
                    logger.warning("Failed to snapshot table %s: %s", table, e)

        # 3. 메타데이터 저장
        meta = {
            "checkpoint_id": cp_id,
            "module": module,
            "action": action,
            "files_backed": backed_files,
            "tables_snapshotted": list(db_snapshot.keys()),
            "metadata": metadata or {},
            "created_at": datetime.utcnow().isoformat(),
        }
        (cp_dir / "meta.json").write_text(
            json.dumps(meta, indent=2, default=str),
            encoding="utf-8"
        )

        # DB 스냅샷 저장
        if db_snapshot:
            (cp_dir / "db_snapshot.json").write_text(
                json.dumps(db_snapshot, indent=2, default=str),
                encoding="utf-8"
            )

        # 4. DB에 기록
        try:
            self.conn.execute("""
                INSERT INTO checkpoints
                (checkpoint_id, module, action, files_backed, created_at, rolled_back)
                VALUES (?, ?, ?, ?, ?, 0)
            """, (
                cp_id, module, action,
                json.dumps(backed_files),
                datetime.utcnow().isoformat()
            ))
            self.conn.commit()
        except Exception as e:
            logger.error("Failed to record checkpoint: %s", e)

        logger.info(
            "Checkpoint: created %s (files=%d, tables=%d)",
            cp_id, len(backed_files), len(db_snapshot)
        )

        return cp_id

    def rollback(self, checkpoint_id: str) -> bool:
        """
        체크포인트로 롤백.

        Args:
            checkpoint_id: 롤백할 체크포인트 ID

        Returns:
            True if 성공
        """
        cp_dir = CHECKPOINT_DIR / checkpoint_id

        if not cp_dir.exists():
            logger.error("Checkpoint not found: %s", checkpoint_id)
            return False

        meta_file = cp_dir / "meta.json"
        if not meta_file.exists():
            logger.error("Checkpoint meta not found: %s", checkpoint_id)
            return False

        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error("Failed to read checkpoint meta: %s", e)
            return False

        # 1. 파일 복원
        for f in meta.get("files_backed", []):
            backup = cp_dir / f
            target = REZE_ROOT / f

            if backup.exists():
                # 현재 파일 백업 (롤백의 롤백 가능하게)
                if target.exists():
                    pre_rollback = target.with_suffix(target.suffix + ".pre_rollback")
                    shutil.copy2(target, pre_rollback)

                # 복원
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup, target)
                logger.info("Checkpoint: restored %s", f)

        # 2. DB 롤백 기록
        try:
            self.conn.execute("""
                UPDATE checkpoints
                SET rolled_back = 1, rolled_back_at = ?
                WHERE checkpoint_id = ?
            """, (datetime.utcnow().isoformat(), checkpoint_id))
            self.conn.commit()
        except Exception as e:
            logger.error("Failed to update rollback status: %s", e)

        logger.info("Checkpoint: rolled back to %s", checkpoint_id)
        return True

    def get_checkpoint_info(self, checkpoint_id: str) -> Optional[dict]:
        """체크포인트 정보 조회"""
        cp_dir = CHECKPOINT_DIR / checkpoint_id
        meta_file = cp_dir / "meta.json"

        if meta_file.exists():
            try:
                return json.loads(meta_file.read_text(encoding="utf-8"))
            except:
                pass
        return None

    def list_checkpoints(
        self,
        module: str = None,
        limit: int = 20
    ) -> List[dict]:
        """체크포인트 목록 조회"""
        try:
            if module:
                rows = self.conn.execute("""
                    SELECT checkpoint_id, module, action, files_backed,
                           created_at, rolled_back, rolled_back_at
                    FROM checkpoints
                    WHERE module = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (module, limit)).fetchall()
            else:
                rows = self.conn.execute("""
                    SELECT checkpoint_id, module, action, files_backed,
                           created_at, rolled_back, rolled_back_at
                    FROM checkpoints
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (limit,)).fetchall()

            return [dict(row) for row in rows]
        except Exception as e:
            logger.error("Failed to list checkpoints: %s", e)
            return []

    def cleanup_old(self, keep_days: int = 7) -> int:
        """
        오래된 체크포인트 정리.

        Args:
            keep_days: 보관 기간 (기본 7일)

        Returns:
            삭제된 체크포인트 수
        """
        cutoff = datetime.utcnow() - timedelta(days=keep_days)
        deleted_count = 0

        for cp_dir in CHECKPOINT_DIR.iterdir():
            if not cp_dir.is_dir():
                continue

            meta_file = cp_dir / "meta.json"
            if not meta_file.exists():
                continue

            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                created_str = meta.get("created_at", "")
                if created_str:
                    created = datetime.fromisoformat(created_str)
                    if created < cutoff:
                        # 디렉토리 삭제
                        shutil.rmtree(cp_dir, ignore_errors=True)
                        deleted_count += 1
                        logger.debug("Checkpoint: cleaned up %s", cp_dir.name)
            except Exception as e:
                logger.warning("Failed to check checkpoint age: %s", e)

        if deleted_count > 0:
            logger.info("Checkpoint: cleaned up %d old checkpoints", deleted_count)

        return deleted_count

    def get_latest_for_module(self, module: str) -> Optional[str]:
        """모듈의 가장 최근 체크포인트 ID 반환"""
        try:
            row = self.conn.execute("""
                SELECT checkpoint_id FROM checkpoints
                WHERE module = ? AND rolled_back = 0
                ORDER BY created_at DESC
                LIMIT 1
            """, (module,)).fetchone()

            if row:
                return row[0]
        except Exception as e:
            logger.error("Failed to get latest checkpoint: %s", e)
        return None

    def diff_from_checkpoint(
        self,
        checkpoint_id: str,
        file_path: str
    ) -> Optional[str]:
        """
        체크포인트와 현재 파일의 차이 확인.

        Returns:
            diff 문자열 또는 None
        """
        cp_dir = CHECKPOINT_DIR / checkpoint_id
        backup = cp_dir / file_path
        current = REZE_ROOT / file_path

        if not backup.exists():
            return None

        if not current.exists():
            return f"File deleted: {file_path}"

        try:
            backup_content = backup.read_text(encoding="utf-8")
            current_content = current.read_text(encoding="utf-8")

            if backup_content == current_content:
                return "No changes"

            # 간단한 라인 수 비교
            backup_lines = len(backup_content.splitlines())
            current_lines = len(current_content.splitlines())

            return (
                f"File changed: {file_path}\n"
                f"  Backup: {backup_lines} lines\n"
                f"  Current: {current_lines} lines\n"
                f"  Delta: {current_lines - backup_lines:+d} lines"
            )

        except Exception as e:
            return f"Error comparing: {e}"
