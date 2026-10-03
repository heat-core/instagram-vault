"""Verified archive copy; source stays untouched until the user switches storage."""
import hashlib
import json
import os
import shutil
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from .. import database
from ..job_manager import manager


class StorageService:
    @staticmethod
    def copy_archive(job_id: str, cancel_event: threading.Event, destination_parent: str, activate: bool = False):
        source = database.DATA_DIR.resolve()
        parent = Path(destination_parent).resolve()
        if not parent.is_dir() or parent.is_relative_to(source):
            raise ValueError("Choose an existing folder outside the current archive")
        name = "Saved Archive" if activate else time.strftime("Saved Archive Backup %Y-%m-%d %H-%M-%S")
        destination = parent / name
        if destination.exists():
            raise ValueError("The destination archive already exists; choose another folder")
        stage = parent / f".saved-archive-stage-{uuid.uuid4().hex}"
        stage.mkdir()
        try:
            manager.update_progress(job_id, 0, 'Scanning archive files')
            files = []
            scanned = 0
            ignored = {database.DB_PATH.resolve()}
            for root, directories, names in os.walk(source, followlinks=False):
                if cancel_event.is_set():
                    raise RuntimeError("Archive copy cancelled")
                directories[:] = [name for name in directories if not (Path(root) / name).is_symlink()]
                for name in names:
                    path = Path(root) / name
                    scanned += 1
                    if (
                        path.is_symlink()
                        or path.resolve() in ignored
                        or path.suffix in {'.db-wal', '.db-shm', '.db-journal'}
                        or path.name.startswith(database.DB_PATH.name)
                    ):
                        continue
                    files.append(path)
                    if scanned % 250 == 0:
                        manager.update_progress(job_id, 1, f'Scanning archive: {scanned} files found')
            manager.update_progress(job_id, 4, f'Archive scan complete: {len(files)} files')
            inodes = {}
            manifest = []
            for number, src in enumerate(files, 1):
                if cancel_event.is_set():
                    raise RuntimeError("Archive copy cancelled")
                if not src.is_file():
                    continue
                relative = src.relative_to(source)
                target = stage / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                identity = (src.stat().st_dev, src.stat().st_ino)
                if identity in inodes:
                    try:
                        os.link(inodes[identity], target)
                    except OSError:
                        shutil.copy2(src, target)
                else:
                    shutil.copy2(src, target)
                    inodes[identity] = target
                if relative.parts[:2] == ('media', 'canonical_files'):
                    with target.open('rb') as handle:
                        digest = hashlib.file_digest(handle, 'sha256').hexdigest()
                    manifest.append({'path': relative.as_posix(), 'size': target.stat().st_size, 'sha256': digest})
                manager.update_progress(job_id, 4 + 81 * number / max(len(files), 1), f"Copying {number}/{len(files)} files")
            copied_db = stage / 'database' / 'library.db'
            copied_db.parent.mkdir(parents=True, exist_ok=True)
            source_db = database.get_db()
            backup_db = sqlite3.connect(copied_db)
            try:
                source_db.backup(backup_db)
                with backup_db:
                    rows = backup_db.execute("SELECT id, file_path FROM media_files").fetchall()
                    for media_id, old_path in rows:
                        resolved_old = database.resolve_media_path(old_path, base_dir=source)
                        try:
                            relative = resolved_old.relative_to(source)
                        except ValueError:
                            relative = Path(old_path)
                        if not (stage / relative).is_file():
                            raise ValueError("A recorded media file is missing; source archive needs repair")
                        backup_db.execute("UPDATE media_files SET file_path=? WHERE id=?", (str(destination / relative), media_id))
                if backup_db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('Database copy failed integrity check')
            finally:
                backup_db.close()
                source_db.close()
            for entry in manifest:
                target = stage / entry['path']
                with target.open('rb') as handle:
                    digest = hashlib.file_digest(handle, 'sha256').hexdigest()
                if target.stat().st_size != entry['size'] or digest != entry['sha256']:
                    raise ValueError('Copied media failed verification')
            (stage / 'backup-manifest.json').write_text(json.dumps({
                'created_at_utc': database.published_at(time.time()), 'files': manifest,
            }, ensure_ascii=False), encoding='utf-8')
            manager.update_progress(job_id, 95, 'Activating verified copy')
            stage.rename(destination)
            return {'destination': str(destination), 'files_verified': len(manifest), 'activated': activate}
        except Exception:
            if stage.is_dir() and stage.parent == parent:
                shutil.rmtree(stage)
            raise

    @staticmethod
    def migrate_archive(job_id: str, cancel_event: threading.Event, source_directory: str, destination_directory: str = None, activate: bool = True):
        source = Path(source_directory).resolve()
        if not source.is_dir():
            raise ValueError("Source archive directory does not exist")
        source_db_file = source / "database" / "library.db"
        if not source_db_file.is_file():
            raise ValueError("Source folder does not contain database/library.db")

        # Test source DB integrity
        src_conn = sqlite3.connect(str(source_db_file))
        try:
            check = src_conn.execute("PRAGMA integrity_check").fetchone()
            if not check or check[0] != 'ok':
                raise ValueError("Source database failed integrity check")
        finally:
            src_conn.close()

        target = Path(destination_directory).resolve() if destination_directory else database.DATA_DIR.resolve()
        if source == target:
            # Just rebase and verify!
            manager.update_progress(job_id, 50, "Rebasing media paths in-place")
            rebased = database.rebase_media_paths(target)
            return {'source': str(source), 'destination': str(target), 'rebased_paths': rebased, 'activated': activate}

        manager.update_progress(job_id, 10, "Preparing target directory")
        target.mkdir(parents=True, exist_ok=True)
        
        # Copy database
        target_db_file = target / "database" / "library.db"
        target_db_file.parent.mkdir(parents=True, exist_ok=True)
        
        if target_db_file.exists():
            backup_file = target / "database" / f"library.backup.{int(time.time())}.db"
            try:
                shutil.copy2(target_db_file, backup_file)
            except Exception:
                pass

        manager.update_progress(job_id, 20, "Copying database")
        shutil.copy2(source_db_file, target_db_file)
        
        # Copy session.enc if present
        source_session = source / "session.enc"
        if source_session.is_file():
            shutil.copy2(source_session, target / "session.enc")

        # Copy media/canonical_files
        source_media = source / "media" / "canonical_files"
        target_media = target / "media" / "canonical_files"
        target_media.mkdir(parents=True, exist_ok=True)
        
        migrated_files = 0
        if source_media.is_dir():
            files_to_copy = []
            for root, _, names in os.walk(source_media):
                for name in names:
                    files_to_copy.append(Path(root) / name)
            
            total = len(files_to_copy)
            for i, file_path in enumerate(files_to_copy, 1):
                if cancel_event.is_set():
                    raise RuntimeError("Migration cancelled by user")
                rel = file_path.relative_to(source_media)
                dest = target_media / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                if not dest.exists() or dest.stat().st_size != file_path.stat().st_size:
                    try:
                        os.link(file_path, dest)
                    except OSError:
                        shutil.copy2(file_path, dest)
                migrated_files += 1
                if i % 50 == 0 or i == total:
                    manager.update_progress(job_id, 30 + int(50 * i / max(total, 1)), f"Migrated {i}/{total} media files")

        # Copy categories folder if present
        source_cat = source / "categories"
        target_cat = target / "categories"
        if source_cat.is_dir():
            manager.update_progress(job_id, 85, "Migrating organized categories")
            for root, _, names in os.walk(source_cat):
                for name in names:
                    cat_file = Path(root) / name
                    rel = cat_file.relative_to(source_cat)
                    dest = target_cat / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    if not dest.exists():
                        try:
                            os.link(cat_file, dest)
                        except OSError:
                            shutil.copy2(cat_file, dest)

        # Rebase media_files file_path in target database
        manager.update_progress(job_id, 92, "Updating media paths in database")
        target_conn = sqlite3.connect(str(target_db_file))
        rebased = 0
        try:
            target_conn.row_factory = sqlite3.Row
            rows = target_conn.execute("SELECT id, post_pk, file_path, media_index FROM media_files").fetchall()
            updates = []
            for row in rows:
                old_path = row['file_path']
                fname = Path(old_path).name
                new_path = target_media / row['post_pk'] / fname
                if new_path.is_file():
                    updates.append((str(new_path), row['id']))
                else:
                    post_dir = target_media / row['post_pk']
                    if post_dir.is_dir():
                        candidates = list(post_dir.glob(f"*_{row['post_pk']}_{row['media_index'] + 1}.*"))
                        if candidates and candidates[0].is_file():
                            updates.append((str(candidates[0]), row['id']))
            if updates:
                with target_conn:
                    target_conn.executemany("UPDATE media_files SET file_path = ? WHERE id = ?", updates)
                rebased = len(updates)
            
            check = target_conn.execute("PRAGMA integrity_check").fetchone()
            if not check or check[0] != 'ok':
                raise ValueError("Migrated database failed integrity check")
        finally:
            target_conn.close()

        manager.update_progress(job_id, 100, f"Migration complete: {migrated_files} files, {rebased} paths updated")
        return {
            'source': str(source),
            'destination': str(target),
            'migrated_files': migrated_files,
            'rebased_paths': rebased,
            'activated': activate
        }
