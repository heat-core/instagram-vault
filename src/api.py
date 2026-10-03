from fastapi import FastAPI, BackgroundTasks, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, Literal
import os
import importlib.util
import json
import secrets
import shutil
import time
import uuid
import re
import base64
import binascii
from datetime import date, datetime, time as dt_time, timezone
from pathlib import Path
from .job_manager import manager
from .services.discovery_service import DiscoveryService, SESSION_FILE
from .services.download_service import DownloadService, safe_error_detail
from .services.ai_service import AIService
from .services.taxonomy_service import TaxonomyService
from .services.storage_service import StorageService
from .services.reconciliation_service import ReconciliationService
from .services.export_service import preview as preview_export, run_import, validate_export_directory
from . import ai_config, database, session_store

# Ensure database is initialized before any requests
database.init_db()
database.recover_orphans()
database.recover_jobs()

API_TOKEN = os.environ.get("APP_API_TOKEN")
if not API_TOKEN:
    raise RuntimeError("APP_API_TOKEN must be set by the desktop launcher")

app = FastAPI(title="Instagram Saved Archiver API")

# Allow CORS for local development with Electron/React
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "null"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def require_local_token(request, call_next):
    # Allow local media static files and media streaming requests without requiring token header
    # (HTML5 <video> and <img> tags and browser range requests cannot easily send custom auth headers)
    if (
        request.method != "OPTIONS" 
        and not request.url.path.startswith("/media") 
        and not request.url.path.startswith("/media-stream")
        and not secrets.compare_digest(request.headers.get("X-App-Token", ""), API_TOKEN)
    ):
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return await call_next(request)

media_dir = database.DATA_DIR / "media/canonical_files"
media_dir.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=str(media_dir)), name="media")

