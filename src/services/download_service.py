import os
import time
import random
import shutil
import threading
import json
import re
import cv2
import requests
from PIL import Image
from pathlib import Path
from datetime import date, datetime, time as dt_time, timezone
from urllib.parse import urlsplit
from instagrapi import Client
from instagrapi.exceptions import (
    ClientError, LoginRequired, RateLimitError, FeedbackRequired, 
    PleaseWaitFewMinutes, ClientThrottledError, ChallengeRequired
)
from .. import database
from ..job_manager import manager
from .discovery_service import DiscoveryService, SESSION_FILE

MEDIA_DIR = database.DATA_DIR / "media/canonical_files"
_PUBLIC_INSTAGRAM_EXTRACTOR_READY = False

def safe_error_detail(error):
    detail = str(error).replace('\r', ' ').replace('\n', ' ')
    detail = re.sub(r'(?i)\b(?:https?://)[^\s\"\'<>]+', '<url>', detail)
    detail = re.sub(r'(?i)\b(authorization|cookie|password|access[_-]?token|refresh[_-]?token|api[_-]?key)\s*[:=]\s*[^\s,;]+', r'\1=<redacted>', detail)
    detail = re.sub(r'(?i)\bBearer\s+\S+', 'Bearer <redacted>', detail)
    detail = re.sub(r'(?i)[A-Z]:\\Users\\[^\\\s]+', '<user-path>', detail)
    return ' '.join(detail.split())[:240]

class PublicAccessWarning(RuntimeError):
    pass

class PublicLoginRequired(RuntimeError):
    pass

