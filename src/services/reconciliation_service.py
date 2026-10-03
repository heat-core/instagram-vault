"""Reconciliation Engine: ensures consistency between SQLite database and NTFS filesystem."""
import os
import re
import json
import time
import hashlib
from pathlib import Path
from typing import Dict, Any, List, Optional
import threading

from .. import database
from ..job_manager import manager
from .download_service import DownloadService

class ReconciliationService:
    @classmethod
    def diagnose_archive(cls, cancel_event: Optional[threading.Event] = None,
                         progress_callback=None) -> Dict[str, Any]:
        """
        Scans both database and filesystem to identify discrepancies:
        - Missing files: in SQLite media_files but absent from disk
        - Orphaned files: files present in media/canonical_files but not registered in SQLite
        - Orphaned posts: post folders in canonical_files with source.json but not in SQLite posts
        - Corrupted files: files whose SHA256 does not match recorded SHA256 in DB
        - Broken taxonomy links: files in category/format/creator/year folders with broken targets
        """
        conn = database.get_db()
        base_dir = database.DATA_DIR.resolve()
        canonical_root = base_dir / "media" / "canonical_files"
        
        missing_media = []
        corrupted_files = []
        orphaned_files = []
        orphaned_posts = []
        broken_links = []
        
        try:
            # 1. Inspect DB media_files vs disk
            db_media_rows = conn.execute("SELECT id, post_pk, file_path, media_index, sha256 FROM media_files").fetchall()
            total_db_media = len(db_media_rows)
            
            for idx, row in enumerate(db_media_rows, 1):
                if cancel_event and cancel_event.is_set():
                    break
                disk_path = database.resolve_media_path(row['file_path'])
                if not disk_path.is_file():
                    missing_media.append({
                        "id": row['id'],
                        "post_pk": row['post_pk'],
                        "file_path": row['file_path'],
                        "media_index": row['media_index']
                    })
                else:
                    recorded_hash = row['sha256']
                    if recorded_hash:
                        try:
                            with disk_path.open('rb') as f:
                                actual_hash = hashlib.file_digest(f, 'sha256').hexdigest()
                            if actual_hash != recorded_hash:
                                corrupted_files.append({
                                    "post_pk": row['post_pk'],
                                    "file_path": row['file_path'],
                                    "expected_sha256": recorded_hash,
                                    "actual_sha256": actual_hash
                                })
                        except Exception:
                            pass
                if progress_callback and idx % 200 == 0:
                    progress_callback(10 * idx / max(total_db_media, 1), f"Checked {idx}/{total_db_media} DB media files")

            # 2. Inspect filesystem canonical_files vs DB
            total_db_posts_count = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
            existing_pks = {r[0] for r in conn.execute("SELECT pk FROM posts").fetchall()}
            existing_media_keys = {(r['post_pk'], Path(r['file_path']).name) for r in db_media_rows}
            
            total_disk_files = 0
            if canonical_root.is_dir():
                pk_folders = [p for p in canonical_root.iterdir() if p.is_dir()]
                for idx, post_folder in enumerate(pk_folders, 1):
                    if cancel_event and cancel_event.is_set():
                        break
                    post_pk = post_folder.name
                    has_source_json = (post_folder / "source.json").is_file()
                    
                    if post_pk not in existing_pks:
                        orphaned_posts.append({
                            "post_pk": post_pk,
                            "folder": str(post_folder),
                            "has_source_json": has_source_json
                        })
                    
                    for item in post_folder.iterdir():
                        if not item.is_file() or item.name in {"source.json"} or item.suffix in {".part", ".previous"}:
                            continue
                        if item.name.endswith(".poster.jpg"):
                            continue
                        if item.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov"}:
                            total_disk_files += 1
                            if (post_pk, item.name) not in existing_media_keys:
                                orphaned_files.append({
                                    "post_pk": post_pk,
                                    "file_path": str(item),
                                    "filename": item.name
                                })
                    if progress_callback and idx % 100 == 0:
                        progress_callback(10 + 20 * idx / max(len(pk_folders), 1), f"Scanned {idx}/{len(pk_folders)} canonical folders")

            # 3. Check taxonomy hardlinks / files
            taxonomy_roots = [base_dir / axis for axis in ("categories", "by-creator", "by-format", "by-year")]
            for tax_root in taxonomy_roots:
                if not tax_root.is_dir():
                    continue
                for root, _, names in os.walk(tax_root):
                    if cancel_event and cancel_event.is_set():
                        break
                    for name in names:
                        if name == "info.md":
                            continue
                        tax_file = Path(root) / name
                        if not tax_file.exists():
                            broken_links.append(str(tax_file))

        finally:
            conn.close()

        healthy = not (missing_media or corrupted_files or orphaned_files or orphaned_posts or broken_links)
        return {
            "healthy": healthy,
            "total_db_posts": total_db_posts_count,
            "total_db_media_files": total_db_media,
            "total_disk_canonical_files": total_disk_files,
            "missing_media_count": len(missing_media),
            "missing_media": missing_media[:100],
            "orphaned_files_count": len(orphaned_files),
            "orphaned_files": orphaned_files[:100],
            "orphaned_posts_count": len(orphaned_posts),
            "orphaned_posts": orphaned_posts[:100],
            "corrupted_files_count": len(corrupted_files),
            "corrupted_files": corrupted_files[:100],
            "broken_links_count": len(broken_links),
            "broken_links": broken_links[:100]
        }

    @classmethod
    def run_reconciliation(cls, job_id: str, cancel_event: threading.Event, auto_repair: bool = True) -> Dict[str, Any]:
        """
        Executes a full reconciliation job with live progress reporting and automatic repair.
        """
        manager.update_progress(job_id, 2, "Diagnosing archive consistency...")
        
        def update_scan(pct, msg):
            manager.update_progress(job_id, pct, msg)
            
        report = cls.diagnose_archive(cancel_event=cancel_event, progress_callback=update_scan)
        if cancel_event.is_set():
            return {"cancelled": True, "report": report}
            
        manager.update_progress(job_id, 35, f"Diagnosis complete. Issues: {report['missing_media_count']} missing, {report['orphaned_files_count']} orphaned files, {report['orphaned_posts_count']} orphaned posts.")
        
        repairs = {
            "posts_recovered": 0,
            "media_files_registered": 0,
            "missing_status_updated": 0,
            "broken_links_removed": 0,
            "fts_synced": False
        }
        
        if not auto_repair:
            manager.update_progress(job_id, 100, "Reconciliation dry run complete.")
            return {"repaired": False, "report": report, "repairs": repairs}
            
        conn = database.get_db()
        base_dir = database.DATA_DIR.resolve()
        
        try:
            # 1. Recover orphaned posts from source.json
            canonical_root = base_dir / "media" / "canonical_files"
            orphans = report.get("orphaned_posts", [])
            for post_item in orphans:
                if cancel_event.is_set():
                    break
                pk = post_item["post_pk"]
                source_json_file = Path(post_item["folder"]) / "source.json"
                if source_json_file.is_file():
                    try:
                        data = json.loads(source_json_file.read_text(encoding='utf-8'))
                        with conn:
                            conn.execute("""
                            INSERT OR IGNORE INTO posts (pk, shortcode, original_url, media_type, owner_username, owner_id,
                                                        caption, original_hashtags, taken_at, status, status_updated_at, retry_count)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'DOWNLOAD_OK', ?, 0)
                            """, (
                                pk,
                                data.get("shortcode") or pk,
                                data.get("source_url") or data.get("original_url"),
                                data.get("media_type", 1),
                                data.get("owner_username") or data.get("creator") or "instagram",
                                data.get("owner_id"),
                                database.fix_mojibake_text(data.get("caption", "")),
                                database.fix_mojibake_text(data.get("hashtags", "")),
                                str(data.get("taken_at") or int(time.time())),
                                int(time.time())
                            ))
                        repairs["posts_recovered"] += 1
                    except Exception as e:
                        manager.log(job_id, "WARN", f"Failed restoring post {pk} from source.json: {e}")

            manager.update_progress(job_id, 55, "Registering orphaned media files...")
            
            # 2. Register orphaned media files into SQLite
            all_orphaned = report.get("orphaned_files", [])
            for file_item in all_orphaned:
                if cancel_event.is_set():
                    break
                pk = file_item["post_pk"]
                file_path = Path(file_item["file_path"])
                if not file_path.is_file():
                    continue
                # Determine media index from filename (e.g. user_pk_1.jpg -> index 0)
                match = re.search(r'_(\d+)\.[^.]+$', file_path.name)
                media_index = (int(match.group(1)) - 1) if match else 0
                if media_index < 0:
                    media_index = 0
                
                # Check metrics and sha256
                width, height, size, duration, bitrate = DownloadService.media_metrics(file_path)
                sha256 = None
                try:
                    with file_path.open('rb') as f:
                        sha256 = hashlib.file_digest(f, 'sha256').hexdigest()
                except Exception:
                    pass
                
                rel_path = database.to_relative_media_path(file_path)
                with conn:
                    conn.execute("""
                    INSERT INTO media_files (post_pk, file_path, media_index, width, height, size_bytes, duration_seconds, bitrate_bps, sha256)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(post_pk, media_index) DO UPDATE SET
                        file_path=excluded.file_path, width=excluded.width, height=excluded.height,
                        size_bytes=excluded.size_bytes, duration_seconds=excluded.duration_seconds,
                        bitrate_bps=excluded.bitrate_bps, sha256=excluded.sha256
                    """, (pk, rel_path, media_index, width, height, size, duration, bitrate, sha256))
                repairs["media_files_registered"] += 1

            manager.update_progress(job_id, 75, "Updating status for missing items...")
            
            # 3. Mark posts with missing media files
            missing_items = report.get("missing_media", [])
            missing_pks = {item["post_pk"] for item in missing_items}
            for pk in missing_pks:
                if cancel_event.is_set():
                    break
                row = conn.execute("SELECT status FROM posts WHERE pk = ?", (pk,)).fetchone()
                if row and row['status'] in {'DOWNLOAD_OK', 'ORGANIZED', 'APPROVED'}:
                    database.mark_media_missing(pk, row['status'])
                    repairs["missing_status_updated"] += 1
            
            # 4. Remove broken hardlinks if any
            for broken in report.get("broken_links", []):
                try:
                    p = Path(broken)
                    if p.is_symlink() or not p.exists():
                        p.unlink(missing_ok=True)
                        repairs["broken_links_removed"] += 1
                except Exception:
                    pass

            manager.update_progress(job_id, 90, "Synchronizing search index...")
            database.sync_fts_index()
            repairs["fts_synced"] = True

        finally:
            conn.close()

        manager.update_progress(job_id, 100, "Reconciliation and repair completed successfully.")
        return {
            "repaired": True,
            "initial_report": report,
            "repairs": repairs
        }

    @classmethod
    def rebuild_library_from_disk(cls, archive_dir: Optional[Path] = None,
                                  cancel_event: Optional[threading.Event] = None,
                                  progress_callback=None) -> Dict[str, Any]:
        """
        Disaster Recovery: Reconstructs SQLite database completely from canonical disk files:
        Iterates over media/canonical_files/*/, extracts metadata from source.json,
        indexes all media files, computes SHA256 hashes and dimensions,
        and regenerates the FTS5 search index.
        """
        if archive_dir is None:
            archive_dir = database.DATA_DIR.resolve()
        else:
            archive_dir = Path(archive_dir).resolve()

        canonical_root = archive_dir / "media" / "canonical_files"
        if not canonical_root.is_dir():
            return {"error": f"Canonical directory not found: {canonical_root}", "rebuilt_posts": 0, "rebuilt_media": 0}

        database.init_db()
        conn = database.get_db()

        pk_folders = [p for p in canonical_root.iterdir() if p.is_dir()]
        total_folders = len(pk_folders)

        posts_added = 0
        media_added = 0
        source_jsons_found = 0

        try:
            for idx, post_folder in enumerate(pk_folders, 1):
                if cancel_event and cancel_event.is_set():
                    break

                pk = post_folder.name
                source_json_file = post_folder / "source.json"
                metadata = {}
                if source_json_file.is_file():
                    try:
                        metadata = json.loads(source_json_file.read_text(encoding='utf-8'))
                        source_jsons_found += 1
                    except Exception:
                        pass

                # Extract or synthesize post fields
                shortcode = metadata.get("shortcode") or pk
                orig_url = metadata.get("source_url") or metadata.get("original_url") or f"https://www.instagram.com/p/{shortcode}/"
                owner_username = metadata.get("owner_username") or metadata.get("creator") or "instagram"
                owner_id = metadata.get("owner_id")
                caption = database.fix_mojibake_text(metadata.get("caption", ""))
                hashtags = database.fix_mojibake_text(metadata.get("hashtags") or metadata.get("original_hashtags", ""))
                taken_at = str(metadata.get("taken_at") or int(time.time()))
                ai_summary = database.fix_mojibake_text(metadata.get("ai_summary", ""))
                ai_tags = database.fix_mojibake_text(metadata.get("tags") or metadata.get("ai_tags", ""))
                ai_category = metadata.get("category") or metadata.get("ai_category")
                raw_cats = metadata.get("categories") or metadata.get("ai_categories")
                ai_categories = json.dumps(raw_cats) if isinstance(raw_cats, list) else (raw_cats or "[]")
                ai_confidence = metadata.get("ai_confidence") or ("HIGH" if ai_summary else None)
                status = "ORGANIZED" if ai_category else ("DOWNLOAD_OK" if metadata else "DISCOVERED")
                media_type = metadata.get("media_type", 1)

                # Scan media files in folder
                valid_files = []
                for item in post_folder.iterdir():
                    if not item.is_file() or item.name in {"source.json"} or item.suffix in {".part", ".previous", ".tmp"}:
                        continue
                    if item.name.endswith(".poster.jpg"):
                        continue
                    if item.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov"}:
                        valid_files.append(item)

                if len(valid_files) > 1:
                    media_type = 8
                elif len(valid_files) == 1 and valid_files[0].suffix.lower() in {".mp4", ".mov"}:
                    media_type = 2
                elif not valid_files and metadata.get("media_type"):
                    media_type = metadata["media_type"]

                now = int(time.time())
                with conn:
                    conn.execute("""
                    INSERT INTO posts (pk, shortcode, original_url, media_type, owner_username, owner_id,
                                        caption, original_hashtags, taken_at, status, status_updated_at,
                                        ai_summary, ai_tags, ai_category, ai_categories, ai_confidence,
                                        retry_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                    ON CONFLICT(pk) DO UPDATE SET
                        shortcode=COALESCE(excluded.shortcode, posts.shortcode),
                        original_url=COALESCE(excluded.original_url, posts.original_url),
                        media_type=COALESCE(excluded.media_type, posts.media_type),
                        owner_username=COALESCE(excluded.owner_username, posts.owner_username),
                        owner_id=COALESCE(excluded.owner_id, posts.owner_id),
                        caption=COALESCE(excluded.caption, posts.caption),
                        original_hashtags=COALESCE(excluded.original_hashtags, posts.original_hashtags),
                        taken_at=COALESCE(excluded.taken_at, posts.taken_at),
                        ai_summary=COALESCE(excluded.ai_summary, posts.ai_summary),
                        ai_tags=COALESCE(excluded.ai_tags, posts.ai_tags),
                        ai_category=COALESCE(excluded.ai_category, posts.ai_category),
                        ai_categories=COALESCE(excluded.ai_categories, posts.ai_categories),
                        ai_confidence=COALESCE(excluded.ai_confidence, posts.ai_confidence)
                    """, (pk, shortcode, orig_url, media_type, owner_username, owner_id,
                          caption, hashtags, taken_at, status, now,
                          ai_summary, ai_tags, ai_category, ai_categories, ai_confidence))
                posts_added += 1

                # Sort files to assign media_index
                valid_files.sort(key=lambda p: p.name)
                for f_idx, f_path in enumerate(valid_files):
                    match = re.search(r'_(\d+)\.[^.]+$', f_path.name)
                    m_index = (int(match.group(1)) - 1) if match else f_idx
                    if m_index < 0:
                        m_index = f_idx

                    width, height, size, duration, bitrate = DownloadService.media_metrics(f_path)
                    sha256 = None
                    try:
                        with f_path.open('rb') as f:
                            sha256 = hashlib.file_digest(f, 'sha256').hexdigest()
                    except Exception:
                        pass

                    rel_path = database.to_relative_media_path(f_path, base_dir=archive_dir)
                    with conn:
                        conn.execute("""
                        INSERT INTO media_files (post_pk, file_path, media_index, width, height, size_bytes, duration_seconds, bitrate_bps, sha256)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(post_pk, media_index) DO UPDATE SET
                            file_path=excluded.file_path, width=excluded.width, height=excluded.height,
                            size_bytes=excluded.size_bytes, duration_seconds=excluded.duration_seconds,
                            bitrate_bps=excluded.bitrate_bps, sha256=excluded.sha256
                        """, (pk, rel_path, m_index, width, height, size, duration, bitrate, sha256))
                    media_added += 1

                if progress_callback and (idx % 25 == 0 or idx == total_folders):
                    progress_callback(10.0 + 80.0 * idx / max(total_folders, 1), f"Processed {idx}/{total_folders} post folders")

            if progress_callback:
                progress_callback(95.0, "Rebuilding FTS search index...")
            database.sync_fts_index()

        finally:
            conn.close()

        return {
            "success": True,
            "total_folders": total_folders,
            "posts_recovered": posts_added,
            "media_files_recovered": media_added,
            "source_jsons_found": source_jsons_found
        }

    @classmethod
    def run_rebuild_job(cls, job_id: str, cancel_event: threading.Event, archive_dir: Optional[str] = None) -> Dict[str, Any]:
        manager.update_progress(job_id, 2, "Starting disaster recovery library rebuild...")
        def update_prog(pct, msg):
            manager.update_progress(job_id, pct, msg)
        target_dir = Path(archive_dir) if archive_dir else None
        res = cls.rebuild_library_from_disk(archive_dir=target_dir, cancel_event=cancel_event, progress_callback=update_prog)
        if cancel_event.is_set():
            manager.update_progress(job_id, 100, "Rebuild job cancelled.")
            return {"cancelled": True, **res}
        manager.update_progress(job_id, 100, f"Library rebuild complete: {res.get('posts_recovered', 0)} posts restored.")
        return res