@app.get("/media-stream/{pk}")
def get_media_stream(pk: str, index: int = 0):
    conn = database.get_db()
    try:
        row = conn.execute(
            "SELECT file_path FROM media_files WHERE post_pk=? ORDER BY media_index LIMIT 1 OFFSET ?", 
            (pk, index)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Media not found in database")
    abs_path = database.resolve_media_path(row['file_path'])
    if not abs_path.is_file():
        canonical_cand = database.DATA_DIR / "media/canonical_files" / pk / Path(row['file_path']).name
        if canonical_cand.is_file():
            abs_path = canonical_cand
        else:
            raise HTTPException(status_code=404, detail="Media file not found on disk")
    suffix = abs_path.suffix.lower()
    media_type = "video/mp4" if suffix in {'.mp4', '.mov'} else ("image/jpeg" if suffix in {'.jpg', '.jpeg'} else "application/octet-stream")
    from fastapi.responses import FileResponse
    return FileResponse(str(abs_path), media_type=media_type)

class JobStartRequest(BaseModel):
    job_type: str
    params: Optional[dict] = None

class StorageCopyRequest(BaseModel):
    destination_parent: str
    activate: bool = False

class StorageMigrateRequest(BaseModel):
    source_directory: str
    destination_directory: Optional[str] = None
    activate: bool = True

class AppSettingsUpdate(BaseModel):
    daily_download_limit: Optional[int] = None
    proxies: Optional[str] = None
    download_concurrency: Optional[int] = None
    download_delay_min: Optional[float] = None
    download_delay_max: Optional[float] = None

@app.post('/storage/copy')
def copy_storage(request: StorageCopyRequest):
    try:
        job_id = manager.start_job('storage', StorageService.copy_archive,
                                   destination_parent=request.destination_parent, activate=request.activate)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {'job_id': job_id}

@app.post('/storage/migrate')
def migrate_storage(request: StorageMigrateRequest):
    try:
        job_id = manager.start_job('migration', StorageService.migrate_archive,
                                   source_directory=request.source_directory,
                                   destination_directory=request.destination_directory,
                                   activate=request.activate)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {'job_id': job_id}

@app.get('/settings/app')
def get_app_settings():
    return {
        'daily_download_limit': database.get_daily_download_limit(),
        'proxies': database.get_setting('proxies', '') or '',
        'download_concurrency': database.get_download_concurrency(),
        'delay_range': database.get_download_delay_range(),
    }

@app.post('/settings/app')
def update_app_settings(update: AppSettingsUpdate):
    if update.daily_download_limit is not None:
        database.set_setting('daily_download_limit', str(update.daily_download_limit))
    if update.proxies is not None:
        database.set_setting('proxies', update.proxies)
    if update.download_concurrency is not None:
        database.set_setting('download_concurrency', str(update.download_concurrency))
    if update.download_delay_min is not None:
        database.set_setting('download_delay_min', str(update.download_delay_min))
    if update.download_delay_max is not None:
        database.set_setting('download_delay_max', str(update.download_delay_max))
    return get_app_settings()

@app.get("/jobs")
def get_jobs():
    return manager.get_all_jobs()

@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    job = manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job

@app.post("/jobs")
def start_job(request: JobStartRequest):
    job_type = request.job_type.lower()
    params = request.params or {}
    
    if job_type not in {"discovery", "download", "analysis", "taxonomy", "integrity", "export_import", "quality_scan", "migration", "storage", "reconciliation", "rebuild"}:
        raise HTTPException(status_code=400, detail="Invalid job type")
    allowed = {"discovery": {"max_pages", "mode", "source"}, "download": {"batch_size", "from_date", "to_date", "sync_id", "source", "collection", "quality_target", "upgrade", "downloader", "continuous"},
               "analysis": {"batch_size", "continuous"}, "taxonomy": set(), "integrity": set(),
               "export_import": {"directory"}, "quality_scan": set(),
               "migration": {"source_directory", "destination_directory", "activate"},
               "storage": {"destination_parent", "activate"},
               "reconciliation": {"auto_repair"},
               "rebuild": {"archive_dir"}}
    if set(params) - allowed[job_type]:
        raise HTTPException(status_code=422, detail="Invalid job parameters")
    size_key = "max_pages" if job_type == "discovery" else "batch_size"
    if size_key in params:
        val = params[size_key]
        if type(val) is not int or val < 0 or val > 1000000:
            raise HTTPException(status_code=422, detail="Invalid job size: must be an integer between 0 and 1000000 (0 = continuous)")
        if job_type == "discovery" and not 1 <= val <= 50:
            raise HTTPException(status_code=422, detail="Invalid discovery size: must be between 1 and 50")
    if job_type == "discovery":
        if params.get("mode", "recent") not in {"recent", "history"}:
            raise HTTPException(status_code=422, detail="Invalid sync mode")
        if params.get("source", "saved") not in {"saved", "liked", "all"}:
            raise HTTPException(status_code=422, detail="Invalid discovery source: must be 'saved', 'liked', or 'all'")
    if job_type == "download":
        if params.get('source', 'all') not in {'all', 'saved', 'liked'} or params.get('quality_target', 'high') not in {'hd', 'high'} or params.get('downloader', 'session') not in {'session', 'public', 'auto'} or type(params.get('upgrade', False)) is not bool:
            raise HTTPException(status_code=422, detail='Invalid download selection')
        if 'collection' in params and (type(params['collection']) is not str or len(params['collection']) > 100):
            raise HTTPException(status_code=422, detail='Invalid collection')
        if 'sync_id' in params:
            if type(params['sync_id']) is not str or len(params['sync_id']) > 100:
                raise HTTPException(status_code=422, detail="Invalid sync report ID")
            conn = database.get_db()
            try:
                exists = conn.execute("SELECT 1 FROM sync_runs WHERE id=?", (params['sync_id'],)).fetchone()
            finally:
                conn.close()
            if not exists:
                raise HTTPException(status_code=422, detail="Unknown sync report")
        for key in ("from_date", "to_date"):
            if key in params:
                try:
                    date.fromisoformat(params[key])
                except (TypeError, ValueError):
                    raise HTTPException(status_code=422, detail=f"Invalid {key}")
        if params.get("from_date") and params.get("to_date") and params["from_date"] > params["to_date"]:
            raise HTTPException(status_code=422, detail="Start date is after end date")
    if job_type == 'export_import':
        try:
            validate_export_directory(params['directory'])
        except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=422, detail='Invalid Instagram export folder or JSON') from exc

    if job_type in {"discovery", "download"} and database.get_instagram_pause():
        raise HTTPException(status_code=409, detail="Instagram access is paused; review the account before resuming")

    workers = {"discovery": DiscoveryService.run_discovery, "download": DownloadService.run_downloads,
               "analysis": AIService.run_analysis, "taxonomy": TaxonomyService.run_taxonomy,
               "integrity": DownloadService.run_integrity, "export_import": run_import,
               "quality_scan": DownloadService.run_quality_scan,
               "reconciliation": ReconciliationService.run_reconciliation,
               "rebuild": ReconciliationService.run_rebuild_job}
    try:
        job_id = manager.start_job(job_type, workers[job_type], **params)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
        
    return {"job_id": job_id, "message": f"{job_type} job started."}

class AnalysisJobRequest(BaseModel):
    limit: Optional[int] = 0
    batch_size: Optional[int] = 0
    continuous: Optional[bool] = True

@app.post("/jobs/analysis")
def start_analysis_job_shortcut(request: Optional[AnalysisJobRequest] = None):
    batch = 0
    continuous = True
    if request:
        batch = request.batch_size if request.batch_size is not None else (request.limit or 0)
        if request.continuous is not None:
            continuous = request.continuous
    try:
        job_id = manager.start_job('analysis', AIService.run_analysis, batch_size=batch, continuous=continuous)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"job_id": job_id, "message": "Analysis job started"}

class RebuildRequest(BaseModel):
    archive_dir: Optional[str] = None

@app.get('/reconciliation/diagnosis')
def get_reconciliation_diagnosis():
    return ReconciliationService.diagnose_archive()

@app.post('/reconciliation/repair')
def start_reconciliation_repair():
    try:
        job_id = manager.start_job('reconciliation', ReconciliationService.run_reconciliation, auto_repair=True)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"job_id": job_id, "message": "Reconciliation and repair started"}

@app.post('/system/rebuild-library')
def start_system_rebuild(request: Optional[RebuildRequest] = None):
    archive_dir = request.archive_dir if request else None
    try:
        job_id = manager.start_job('rebuild', ReconciliationService.run_rebuild_job, archive_dir=archive_dir)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"job_id": job_id, "message": "Disaster recovery rebuild started"}