class DownloadService:
    @staticmethod
    def media_metrics(path: Path):
        size = path.stat().st_size
        if path.suffix.lower() in {'.mp4', '.mov'}:
            cap = cv2.VideoCapture(str(path))
            try:
                width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                fps = cap.get(cv2.CAP_PROP_FPS)
                frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
            finally:
                cap.release()
            duration = frames / fps if fps and frames else None
            return width, height, size, duration, int(8 * size / duration) if duration else None
        with Image.open(path) as image:
            return image.width, image.height, size, None, None

    @classmethod
    def record_metrics(cls, pk, files):
        conn = database.get_db()
        try:
            with conn:
                for path, index in files:
                    file_p = database.resolve_media_path(path)
                    width, height, size, duration, bitrate = cls.media_metrics(file_p)
                    sha256 = None
                    try:
                        if file_p.is_file():
                            with file_p.open('rb') as f:
                                sha256 = hashlib.file_digest(f, 'sha256').hexdigest()
                    except Exception:
                        pass
                    conn.execute('''UPDATE media_files SET width=?, height=?, size_bytes=?, duration_seconds=?, bitrate_bps=?, sha256=COALESCE(?, sha256)
                                    WHERE post_pk=? AND media_index=?''',
                                 (width, height, size, duration, bitrate, sha256, pk, index))
        finally:
            conn.close()

    @classmethod
    def run_quality_scan(cls, job_id, cancel_event):
        conn = database.get_db()
        try:
            rows = conn.execute('SELECT post_pk, file_path, media_index FROM media_files ORDER BY post_pk, media_index').fetchall()
        finally:
            conn.close()
        checked = missing = 0
        for index, row in enumerate(rows, 1):
            if cancel_event.is_set():
                break
            path = database.resolve_media_path(row['file_path'])
            if cls.verify_media_file(path, path.suffix):
                cls.record_metrics(row['post_pk'], [(str(path), row['media_index'])])
                checked += 1
            else:
                missing += 1
            if index % 25 == 0 or index == len(rows):
                manager.update_progress(job_id, 100 * index / max(len(rows), 1), f'Checked quality {index}/{len(rows)}')
        return {'measured': checked, 'missing_or_invalid': missing}

    @staticmethod
    def item_stage(job_id, pk, stage):
        conn = database.get_db()
        try:
            with conn:
                conn.execute('''INSERT INTO download_items (job_id, post_pk, stage, updated_at) VALUES (?, ?, ?, ?)
                    ON CONFLICT(job_id, post_pk) DO UPDATE SET stage=excluded.stage, updated_at=excluded.updated_at''',
                    (job_id, pk, stage, int(time.time())))
        finally:
            conn.close()

    @classmethod
    def run_integrity(cls, job_id: str, cancel_event: threading.Event):
        database.init_db()
        conn = database.get_db()
        try:
            rows = conn.execute("""SELECT p.pk, p.status, p.export_category, p.carousel_media_count,
                m.file_path FROM posts p LEFT JOIN media_files m ON m.post_pk=p.pk
                WHERE p.status IN ('DOWNLOAD_OK','ANALYSIS_OK','ANALYSIS_FAILED','REVIEW_REQUIRED','APPROVED','ORGANIZED')
                ORDER BY p.pk, m.media_index""").fetchall()
        finally:
            conn.close()
        posts = {}
        for row in rows:
            item = posts.setdefault(row['pk'], {'status': row['status'], 'category': row['export_category'],
                                                'expected': row['carousel_media_count'] or 1, 'files': []})
            if row['file_path']:
                item['files'].append(database.resolve_media_path(row['file_path']))
        queued = local_missing = recovered = 0
        for number, (pk, item) in enumerate(posts.items(), 1):
            if cancel_event.is_set():
                break
            invalid = []
            for path in item['files']:
                if cls.verify_media_file(path, path.suffix):
                    continue
                category = item['category'] or ''
                parts = category.split('/')
                if len(parts) == 2 and all(part and part not in {'.', '..'} for part in parts):
                    category_root = database.DATA_DIR / 'categories'
                    view = category_root / parts[0] / parts[1] / pk / path.name
                    if (path.resolve().is_relative_to(MEDIA_DIR.resolve()) and
                            view.resolve().is_relative_to(category_root.resolve()) and
                            cls.verify_media_file(view, path.suffix)):
                        path.parent.mkdir(parents=True, exist_ok=True)
                        try:
                            if path.exists():
                                path.unlink()
                            os.link(view, path)
                        except OSError:
                            shutil.copy2(view, path)
                        recovered += 1
                        continue
                invalid.append(path)
            if invalid or len(item['files']) < item['expected']:
                database.mark_media_missing(pk, item['status'])
                if pk.startswith('local-'):
                    local_missing += 1
                else:
                    queued += 1
            if number % 50 == 0 or number == len(posts):
                manager.update_progress(job_id, 100 * number / max(len(posts), 1), f'Checked {number}/{len(posts)} posts')
        manager.log(job_id, 'INFO', f'Integrity: {recovered} local recoveries, {queued} queued for download, {local_missing} missing local imports')
        return {'checked': number if posts else 0, 'recovered_locally': recovered,
                'queued_for_download': queued, 'missing_local': local_missing}

    @staticmethod
    def write_source_metadata(row, file_paths):
        folder = MEDIA_DIR / row['pk']
        metadata = {key: row[key] for key in (
            'pk', 'shortcode', 'owner_id', 'owner_username', 'caption',
            'original_hashtags', 'taken_at', 'media_type')}
        metadata['tagged_users'] = json.loads(row['original_tagged_users'] or '[]') if 'original_tagged_users' in row.keys() else []
        metadata['published_at_utc'] = database.published_at(row['taken_at'])
        metadata['saved_at_utc'] = database.published_at(row['saved_at']) if 'saved_at' in row.keys() else None
        metadata['liked_at_utc'] = database.published_at(row['liked_at']) if 'liked_at' in row.keys() else None
        metadata['from_saved_export'] = bool(row['is_saved']) if 'is_saved' in row.keys() else False
        metadata['from_liked_export'] = bool(row['is_liked']) if 'is_liked' in row.keys() else False
        metadata['original_url'] = (row['original_url'] if 'original_url' in row.keys() and row['original_url']
                                    else f"https://www.instagram.com/p/{row['shortcode']}/" if row['shortcode'] else None)
        metadata['files'] = [Path(file_path).name for file_path, _ in file_paths]
        temporary = folder / 'source.json.tmp'
        temporary.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(folder / 'source.json')

    @staticmethod
    def create_video_poster(video_path: Path):
        cap = cv2.VideoCapture(str(video_path))
        try:
            ok, frame = cap.read()
            if ok:
                cv2.imwrite(str(video_path.with_name(f"{video_path.stem}.poster.jpg")), frame)
        finally:
            cap.release()

    @staticmethod
    def verify_media_file(file_path: Path, original_suffix: str) -> bool:
        path_str = str(file_path)
        
        if not file_path.exists() or file_path.stat().st_size < 1024:
            return False
            
        ext = original_suffix.lower()
        if ext in ['.jpg', '.jpeg', '.png', '.webp']:
            try:
                with Image.open(path_str) as img:
                    img.verify()
                return True
            except Exception:
                return False
                
        elif ext in ['.mp4', '.mov']:
            try:
                cap = cv2.VideoCapture(path_str)
                if not cap.isOpened():
                    return False
                ret, frame = cap.read()
                cap.release()
                return ret
            except Exception:
                return False
                
        return True

    @classmethod
    def download_post_media(cls, cl: Client, pk: str, info, upgrade: bool = False, existing_files=None) -> list:
        out_dir = MEDIA_DIR / pk
        if not str(pk).isdecimal() or not out_dir.resolve().is_relative_to(MEDIA_DIR.resolve()):
            raise ValueError('Invalid Instagram post ID')
        out_dir.mkdir(parents=True, exist_ok=True)
        
        temp_dir = out_dir / "temp_parts"
        if not temp_dir.resolve().is_relative_to(MEDIA_DIR.resolve()):
            raise ValueError('Unsafe temporary media directory')
        temp_dir.mkdir(exist_ok=True)
        
        paths = []
        try:
            username = info.user.username if info.user else 'instagram'
            if info.media_type == 1:
                p = cl.photo_download_by_url(str(info.thumbnail_url), f'{username}_{pk}', folder=temp_dir)
                paths.append(p)
            elif info.media_type == 2:
                p = cl.video_download_by_url(str(info.video_url), f'{username}_{pk}', folder=temp_dir)
                paths.append(p)
            elif info.media_type == 8:
                for resource in info.resources:
                    filename = f'{username}_{resource.pk}'
                    if resource.media_type == 1:
                        paths.append(cl.photo_download_by_url(str(resource.thumbnail_url), filename, folder=temp_dir))
                    elif resource.media_type == 2:
                        paths.append(cl.video_download_by_url(str(resource.video_url), filename, folder=temp_dir))
                    else:
                        raise ValueError('Unsupported carousel media type')
                
            return cls.finalize_download_paths(pk, paths, temp_dir, out_dir, username, upgrade, existing_files)
            
        except Exception as e:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise e

    @classmethod
    def download_public_media(cls, pk: str, shortcode: str, media_type: int, upgrade=False, existing_files=None,
                              username='instagram', original_url=None, proxy=None):
        import re
        from gallery_dl import config as gallery_config
        from gallery_dl import extractor as gallery_extractor
        from gallery_dl.extractor import instagram as instagram_extractor
        from gallery_dl.job import DownloadJob
        from yt_dlp import YoutubeDL

        if not re.fullmatch(r'[A-Za-z0-9_-]{5,64}', shortcode or ''):
            raise ValueError('Invalid Instagram shortcode')
        out_dir = MEDIA_DIR / pk
        if not str(pk).isdecimal() or not out_dir.resolve().is_relative_to(MEDIA_DIR.resolve()):
            raise ValueError('Invalid Instagram post ID')
        url = f'https://www.instagram.com/p/{shortcode}/'
        if original_url:
            parsed = urlsplit(original_url)
            route = re.fullmatch(r'/(p|reel|tv)/([A-Za-z0-9_-]{5,64})/?', parsed.path)
            if parsed.scheme != 'https' or parsed.netloc not in {'instagram.com', 'www.instagram.com'} or not route or route.group(2) != shortcode:
                raise ValueError('Invalid original Instagram URL')
            url = f'https://www.instagram.com/{route.group(1)}/{shortcode}/'
        out_dir.mkdir(parents=True, exist_ok=True)
        temp_dir = out_dir / 'temp_parts'
        shutil.rmtree(temp_dir, ignore_errors=True)
        temp_dir.mkdir()
        try:
            downloaded = False
            # Check if this post might be a video/reel:
            # 1. media_type == 2 (explicit video/reel)
            # 2. original_url has /reel/ or /tv/
            # 3. media_type == 0 (unspecified format from Instagram JSON export)
            is_video_target = (media_type == 2) or bool(original_url and ('/reel/' in original_url or '/tv/' in original_url)) or (media_type == 0)
            if is_video_target:
                try:
                    options = {'outtmpl': str(temp_dir / '%(id)s.%(ext)s'), 'format': 'best[ext=mp4]/best',
                               'noplaylist': True, 'quiet': True, 'no_warnings': True, 'overwrites': True,
                               'socket_timeout': 20}
                    if proxy:
                        options['proxy'] = proxy
                    with YoutubeDL(options) as downloader:
                        info = downloader.extract_info(url, download=True)
                    if isinstance(info, dict):
                        pub_caption = (info.get('description') or info.get('title') or '').strip()
                        pub_uploader = (info.get('uploader') or info.get('channel') or '').strip()
                        published_ts = None
                        if info.get('upload_date'):
                            try:
                                published = datetime.strptime(info['upload_date'], '%Y%m%d').replace(tzinfo=timezone.utc)
                                published_ts = str(int(published.timestamp()))
                            except (TypeError, ValueError):
                                pass
                        conn = database.get_db()
                        try:
                            with conn:
                                conn.execute('''UPDATE posts SET taken_at=COALESCE(taken_at, ?), media_type=2,
                                    caption=CASE WHEN caption IS NULL OR caption='' THEN ? ELSE caption END,
                                    owner_username=CASE WHEN owner_username IS NULL OR owner_username='' THEN ? ELSE owner_username END
                                    WHERE pk=?''', (published_ts, pub_caption[:100000], pub_uploader[:100], pk))
                        finally:
                            conn.close()
                    downloaded_videos = [path for path in temp_dir.rglob('*') if path.is_file()
                                         and path.suffix.lower() in {'.mp4', '.mov', '.webm', '.mkv'}]
                    if downloaded_videos:
                        downloaded = True
                except Exception as ytdl_err:
                    err_msg = str(ytdl_err).casefold()
                    if any(token in err_msg for token in ('429', 'rate limit', 'too many requests')):
                        raise PublicAccessWarning('Public Instagram access was rate-limited') from ytdl_err
                    # If not a video, smoothly fall through to gallery-dl
                    downloaded = False

            if not downloaded:
                # Frozen builds contain only the Instagram extractor, so register it
                # before gallery-dl's dynamic extractor scan reaches absent modules.
                global _PUBLIC_INSTAGRAM_EXTRACTOR_READY
                if not _PUBLIC_INSTAGRAM_EXTRACTOR_READY:
                    gallery_extractor.add_module(instagram_extractor)
                    _PUBLIC_INSTAGRAM_EXTRACTOR_READY = True
                gallery_config.set(('extractor',), 'base-directory', str(temp_dir))
                gallery_config.set(('extractor',), 'timeout', 20)
                if proxy:
                    gallery_config.set(('extractor',), 'proxy', proxy)
                else:
                    gallery_config.set(('extractor',), 'proxy', None)

                class MetadataDownloadJob(DownloadJob):
                    def __init__(self, job_url):
                        super().__init__(job_url)
                        self.post_metadata = {}

                    def handle_directory(self, kwdict):
                        if not self.post_metadata and (kwdict.get('post_date') or kwdict.get('description') or kwdict.get('caption')):
                            self.post_metadata = dict(kwdict)
                        super().handle_directory(kwdict)

                job = MetadataDownloadJob(url)
                result = job.run()
                if result != 0:
                    raise PublicAccessWarning(f'gallery-dl reported download failure (status {result})')
                published = job.post_metadata.get('post_date')
                pub_caption = (job.post_metadata.get('description') or job.post_metadata.get('caption') or '').strip()
                pub_uploader = (job.post_metadata.get('username') or '').strip()
                published_ts = None
                if isinstance(published, datetime) and published:
                    if published.tzinfo is None:
                        published = published.replace(tzinfo=timezone.utc)
                    else:
                        published = published.astimezone(timezone.utc)
                    published_ts = str(int(published.timestamp()))
                conn = database.get_db()
                try:
                    with conn:
                        conn.execute('''UPDATE posts SET taken_at=COALESCE(taken_at, ?),
                            caption=CASE WHEN caption IS NULL OR caption='' THEN ? ELSE caption END,
                            owner_username=CASE WHEN owner_username IS NULL OR owner_username='' THEN ? ELSE owner_username END
                            WHERE pk=?''', (published_ts, pub_caption[:100000], pub_uploader[:100], pk))
                finally:
                    conn.close()

            paths = [path for path in temp_dir.rglob('*') if path.is_file()
                     and path.suffix.lower() in {'.jpg', '.jpeg', '.png', '.webp', '.mp4', '.mov'}]
            paths.sort(key=lambda path: [int(part) if part.isdigit() else part.casefold()
                                         for part in re.split(r'(\d+)', path.name)])
            if not paths:
                raise PublicLoginRequired('No public media was downloaded; the post may be private, login-required, or unavailable')
            return cls.finalize_download_paths(pk, paths, temp_dir, out_dir, username or 'instagram', upgrade, existing_files)
        except Exception as exc:
            shutil.rmtree(temp_dir, ignore_errors=True)
            if isinstance(exc, (PublicAccessWarning, PublicLoginRequired)):
                raise
            reason = str(exc).casefold()
            if any(token in reason for token in ('429', 'rate limit', 'too many requests', 'please wait')):
                raise PublicAccessWarning('Public Instagram access was rate-limited') from exc
            if any(token in reason for token in ('login required', 'private account', 'login to see', 'not authorized',
                                                  'redirect to login', 'login page', 'requires authentication', 'could not fetch', 'no public media', 'no video')):
                raise PublicLoginRequired('This post needs an authenticated Instagram session or is private') from exc
            raise

    @classmethod
    def finalize_download_paths(cls, pk, paths, temp_dir, out_dir, username, upgrade=False, existing_files=None):
        from .taxonomy_service import TaxonomyService
        username = TaxonomyService.sanitize_windows_name(str(username or 'instagram'))
        previous = {index: Path(path) for path, index in (existing_files or [])}
        final_paths = []
        for index, source in enumerate(paths):
            source = Path(source)
            if not source.resolve().is_relative_to(temp_dir.resolve()):
                raise ValueError('Downloader returned a file outside its temporary folder')
            suffix = source.suffix.lower()
            if suffix not in {'.jpg', '.jpeg', '.png', '.webp', '.mp4', '.mov'}:
                continue
            part_file = source.with_name(f'{source.stem}.verified{suffix}.part')
            shutil.move(str(source), str(part_file))
            if not cls.verify_media_file(part_file, suffix):
                raise ValueError(f'Invalid or corrupted file: {source.name}')
            prior = previous.get(index) if upgrade else None
            if prior and (prior.parent.resolve() != out_dir.resolve() or prior.suffix.lower() != suffix):
                prior = None
            final_file = prior or out_dir / f'{username}_{pk}_{index + 1}{suffix}'
            if prior and prior.is_file():
                old, new = cls.media_metrics(prior), cls.media_metrics(part_file)
                if (new[0] * new[1], new[4] or 0) <= (old[0] * old[1], old[4] or 0):
                    part_file.unlink()
                    final_paths.append((str(prior), index))
                    continue
                shutil.copy2(prior, prior.with_name(prior.name + '.previous'))
            os.replace(part_file, final_file)
            if suffix in {'.mp4', '.mov'}:
                try:
                    cls.create_video_poster(final_file)
                except Exception:
                    pass
            final_paths.append((str(final_file), index))
        shutil.rmtree(temp_dir, ignore_errors=True)
        if not final_paths:
            raise ValueError(f'No files downloaded for post {pk}!')
        return final_paths

    @classmethod
    def run_downloads(cls, job_id: str, cancel_event: threading.Event, batch_size: int = 0,
                      from_date: str = None, to_date: str = None, sync_id: str = None,
                      source: str = 'all', collection: str = None, quality_target: str = 'high', upgrade: bool = False,
                      downloader: str = 'session', continuous: bool = True):
        database.init_db()
        conn = database.get_db()
        cursor = conn.cursor()
        
        query = "SELECT pk, shortcode, original_url, owner_id, owner_username, caption, original_hashtags, original_tagged_users, taken_at, saved_at, liked_at, is_saved, is_liked, media_type, carousel_media_count, export_category FROM posts WHERE " + ("status IN ('DOWNLOAD_OK','ANALYSIS_PENDING','ANALYSIS_OK','ANALYSIS_FAILED','APPROVED','ORGANIZED','REVIEW_REQUIRED')" if upgrade else "status = 'DISCOVERED'") + " AND pk NOT LIKE 'local-%'"
        values = []
        if source == 'saved':
            query += " AND (is_saved=1 OR (is_saved=0 AND is_liked=0))"
        elif source == 'liked':
            query += " AND is_liked=1"
        activity_time = {'saved': 'COALESCE(saved_at,taken_at,liked_at)',
                         'liked': 'COALESCE(liked_at,taken_at,saved_at)'}.get(source, 'COALESCE(saved_at,liked_at,taken_at)')
        if collection:
            query += " AND EXISTS (SELECT 1 FROM export_collections ec WHERE ec.post_pk=posts.pk AND ec.name=?)"
            values.append(collection)
        if upgrade:
            threshold = 1080 if quality_target == 'high' else 720
            query += " AND EXISTS (SELECT 1 FROM media_files m WHERE m.post_pk=posts.pk AND (m.width IS NULL OR MIN(m.width,m.height) < ? OR (LOWER(m.file_path) LIKE '%.mp4' AND COALESCE(m.bitrate_bps,0)<1000000)))"
            values.append(threshold)
            query += " AND NOT EXISTS (SELECT 1 FROM download_events e WHERE e.post_pk=posts.pk AND e.outcome='upgrade' AND e.timestamp>=?)"
            values.append(int(time.time()) - 7 * 86400)
        if from_date:
            query += f" AND CAST({activity_time} AS INTEGER) >= ?"
            values.append(int(datetime.combine(date.fromisoformat(from_date), dt_time.min, timezone.utc).timestamp()))
        if to_date:
            query += f" AND CAST({activity_time} AS INTEGER) < ?"
            values.append(int(datetime.combine(date.fromisoformat(to_date), dt_time.max, timezone.utc).timestamp()) + 1)
            
        count_query = query.replace("SELECT pk, shortcode, original_url, owner_id, owner_username, caption, original_hashtags, original_tagged_users, taken_at, saved_at, liked_at, is_saved, is_liked, media_type, carousel_media_count, export_category FROM posts", "SELECT COUNT(*) FROM posts", 1)
        total_matching = cursor.execute(count_query, tuple(values)).fetchone()[0]
        used = cursor.execute("SELECT COUNT(*) FROM download_events WHERE timestamp >= ?", (int(time.time()) - 86400,)).fetchone()[0]
        daily_limit = database.get_daily_download_limit()
        conn.close()
        
        is_continuous = (batch_size is None or batch_size <= 0 or continuous)
        target_goal = total_matching if is_continuous else min(batch_size, total_matching)

        if total_matching == 0:
            message = 'هیچ پست جدیدی مطابق فیلترهای انتخابی در صف دانلود نیست.'
            manager.log(job_id, "INFO", message)
            return {"downloaded": 0, "failed": 0, "daily_remaining": max(0, daily_limit - used),
                    "limit_reached": False, "message": message}

        proxies = database.get_proxies()
        delay_min, delay_max = database.get_download_delay_range()

        try:
            cl = DiscoveryService.get_client(job_id) if (downloader == 'session' or (downloader == 'auto' and os.path.isfile(SESSION_FILE))) else None
        except Exception:
            if downloader == 'session':
                database.record_sync_download(sync_id, failed=1)
                raise
            cl = None
            
        mode_label = "پیوسته (تا پایان همه موارد)" if is_continuous else f"دسته‌ای ({target_goal} پست)"
        manager.log(job_id, "INFO", f"شروع فرآیند دانلود: {target_goal} مورد در صف، حالت {mode_label}، روش {downloader}...")
        
        success_count = 0
        fail_count = 0
        session_known_invalid = False
        chunk_size = 25
        
        while not cancel_event.is_set():
            if not is_continuous and (success_count + fail_count) >= target_goal:
                break
                
            fetch_limit = chunk_size if is_continuous else min(chunk_size, target_goal - (success_count + fail_count))
            if fetch_limit <= 0:
                break
                
            conn = database.get_db()
            cursor = conn.cursor()
            cursor.execute(query + f" ORDER BY retry_count ASC, CAST({activity_time} AS INTEGER) DESC LIMIT ?", (*values, fetch_limit))
            todo = cursor.fetchall()
            conn.close()
            
            if not todo:
                break
                
            for idx, row in enumerate(todo):
                if cancel_event.is_set():
                    manager.log(job_id, "INFO", "Download job cancelled by user.")
                    break
                    
                row = dict(row)
                pk = row['pk']
                media_type = row['media_type']
                expected_assets = row['carousel_media_count'] or 1
                if media_type == 8 and expected_assets == 0:
                    expected_assets = 1
                    
                cls.item_stage(job_id, pk, 'fetching metadata' if row['media_type'] == 0 else 'downloading')
                if not upgrade:
                    database.update_post_status(pk, 'DOWNLOAD_PENDING')
                
                current_total = success_count + fail_count
                pct = min(99.0, (current_total / max(target_goal, 1)) * 100.0) if target_goal > 0 else 50.0
                manager.update_progress(job_id, pct, f"دانلود {current_total + 1} از {target_goal} (پست {pk})...")
            
            try:
                existing = database.get_db()
                try:
                    recorded = [(r['file_path'], r['media_index']) for r in existing.execute(
                        "SELECT file_path, media_index FROM media_files WHERE post_pk=? ORDER BY media_index", (pk,))]
                finally:
                    existing.close()
                if not upgrade and len(recorded) >= expected_assets and all(
                        cls.verify_media_file(database.resolve_media_path(path), Path(path).suffix) for path, _ in recorded):
                    final_paths = [(str(database.resolve_media_path(p)), idx) for p, idx in recorded]
                else:
                    cls.item_stage(job_id, pk, 'downloading')
                    current_proxy = proxies[idx % len(proxies)] if proxies else None
                    if downloader == 'session':
                        if current_proxy:
                            try: cl.set_proxy(current_proxy)
                            except Exception: pass
                        info = cl.media_info_v1(pk)
                        media_type = int(info.media_type)
                        taken_at = str(int(info.taken_at.timestamp())) if info.taken_at else None
                        row['taken_at'] = row['taken_at'] or taken_at
                        row['media_type'] = media_type
                        if media_type == 8:
                            expected_assets = max(1, len(info.resources or []))
                        info_conn = database.get_db()
                        try:
                            with info_conn:
                                info_conn.execute('''UPDATE posts SET media_type=?, taken_at=COALESCE(taken_at, ?),
                                    carousel_media_count=CASE WHEN ?=8 THEN ? ELSE carousel_media_count END,
                                    owner_id=COALESCE(owner_id, ?), owner_username=CASE WHEN owner_username IS NULL OR owner_username='' THEN ? ELSE owner_username END
                                    WHERE pk=?''', (media_type, taken_at, media_type, expected_assets,
                                                    str(info.user.pk) if info.user else None,
                                                    info.user.username if info.user else None, pk))
                        finally:
                            info_conn.close()
                        final_paths = cls.download_post_media(cl, pk, info, upgrade=upgrade, existing_files=recorded)
                    else:
                        final_paths = cls.download_public_media(pk, row['shortcode'], int(row['media_type'] or 0),
                                                                upgrade=upgrade, existing_files=recorded,
                                                                username=row['owner_username'] or 'instagram',
                                                                original_url=row['original_url'],
                                                                proxy=current_proxy)
                        expected_assets = len(final_paths)
                        media_type = 8 if len(final_paths) > 1 else (2 if Path(final_paths[0][0]).suffix.lower() in {'.mp4', '.mov'} else 1)
                        row['media_type'] = media_type
                        update = database.get_db()
                        try:
                            with update:
                                update.execute('UPDATE posts SET media_type=?, taken_at=COALESCE(taken_at, ?), carousel_media_count=? WHERE pk=?',
                                               (media_type, row['taken_at'], expected_assets if media_type == 8 else None, pk))
                                row['taken_at'] = update.execute('SELECT taken_at FROM posts WHERE pk=?', (pk,)).fetchone()[0]
                                row['media_type'] = media_type
                        finally:
                            update.close()
                
                if len(final_paths) < expected_assets:
                    raise ValueError(f"Downloaded files ({len(final_paths)}) less than expected ({expected_assets}).")
                    
                cls.item_stage(job_id, pk, 'verifying quality')
                cls.write_source_metadata(row, final_paths)
                if not upgrade:
                    database.complete_download(pk, final_paths)
                else:
                    update_conn = database.get_db()
                    try:
                        with update_conn:
                            update_conn.executemany('''INSERT INTO media_files (post_pk, file_path, media_index) VALUES (?, ?, ?)
                                ON CONFLICT(post_pk, media_index) DO UPDATE SET file_path=excluded.file_path''',
                                [(pk, database.to_relative_media_path(path), index) for path, index in final_paths])
                    finally:
                        update_conn.close()
                cls.record_metrics(pk, final_paths)
                if upgrade and row['export_category']:
                    from .taxonomy_service import TaxonomyService
                    TaxonomyService.refresh_media_views(row, final_paths)
                cls.item_stage(job_id, pk, 'complete')
                success_count += 1
                database.record_sync_download(sync_id, success=1)
                event_conn = database.get_db()
                try:
                    with event_conn:
                        event_conn.execute("INSERT INTO download_events (post_pk, timestamp, outcome) VALUES (?, ?, ?)",
                                           (pk, int(time.time()), 'upgrade' if upgrade else 'download'))
                finally:
                    event_conn.close()
                manager.log(job_id, "INFO", f"Successfully downloaded: {pk}")
                
            except PublicAccessWarning as e:
                manager.log(job_id, 'WARN', f"Public access warning on post {pk}: {e}")
                if not upgrade: database.update_post_status(pk, 'DOWNLOAD_FAILED')
                cls.item_stage(job_id, pk, 'paused: public access warning')
                database.record_sync_download(sync_id, failed=1)
                fail_count += 1
                if proxies:
                    manager.log(job_id, 'INFO', 'Proxy limited; rotating to next proxy...')
                if idx < len(todo) - 1 and cancel_event.wait(random.uniform(delay_min, delay_max)):
                    break
                continue
            except PublicLoginRequired as e:
                # Check for session fallback if available
                can_fallback = os.path.isfile(SESSION_FILE) and not session_known_invalid
                if can_fallback and (downloader in ('auto', 'public')):
                    manager.log(job_id, 'INFO', f"Post {pk} requires login. Attempting session fallback...")
                    try:
                        if cl is None:
                            cl = DiscoveryService.get_client(job_id)
                        info = cl.media_info_v1(pk)
                        media_type = int(info.media_type)
                        taken_at = str(int(info.taken_at.timestamp())) if info.taken_at else None
                        row['taken_at'] = row['taken_at'] or taken_at
                        row['media_type'] = media_type
                        expected_assets = max(1, len(info.resources or [])) if media_type == 8 else 1
                        fb_paths = cls.download_post_media(cl, pk, info, upgrade=upgrade, existing_files=recorded)
                        cls.item_stage(job_id, pk, 'verifying quality')
                        cls.write_source_metadata(row, fb_paths)
                        if not upgrade:
                            database.complete_download(pk, fb_paths)
                        cls.record_metrics(pk, fb_paths)
                        cls.item_stage(job_id, pk, 'complete')
                        success_count += 1
                        database.record_sync_download(sync_id, success=1)
                        manager.log(job_id, "INFO", f"Successfully downloaded {pk} via session fallback")
                        continue
                    except (LoginRequired, ChallengeRequired) as sess_err:
                        session_known_invalid = True
                        manager.log(job_id, 'WARN', "Instagram session is expired or invalid. Please re-login/import in Settings. Continuing remaining posts in public mode...")
                    except Exception as fb_err:
                        manager.log(job_id, 'WARN', f"Session fallback for {pk} failed: {safe_error_detail(fb_err)}")
                manager.log(job_id, 'INFO', f"Post {pk}: {e}")
                if not upgrade: database.update_post_status(pk, 'DOWNLOAD_FAILED')
                cls.item_stage(job_id, pk, 'needs authenticated session')
                database.record_sync_download(sync_id, failed=1)
                fail_count += 1
            except (RateLimitError, FeedbackRequired, PleaseWaitFewMinutes, ClientThrottledError) as e:
                manager.log(job_id, "ERROR", f"Instagram limit: {type(e).__name__}; stopping")
                if not upgrade: database.update_post_status(pk, 'DISCOVERED')
                cls.item_stage(job_id, pk, 'paused: account limit')
                database.record_sync_download(sync_id, failed=1)
                database.pause_instagram(type(e).__name__)
                raise RuntimeError("Instagram downloads paused after a limit warning") from e
            except (ChallengeRequired, LoginRequired) as e:
                manager.log(job_id, "ERROR", f"Instagram access stopped: {type(e).__name__}")
                if not upgrade: database.update_post_status(pk, 'DISCOVERED')
                cls.item_stage(job_id, pk, 'paused: account challenge')
                database.record_sync_download(sync_id, failed=1)
                database.pause_instagram(type(e).__name__)
                raise RuntimeError(f"Instagram downloads paused after {type(e).__name__}") from e
            except ClientError as e:
                if getattr(getattr(e, 'response', None), 'status_code', None) == 404:
                    manager.log(job_id, "INFO", f"Post {pk} is unavailable; existing local files are preserved")
                    if not upgrade: database.update_post_status(pk, 'UNAVAILABLE')
                    cls.item_stage(job_id, pk, 'unavailable')
                    fail_count += 1
                    database.record_sync_download(sync_id, failed=1)
                    if idx < len(todo) - 1 and cancel_event.wait(random.uniform(8, 15)):
                        break
                    continue
                manager.log(job_id, "ERROR", f"Instagram client error: {type(e).__name__}")
                if not upgrade: database.update_post_status(pk, 'DISCOVERED')
                cls.item_stage(job_id, pk, 'paused: client error')
                database.record_sync_download(sync_id, failed=1)
                database.pause_instagram(type(e).__name__)
                raise RuntimeError("Instagram downloads paused after a client error") from e
            except requests.HTTPError as e:
                status_code = getattr(e.response, 'status_code', None)
                if status_code in {403, 404}:
                    manager.log(job_id, "WARN", f"Post media asset inaccessible (HTTP {status_code}) for {pk}")
                    if not upgrade: database.update_post_status(pk, 'DOWNLOAD_FAILED')
                    cls.item_stage(job_id, pk, 'media asset inaccessible')
                    fail_count += 1
                    database.record_sync_download(sync_id, failed=1)
                    continue
                elif status_code == 429:
                    manager.log(job_id, "WARN", f"Media access rate-limited (HTTP 429) for {pk}")
                    if not upgrade: database.update_post_status(pk, 'DISCOVERED')
                    cls.item_stage(job_id, pk, 'paused: media access warning')
                    database.pause_instagram('Media HTTP 429')
                    raise RuntimeError('Instagram downloads paused after a media access warning') from e
                if not upgrade: database.increment_retry_count_and_status(pk, max_retries=3)
                cls.item_stage(job_id, pk, 'failed')
                fail_count += 1
            except Exception as e:
                detail = safe_error_detail(e)
                suffix = f": {detail}" if detail else ''
                manager.log(job_id, "ERROR", f"Failed downloading {pk}: {type(e).__name__}{suffix}")
                if not upgrade: database.increment_retry_count_and_status(pk, max_retries=3)
                cls.item_stage(job_id, pk, 'failed')
                fail_count += 1
                database.record_sync_download(sync_id, failed=1)
                
            if idx < len(todo) - 1 and not cancel_event.is_set():
                if cancel_event.wait(random.uniform(delay_min, delay_max)):
                    break
                
        status_msg = "لغو شد" if cancel_event.is_set() else "پایان یافت"
        manager.log(job_id, "INFO", f"عملیات دانلود {status_msg}. موفق: {success_count}، ناموفق: {fail_count}")
        manager.update_progress(job_id, 100.0 if not cancel_event.is_set() else pct, f"پایان دانلود: {success_count} موفق، {fail_count} ناموفق")
        return {"downloaded": success_count, "failed": fail_count}