class ExportFolderRequest(BaseModel):
    directory: str

@app.post('/import/export/preview')
def export_preview(request: ExportFolderRequest):
    try:
        return preview_export(request.directory)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail='Invalid Instagram export folder or JSON') from exc

@app.get('/import/export/collections')
def export_collections():
    conn = database.get_db()
    try:
        return [dict(row) for row in conn.execute('SELECT name, COUNT(*) AS count FROM export_collections GROUP BY name ORDER BY name')]
    finally:
        conn.close()

@app.get('/jobs/{job_id}/items')
def job_items(job_id: str):
    conn = database.get_db()
    try:
        return [dict(row) for row in conn.execute('SELECT post_pk, stage, updated_at FROM download_items WHERE job_id=? ORDER BY updated_at DESC LIMIT 100', (job_id,))]
    finally:
        conn.close()

@app.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    if not manager.get_job(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    if not manager.cancel_job(job_id):
        raise HTTPException(status_code=409, detail="Job is not running")
    return {"message": "Cancellation requested."}

@app.post("/jobs/cleanup")
def cleanup_jobs():
    conn = database.get_db()
    try:
        with conn:
            conn.execute("DELETE FROM jobs WHERE status IN ('COMPLETED', 'CANCELLED', 'FAILED')")
            conn.execute("DELETE FROM download_items WHERE job_id NOT IN (SELECT id FROM jobs)")
    finally:
        conn.close()
    return {"message": "Job history cleaned up"}

@app.get("/instagram/status")
def instagram_status():
    return {"paused_reason": database.get_instagram_pause(), "checkpoint": database.get_pagination_state()}

@app.get("/sync/runs")
def sync_runs(limit: int = Query(20, ge=1, le=100)):
    conn = database.get_db()
    try:
        return [dict(row) for row in conn.execute("SELECT * FROM sync_runs ORDER BY started_at DESC LIMIT ?", (limit,))]
    finally:
        conn.close()

@app.post("/instagram/resume")
def instagram_resume():
    database.clear_instagram_pause()
    return {"message": "Instagram access resumed manually"}

@app.post("/settings/reset-limit")
def reset_limit():
    conn = database.get_db()
    try:
        with conn:
            conn.execute("DELETE FROM download_events")
            conn.execute("INSERT INTO app_settings (key, value) VALUES ('daily_download_limit', '50000') ON CONFLICT(key) DO UPDATE SET value='50000'")
            conn.execute("UPDATE posts SET status = 'DISCOVERED', retry_count = 0 WHERE status = 'DOWNLOAD_FAILED'")
            conn.execute("UPDATE instagram_control SET paused_reason = NULL WHERE id = 1")
    finally:
        conn.close()
    return {"message": "Limit reset successfully"}


@app.get("/settings/status")
def settings_status():
    ai = ai_config.current()
    return {
        "data_dir": str(database.DATA_DIR.resolve()),
        "session_configured": os.path.isfile(SESSION_FILE),
        "ai_configured": ai["configured"],
        "ai_key_configured": ai["key_configured"],
        "ai_provider": ai["provider"],
        "ai_model": ai["model"],
        "ai_base_url": ai["base_url"],
        "public_downloader_available": bool(importlib.util.find_spec('gallery_dl') and importlib.util.find_spec('yt_dlp')),
    }

class AISettingsUpdate(BaseModel):
    provider: Literal["9router", "openrouter", "google", "custom"]
    model: str = ""
    api_key: Optional[str] = None
    base_url: Optional[str] = None

@app.post("/settings/ai")
def set_ai_settings(update: AISettingsUpdate):
    try:
        return ai_config.save(update.provider, update.model, update.api_key, update.base_url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/settings/ai/models")
def get_ai_models(update: AISettingsUpdate):
    try:
        return ai_config.list_models(update.provider, update.base_url, update.api_key)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not load models: {type(exc).__name__}") from exc

@app.post('/settings/ai/test')
def test_ai_connection(update: AISettingsUpdate):
    try:
        return ai_config.test_vision(update.provider, update.model, update.base_url, update.api_key)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f'Vision test failed: {type(exc).__name__}') from exc

@app.get('/support/diagnostics')
def diagnostics():
    conn = database.get_db()
    try:
        counts = {row['status']: row['count'] for row in conn.execute('SELECT status, COUNT(*) AS count FROM posts GROUP BY status')}
        errors = [dict(row) for row in conn.execute("SELECT type, status, COUNT(*) AS count FROM jobs GROUP BY type, status ORDER BY type, status")]
        return {'generated_at': int(time.time()), 'post_counts': counts, 'job_counts': errors,
                'session_configured': os.path.isfile(SESSION_FILE), 'instagram_paused': bool(database.get_instagram_pause()),
                'ai_provider': ai_config.current()['provider']}
    finally:
        conn.close()


class SessionImport(BaseModel):
    contents: Optional[str] = None
    contents_b64: Optional[str] = None

class CookieSessionRequest(BaseModel):
    sessionid: str
    ds_user_id: Optional[str] = None
    csrftoken: Optional[str] = None

@app.post("/settings/session")
def import_instagram_session(update: SessionImport):
    if manager.storage_busy():
        raise HTTPException(status_code=409, detail="Archive copy is running")
    try:
        if update.contents_b64 is not None:
            raw = base64.b64decode(update.contents_b64, validate=True)
        elif update.contents is not None:
            raw = update.contents.encode("utf-8")
        else:
            raise ValueError("Session file is missing")
        settings = session_store.parse_session(raw)
        if os.path.isfile(SESSION_FILE):
            existing = session_store.load_session(SESSION_FILE)
            database.bind_archive_account(session_store.account_id(existing))
        database.bind_archive_account(session_store.account_id(settings))
        session_store.save_session(settings, SESSION_FILE)
        database.clear_instagram_pause()
    except binascii.Error as exc:
        raise HTTPException(status_code=422, detail="Invalid Instagram session") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"message": "Encrypted Instagram session imported"}

@app.post("/settings/session/cookie")
def login_with_cookies(req: CookieSessionRequest):
    if manager.storage_busy():
        raise HTTPException(status_code=409, detail="Archive copy is running")
    
    clean_sessionid = req.sessionid.strip()
    if not clean_sessionid:
        raise HTTPException(status_code=422, detail="کوکی sessionid نمی‌تواند خالی باشد")
    
    user_id = req.ds_user_id.strip() if req.ds_user_id else None
    if not user_id:
        import urllib.parse
        unquoted = urllib.parse.unquote(clean_sessionid)
        if ":" in unquoted:
            candidate = unquoted.split(":", 1)[0]
            if candidate.isdigit():
                user_id = candidate

    if not user_id:
        user_id = "0"

    settings = {
        "authorization_data": {
            "ds_user_id": user_id,
            "sessionid": clean_sessionid
        },
        "cookies": {
            "sessionid": clean_sessionid,
            "ds_user_id": user_id,
            "csrftoken": (req.csrftoken or "").strip()
        }
    }

    username = user_id
    full_name = ""
    profile_pic = ""
    try:
        from instagrapi import Client
        cl = Client()
        cl.set_settings(settings)
        info = cl.account_info()
        if info:
            username = info.username
            user_id = str(info.pk)
            full_name = info.full_name or ""
            profile_pic = str(info.profile_pic_url) if info.profile_pic_url else ""
            settings["authorization_data"]["ds_user_id"] = user_id
            settings["cookies"]["ds_user_id"] = user_id
    except Exception:
        pass

    if not user_id or user_id == "0":
        raise HTTPException(status_code=422, detail="کوکی وارد شده نامعتبر است یا منقضی شده است. لطفا مجددا وارد حساب شوید.")

    try:
        if os.path.isfile(SESSION_FILE):
            existing = session_store.load_session(SESSION_FILE)
            database.bind_archive_account(session_store.account_id(existing))
        database.bind_archive_account(user_id)
        session_store.save_session(settings, SESSION_FILE)
        database.clear_instagram_pause()
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"ذخیره نشست با خطا مواجه شد: {exc}")

    return {
        "ok": True,
        "message": f"نشست اینستاگرام با موفقیت متصل شد: @{username}",
        "username": username,
        "full_name": full_name,
        "user_id": user_id,
        "profile_pic": profile_pic
    }

@app.get("/settings/session/info")
def get_session_info():
    configured = os.path.isfile(SESSION_FILE)
    if not configured:
        return {"configured": False, "is_paused": bool(database.get_instagram_pause())}
    try:
        settings = session_store.load_session(SESSION_FILE)
        uid = session_store.account_id(settings)
        return {
            "configured": True,
            "account_id": uid,
            "is_paused": bool(database.get_instagram_pause()),
            "paused_reason": database.get_instagram_pause()
        }
    except Exception:
        return {"configured": False, "is_paused": False, "error": "corrupt session"}

@app.delete("/settings/session")
def delete_instagram_session():
    if os.path.isfile(SESSION_FILE):
        try:
            os.remove(SESSION_FILE)
        except OSError:
            pass
    database.clear_instagram_pause()
    return {"ok": True, "message": "اتصال حساب اینستاگرام قطع شد"}

class LocalImportRequest(BaseModel):
    path: str

@app.post("/import/local")
def import_local_media(request: LocalImportRequest):
    if manager.storage_busy():
        raise HTTPException(status_code=409, detail="Archive copy is running")
    source = Path(request.path).resolve()
    suffix = source.suffix.lower()
    if not source.is_file() or suffix not in {'.jpg', '.jpeg', '.png', '.webp', '.mp4', '.mov'}:
        raise HTTPException(status_code=422, detail="Unsupported local media file")
    if source.stat().st_size > 2_000_000_000:
        raise HTTPException(status_code=422, detail="File is too large")

    pk = f"local-{uuid.uuid4().hex}"
    out_dir = media_dir / pk
    out_dir.mkdir()
    destination = out_dir / source.name
    try:
        shutil.copy2(source, destination)
        if not DownloadService.verify_media_file(destination, suffix):
            raise ValueError("Invalid media file")
        if suffix in {'.mp4', '.mov'}:
            try:
                DownloadService.create_video_poster(destination)
            except Exception:
                pass
        conn = database.get_db()
        try:
            with conn:
                conn.execute("""INSERT INTO posts
                    (pk, shortcode, media_type, owner_username, caption, taken_at, status, status_updated_at, carousel_media_count, retry_count)
                    VALUES (?, NULL, ?, 'Local', ?, ?, 'DOWNLOAD_OK', ?, 0, 0)
                """, (pk, 2 if suffix in {'.mp4', '.mov'} else 1, source.stem, str(int(time.time())), int(time.time())))
                conn.execute("INSERT INTO media_files (post_pk, file_path, media_index) VALUES (?, ?, 0)", (pk, str(destination)))
        finally:
            conn.close()
        DownloadService.record_metrics(pk, [(str(destination), 0)])
    except Exception as exc:
        if out_dir.resolve().is_relative_to(media_dir.resolve()):
            shutil.rmtree(out_dir)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"pk": pk}

@app.get("/logs")
def get_logs(limit: int = Query(100, ge=1, le=500)):
    return manager.get_logs(limit)

@app.get("/stats")
def get_stats():
    conn = database.get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT status, COUNT(*) as count FROM posts GROUP BY status")
    rows = cursor.fetchall()
    
    stats = {row['status']: row['count'] for row in rows}
    
    cursor.execute("SELECT COUNT(*) as count FROM posts")
    total = cursor.fetchone()['count']
    stats['TOTAL'] = total

    for source in ('saved', 'liked'):
        stats[f'{source.upper()}_PENDING'] = cursor.execute(
            "SELECT COUNT(*) FROM posts WHERE status='DISCOVERED' AND is_" + source + "=1"
        ).fetchone()[0]

    now = int(time.time())
    window_start = now - 86400
    attempts = cursor.execute("SELECT COUNT(*) FROM download_events WHERE timestamp >= ?", (window_start,)).fetchone()[0]
    daily_limit = database.get_daily_download_limit()
    stats['DOWNLOAD_DAILY_LIMIT'] = daily_limit
    stats['DOWNLOAD_DAILY_REMAINING'] = max(0, daily_limit - attempts)
    oldest_attempt = cursor.execute("SELECT MIN(timestamp) FROM download_events WHERE timestamp >= ?", (window_start,)).fetchone()[0]
    stats['DOWNLOAD_DAILY_RESET_AT'] = oldest_attempt + 86400 if oldest_attempt is not None and attempts >= daily_limit else None
    
    conn.close()
    return stats

class PostMetadataUpdate(BaseModel):
    caption: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[str] = None
    summary: Optional[str] = None
    transcript: Optional[str] = None
    status: Optional[Literal["APPROVED"]] = None
    custom_category_ids: Optional[list[int]] = None

@app.get("/posts")
def get_posts(
    response: Response,
    search: Optional[str] = None,
    category: Optional[str] = None,
    custom_category_id: Optional[int] = None,
    creator: Optional[str] = None,
    status: Optional[str] = None,
    media_type: Optional[int] = None,
    source: Optional[Literal['saved', 'liked']] = None,
    collection: Optional[str] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    sort_by: Optional[Literal['activity_date', 'saved_at', 'liked_at', 'taken_at', 'status_updated_at']] = 'activity_date',
    sort_order: Optional[Literal['desc', 'asc']] = 'desc',
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0)
):
    conn = database.get_db()
    cursor = conn.cursor()
    
    query = """
        SELECT p.* FROM posts p
        WHERE 1=1
    """
    params = []
    
    if search:
        search_term = search.strip()
        norm_term = database.normalize_persian_text(search_term)
        fts_used = False
        try:
            has_fts = cursor.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='posts_fts'").fetchone()
            if has_fts and norm_term:
                clean_words = re.findall(r'[\w\u0600-\u06FF-]+', norm_term, re.UNICODE)
                if clean_words:
                    match_expr = " ".join(f'"{w}"*' for w in clean_words)
                    query += " AND p.pk IN (SELECT pk FROM posts_fts WHERE posts_fts MATCH ?)"
                    params.append(match_expr)
                    fts_used = True
        except Exception:
            fts_used = False

        if not fts_used:
            query += " AND (p.caption LIKE ? OR p.ai_summary LIKE ? OR p.transcript LIKE ? OR p.ai_tags LIKE ? OR p.owner_username LIKE ? OR p.owner_id LIKE ? OR p.ai_categories LIKE ?)"
            params.extend([f"%{search_term}%", f"%{search_term}%", f"%{search_term}%", f"%{search_term}%", f"%{search_term}%", f"%{search_term}%", f"%{search_term}%"])
    if category:
        query += " AND (p.ai_category LIKE ? OR p.ai_categories LIKE ?)"
        params.extend([f"{category}%", f'%"{category}"%'])
    if custom_category_id is not None:
        query += " AND p.pk IN (SELECT post_pk FROM post_custom_categories WHERE category_id = ?)"
        params.append(custom_category_id)
    if creator:
        query += " AND p.owner_username = ?"
        params.append(creator)
    if status:
        if status == 'downloaded':
            query += " AND p.status IN ('DOWNLOAD_OK', 'ANALYSIS_PENDING', 'ANALYSIS_OK', 'ORGANIZED', 'APPROVED')"
        elif ',' in status:
            parts = [s.strip() for s in status.split(',') if s.strip()]
            placeholders = ','.join(['?'] * len(parts))
            query += f" AND p.status IN ({placeholders})"
            params.extend(parts)
        else:
            query += " AND p.status = ?"
            params.append(status)
    if media_type is not None:
        query += " AND p.media_type = ?"
        params.append(media_type)
    if source:
        query += f" AND p.is_{source}=1"
    if collection:
        query += " AND EXISTS (SELECT 1 FROM export_collections ec WHERE ec.post_pk=p.pk AND ec.name=?)"
        params.append(collection)
    if from_date:
        query += " AND CAST(COALESCE(p.saved_at,p.liked_at,p.taken_at) AS INTEGER) >= ?"
        params.append(int(datetime.combine(from_date, dt_time.min, timezone.utc).timestamp()))
    if to_date:
        query += " AND CAST(COALESCE(p.saved_at,p.liked_at,p.taken_at) AS INTEGER) < ?"
        params.append(int(datetime.combine(to_date, dt_time.max, timezone.utc).timestamp()) + 1)
        
    count_query = query.replace("SELECT p.* FROM posts p", "SELECT COUNT(*) FROM posts p", 1)
    total_count = cursor.execute(count_query, tuple(params)).fetchone()[0]
    response.headers["X-Total-Count"] = str(total_count)
    response.headers["Access-Control-Expose-Headers"] = "X-Total-Count"

    direction = "ASC" if (sort_order and sort_order.lower() == "asc") else "DESC"
    if sort_by == 'saved_at':
        order_clause = f"CASE WHEN p.saved_at IS NULL OR p.saved_at='' THEN 1 ELSE 0 END, CAST(p.saved_at AS INTEGER) {direction}, p.pk {direction}"
    elif sort_by == 'liked_at':
        order_clause = f"CASE WHEN p.liked_at IS NULL OR p.liked_at='' THEN 1 ELSE 0 END, CAST(p.liked_at AS INTEGER) {direction}, p.pk {direction}"
    elif sort_by == 'taken_at':
        order_clause = f"CASE WHEN p.taken_at IS NULL OR p.taken_at='' THEN 1 ELSE 0 END, CAST(p.taken_at AS INTEGER) {direction}, p.pk {direction}"
    elif sort_by == 'status_updated_at':
        order_clause = f"CASE WHEN p.status_updated_at IS NULL THEN 1 ELSE 0 END, p.status_updated_at {direction}, p.pk {direction}"
    else:  # activity_date
        order_clause = f"CAST(COALESCE(p.saved_at, p.liked_at, p.taken_at) AS INTEGER) {direction}, p.pk {direction}"

    query += f" ORDER BY {order_clause} LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    
    cursor.execute(query, tuple(params))
    rows = cursor.fetchall()
    
    posts = [dict(r) for r in rows]
    files_by_post = {p['pk']: [] for p in posts}
    if posts:
        placeholders = ','.join('?' for _ in posts)
        cursor.execute(f"SELECT post_pk, file_path, width, height, size_bytes, bitrate_bps, sha256 FROM media_files WHERE post_pk IN ({placeholders}) ORDER BY post_pk, media_index", tuple(files_by_post))
        for row in cursor.fetchall():
            files_by_post[row['post_pk']].append(dict(row))

    custom_cats_map = database.get_all_posts_custom_categories([p['pk'] for p in posts])

    for p in posts:
        p['published_at_utc'] = database.published_at(p['taken_at'])
        p['saved_at_utc'] = database.published_at(p.get('saved_at'))
        p['liked_at_utc'] = database.published_at(p.get('liked_at'))
        p['custom_categories'] = custom_cats_map.get(p['pk'], [])
        try:
            p['tagged_users'] = json.loads(p.get('original_tagged_users') or '[]')
        except ValueError:
            p['tagged_users'] = []
        files = files_by_post[p['pk']]
        p['quality'] = [{key: item.get(key) for key in ('width', 'height', 'size_bytes', 'bitrate_bps', 'sha256')} for item in files]
        p['files'] = [f"/media/{p['pk']}/{Path(item['file_path']).name}" for item in files]
        p['file_paths'] = [str(database.resolve_media_path(item['file_path'])) for item in files]
        p['thumbnail'] = None
        if files:
            first_file = database.resolve_media_path(files[0]['file_path'])
            poster = first_file.with_name(f"{first_file.stem}.poster.jpg")
            if first_file.suffix.lower() in {'.mp4', '.mov'} and poster.exists():
                p['thumbnail'] = f"/media/{p['pk']}/{poster.name}"
            else:
                p['thumbnail'] = p['files'][0]
            
    conn.close()
    return posts

@app.get("/categories")
def get_categories():
    return database.get_existing_categories()

@app.get("/categories/summary")
def get_categories_summary():
    summary = database.get_categories_summary()
    summary['custom_categories'] = database.get_custom_categories()
    return summary

class CustomCategoryCreate(BaseModel):
    name: str
    folder_name: Optional[str] = None
    description: Optional[str] = ""
    color: Optional[str] = "#8b5cf6"

class CustomCategoryUpdate(BaseModel):
    name: Optional[str] = None
    folder_name: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = None

class CustomCategoryAssign(BaseModel):
    post_pks: list[str]

@app.get("/custom-categories")
def list_custom_categories():
    return database.get_custom_categories()

@app.post("/custom-categories")
def create_custom_category(req: CustomCategoryCreate):
    try:
        return database.create_custom_category(req.name, req.folder_name, req.description or "", req.color or "#8b5cf6")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=409, detail=f"Category already exists: {exc}")

@app.put("/custom-categories/{category_id}")
def update_custom_category_endpoint(category_id: int, req: CustomCategoryUpdate):
    try:
        database.update_custom_category(category_id, req.name, req.folder_name, req.description, req.color)
        return {"success": True}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

@app.delete("/custom-categories/{category_id}")
def delete_custom_category_endpoint(category_id: int):
    database.delete_custom_category(category_id)
    return {"success": True}

@app.post("/custom-categories/{category_id}/assign")
def assign_to_custom_category(category_id: int, req: CustomCategoryAssign):
    count = database.assign_posts_to_custom_category(category_id, req.post_pks)
    return {"assigned": count, "assigned_count": count}

@app.post("/custom-categories/{category_id}/remove")
def remove_from_custom_category(category_id: int, req: CustomCategoryAssign):
    count = database.remove_posts_from_custom_category(category_id, req.post_pks)
    return {"removed": count, "removed_count": count}

@app.post("/custom-categories/{category_id}/export-folder")
def export_custom_category_folder(category_id: int):
    try:
        return TaxonomyService.export_custom_category_folder(category_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

@app.get("/facets")
def get_facets():
    conn = database.get_db()
    try:
        creators = [row[0] for row in conn.execute("SELECT DISTINCT owner_username FROM posts WHERE owner_username IS NOT NULL ORDER BY owner_username")]
        return {"creators": creators, "formats": {"1": "Photo", "2": "Video", "8": "Carousel"}}
    finally:
        conn.close()

@app.post("/posts/{pk}/metadata")
def update_post_metadata(pk: str, update: PostMetadataUpdate):
    if manager.storage_busy():
        raise HTTPException(status_code=409, detail="Archive copy is running")
    conn = database.get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT status, ai_categories FROM posts WHERE pk = ?", (pk,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Post not found")
    if update.status == 'APPROVED' and row['status'] not in {'DOWNLOAD_OK', 'ANALYSIS_OK', 'REVIEW_REQUIRED'}:
        conn.close()
        raise HTTPException(status_code=409, detail="Post is not ready for approval")
    if update.category is not None and (not update.category.strip() or len(update.category) > 100 or
            len(update.category.split('/')) > 3 or any(not re.fullmatch(r"[\w\u0600-\u06FF\u200c -]{1,80}", part.strip(), re.UNICODE) for part in update.category.split('/'))):
        conn.close()
        raise HTTPException(status_code=422, detail="Invalid category name")
    
    updates = []
    params = []
    if update.caption is not None:
        updates.append("caption = ?")
        params.append(update.caption)
    if update.category is not None:
        updates.append("ai_category = ?")
        params.append(update.category)
        if row['ai_categories']:
            try:
                related = json.loads(row['ai_categories'])
            except (ValueError, TypeError):
                related = []
            updates.append("ai_categories = ?")
            params.append(json.dumps([update.category] + [item for item in related if item != update.category][:4], ensure_ascii=False))
    if update.tags is not None:
        updates.append("ai_tags = ?")
        params.append(update.tags)
    if update.summary is not None:
        updates.append("ai_summary = ?")
        params.append(update.summary)
    if update.transcript is not None:
        updates.append("transcript = ?")
        params.append(update.transcript)
    if update.status is not None:
        updates.append("status = ?")
        params.append(update.status)
        updates.append("status_updated_at = ?")
        params.append(int(time.time()))
    elif row['status'] == 'ORGANIZED' and updates:
        updates.append("status = 'APPROVED'")
        updates.append("status_updated_at = ?")
        params.append(int(time.time()))
        
    if update.custom_category_ids is not None:
        cursor.execute("DELETE FROM post_custom_categories WHERE post_pk = ?", (pk,))
        now_ts = int(time.time())
        for cid in update.custom_category_ids:
            cursor.execute("INSERT OR IGNORE INTO post_custom_categories (post_pk, category_id, added_at) VALUES (?, ?, ?)", (pk, cid, now_ts))

    if updates:
        params.append(pk)
        query = f"UPDATE posts SET {', '.join(updates)} WHERE pk = ?"
        cursor.execute(query, tuple(params))
        
    conn.commit()
    conn.close()
    
    return {"message": "Metadata updated successfully"}

@app.post("/posts/retry-failed")
def retry_failed_posts():
    if manager.storage_busy():
        raise HTTPException(status_code=409, detail="Archive copy is running")
    count = database.reset_failed_posts()
    database.clear_instagram_pause()
    return {"message": f"Reset {count} failed posts to DISCOVERED", "reset_count": count}

@app.post("/posts/retry-analysis")
def retry_failed_analysis():
    if manager.storage_busy():
        raise HTTPException(status_code=409, detail="Archive copy is running")
    conn = database.get_db()
    try:
        with conn:
            result = conn.execute("UPDATE posts SET status='DOWNLOAD_OK', ai_retry_count=0, ai_next_retry_at=0, ai_error=NULL WHERE status='ANALYSIS_FAILED'")
        return {"reset": result.rowcount}
    finally:
        conn.close()

class DownloadUrlRequest(BaseModel):
    url: str
    downloader: Optional[str] = "public"
    quality_target: Optional[str] = "high"

@app.post("/download/url")
def download_single_url(req: DownloadUrlRequest):
    from urllib.parse import urlsplit
    import re
    from instagrapi.utils.ids import InstagramIdCodec

    raw_url = req.url.strip()
    parsed = urlsplit(raw_url)
    match = re.search(r'/(p|reel|tv|reels)/([A-Za-z0-9_-]{5,64})/?', parsed.path)
    if not match:
        raise HTTPException(status_code=400, detail="لینک معتبر پست یا ریلز اینستاگرام نیست")
    
    kind, code = match.groups()
    if kind == 'reels': kind = 'reel'
    
    conn = database.get_db()
    existing_row = conn.execute("SELECT pk, shortcode, media_type, status FROM posts WHERE shortcode = ?", (code,)).fetchone()
    conn.close()

    if existing_row:
        pk = existing_row['pk']
        media_type = int(existing_row['media_type'] or (2 if kind in {'reel', 'tv'} else 0))
        if existing_row['status'] in {'DOWNLOAD_OK', 'ORGANIZED', 'APPROVED'}:
            read_conn = database.get_db()
            try:
                media_files = [dict(r) for r in read_conn.execute("SELECT * FROM media_files WHERE post_pk = ?", (pk,)).fetchall()]
            finally:
                read_conn.close()
            if media_files and all(database.resolve_media_path(mf['file_path']).exists() for mf in media_files):
                post_data = dict(existing_row)
                post_data['files'] = [f"/media/{pk}/{Path(mf['file_path']).name}" for mf in media_files]
                return {
                    "success": True,
                    "already_exists": True,
                    "message": "این پست قبلاً با بالاترین کیفیت دانلود شده و در آرشیو شما موجود است.",
                    "post": post_data,
                    "media_files": media_files
                }
    else:
        try:
            pk = str(InstagramIdCodec.decode(code[:11]))
        except Exception:
            pk = f"direct-{code}"
        media_type = 2 if kind in {'reel', 'tv'} else 0

    proxies = database.get_proxies()
    proxy = proxies[0] if proxies else None

    try:
        if req.downloader == 'session' and os.path.isfile(SESSION_FILE):
            cl = DiscoveryService.get_client("direct-download")
            info = cl.media_info_v1(pk)
            media_type = int(info.media_type)
            final_paths = DownloadService.download_post_media(cl, pk, info, upgrade=False)
            taken_at = str(int(info.taken_at.timestamp())) if info.taken_at else str(int(time.time()))
            username = info.user.username if info.user else 'instagram'
            caption = info.caption_text if info.caption_text else ''
        else:
            final_paths = DownloadService.download_public_media(
                pk=pk, shortcode=code, media_type=media_type,
                original_url=f"https://www.instagram.com/{kind}/{code}/",
                proxy=proxy
            )
            media_type = 8 if len(final_paths) > 1 else (2 if Path(final_paths[0][0]).suffix.lower() in {'.mp4', '.mov'} else 1)
            taken_at = str(int(time.time()))
            username = 'instagram'
            caption = ''

        now = int(time.time())
        db_conn = database.get_db()
        try:
            with db_conn:
                db_conn.execute("""
                    INSERT INTO posts (pk, shortcode, original_url, media_type, owner_username, caption, taken_at, status, status_updated_at, retry_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'DOWNLOAD_OK', ?, 0)
                    ON CONFLICT(pk) DO UPDATE SET
                        status = 'DOWNLOAD_OK',
                        media_type = excluded.media_type,
                        status_updated_at = excluded.status_updated_at
                """, (pk, code, f"https://www.instagram.com/{kind}/{code}/", media_type, username, caption, taken_at, now))
        finally:
            db_conn.close()

        database.complete_download(pk, final_paths)

        read_conn = database.get_db()
        try:
            post_data = dict(read_conn.execute("SELECT * FROM posts WHERE pk = ?", (pk,)).fetchone())
            media_files = [dict(r) for r in read_conn.execute("SELECT * FROM media_files WHERE post_pk = ?", (pk,)).fetchall()]
        finally:
            read_conn.close()

        post_data['files'] = [f"/media/{pk}/{Path(mf['file_path']).name}" for mf in media_files]

        return {
            "success": True,
            "message": "دانلود با موفقیت انجام شد",
            "post": post_data,
            "media_files": media_files
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"خطا در دانلود: {safe_error_detail(exc)}") from exc

@app.get("/duplicates")
def get_duplicates():
    """Returns duplicate media items grouped by SHA256 hash."""
    conn = database.get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT sha256, COUNT(*) as count, GROUP_CONCAT(post_pk, ', ') as post_pks, SUM(size_bytes) as total_bytes
            FROM media_files
            WHERE sha256 IS NOT NULL AND sha256 != ''
            GROUP BY sha256
            HAVING COUNT(*) > 1
            ORDER BY total_bytes DESC
            LIMIT 100
        """)
        dups = [dict(r) for r in cursor.fetchall()]
        return {"duplicate_groups": dups, "count": len(dups)}
    finally:
        conn.close()

# Entry point for running the API directly
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api:app", host="127.0.0.1", port=8000, reload=True)
