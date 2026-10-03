import sqlite3
import time
import os
import json
import re
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(os.environ.get("ARCHIVE_DATA_DIR", "archive"))
DB_PATH = DATA_DIR / "database/library.db"

def get_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=30.0)
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA cache_size = -64000;")
    conn.execute("PRAGMA temp_store = MEMORY;")
    conn.row_factory = sqlite3.Row
    return conn

def normalize_persian_text(text: str | None) -> str:
    """
    Normalizes Persian and Arabic text variants to enable consistent token matching in FTS5 and search queries:
    - Converts Arabic Yeh ('ي', U+064A) and Alef Maksura ('ى', U+0649) to Persian Yeh ('ی', U+06CC)
    - Converts Arabic Kaf ('ك', U+0643) to Persian Kaf ('ک', U+06A9)
    - Replaces Zero-Width Non-Joiner (ZWNJ / نیم‌فاصله, U+200C) with space to separate token boundaries
    - Converts Teh Marbuta ('ة', U+0629) and Heh with Yeh ('ۀ', U+06C0) to Heh ('ه', U+0647)
    """
    if not text:
        return ""
    return (
        str(text)
        .replace('\u064a', '\u06cc')
        .replace('\u0649', '\u06cc')
        .replace('\u0643', '\u06a9')
        .replace('\u200c', ' ')
        .replace('\u0629', '\u0647')
        .replace('\u06c0', '\u0647')
    )

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS posts (
        pk TEXT PRIMARY KEY,
        shortcode TEXT,
        original_url TEXT,
        media_type INTEGER,
        owner_username TEXT,
        owner_id TEXT,
        caption TEXT,
        original_hashtags TEXT,
        taken_at TEXT,
        status TEXT,
        ai_category TEXT,
        ai_summary TEXT,
        ai_tags TEXT,
        ai_categories TEXT,
        status_updated_at INTEGER,
        carousel_media_count INTEGER,
        retry_count INTEGER DEFAULT 0
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS media_files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_pk TEXT,
        file_path TEXT,
        media_index INTEGER,
        FOREIGN KEY(post_pk) REFERENCES posts(pk),
        UNIQUE(post_pk, media_index)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS pagination_state (
        id INTEGER PRIMARY KEY,
        historical_scan_cursor TEXT,
        last_seen_newest_pk TEXT,
        pending_newest_pk TEXT
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY,
        type TEXT,
        status TEXT,
        progress REAL DEFAULT 0,
        message TEXT,
        created_at INTEGER,
        updated_at INTEGER,
        details TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp INTEGER,
        level TEXT,
        message TEXT,
        job_id TEXT,
        details TEXT
    )
    """)

    cursor.execute("CREATE TABLE IF NOT EXISTS instagram_control (id INTEGER PRIMARY KEY CHECK(id = 1), paused_reason TEXT)")
    cursor.execute("INSERT OR IGNORE INTO instagram_control (id, paused_reason) VALUES (1, NULL)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_posts_status_taken_at ON posts(status, taken_at DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_posts_taken_at ON posts(taken_at DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at DESC)")
    cursor.execute("CREATE TABLE IF NOT EXISTS archive_account (id INTEGER PRIMARY KEY CHECK(id=1), account_id TEXT NOT NULL)")
    cursor.execute("CREATE TABLE IF NOT EXISTS sync_runs (id TEXT PRIMARY KEY, mode TEXT, started_at INTEGER, finished_at INTEGER, pages INTEGER DEFAULT 0, discovered INTEGER DEFAULT 0, checked INTEGER DEFAULT 0, outcome TEXT, error TEXT)")
    sync_columns = {row[1] for row in cursor.execute("PRAGMA table_info(sync_runs)")}
    for column in ("duplicates", "downloaded", "download_failed"):
        if column not in sync_columns:
            cursor.execute(f"ALTER TABLE sync_runs ADD COLUMN {column} INTEGER DEFAULT 0")

    # Try adding the pending_newest_pk column if the table already existed before this update
    try:
        cursor.execute("ALTER TABLE pagination_state ADD COLUMN pending_newest_pk TEXT")
    except sqlite3.OperationalError:
        pass # Column already exists
        
    try:
        cursor.execute("ALTER TABLE posts ADD COLUMN carousel_media_count INTEGER")
    except sqlite3.OperationalError:
        pass # Column already exists
    
    try:
        cursor.execute("ALTER TABLE posts ADD COLUMN retry_count INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass # Column already exists

    columns = {row[1] for row in cursor.execute("PRAGMA table_info(posts)")}
    for column in ("owner_id", "original_url", "original_hashtags", "original_tagged_users", "ai_categories", "saved_at", "ai_confidence", "ai_error", "export_category", "repair_from_status", "liked_at", "export_fbid", "transcript"):
        if column not in columns:
            cursor.execute(f"ALTER TABLE posts ADD COLUMN {column} TEXT")
            if column == "export_category" and "ai_category" in columns:
                cursor.execute("UPDATE posts SET export_category=ai_category WHERE status='ORGANIZED'")
            if column == "original_hashtags":
                rows = cursor.execute("SELECT pk, caption FROM posts WHERE caption LIKE '%#%'").fetchall()
                cursor.executemany("UPDATE posts SET original_hashtags = ? WHERE pk = ?", [
                    (", ".join(dict.fromkeys("#" + tag for tag in re.findall(r"(?<!\w)#([\w]+)", row['caption'] or ""))), row['pk'])
                    for row in rows
                ])
    for column, kind in (("ai_retry_count", "INTEGER DEFAULT 0"), ("ai_next_retry_at", "INTEGER DEFAULT 0")):
        if column not in columns:
            cursor.execute(f"ALTER TABLE posts ADD COLUMN {column} {kind}")
    for column in ("is_saved", "is_liked"):
        if column not in columns:
            cursor.execute(f"ALTER TABLE posts ADD COLUMN {column} INTEGER DEFAULT 0")
    for name in ("idx_posts_saved_queue", "idx_posts_liked_queue", "idx_posts_all_queue"):
        row = cursor.execute("SELECT sql FROM sqlite_master WHERE type='index' AND name=?", (name,)).fetchone()
        if row and "retry_count" not in row[0].casefold():
            cursor.execute(f"DROP INDEX {name}")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_posts_saved_queue ON posts(status, retry_count ASC, CAST(COALESCE(saved_at, taken_at, liked_at) AS INTEGER) DESC, pk DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_posts_liked_queue ON posts(status, retry_count ASC, CAST(COALESCE(liked_at, taken_at, saved_at) AS INTEGER) DESC, pk DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_posts_all_queue ON posts(status, retry_count ASC, CAST(COALESCE(saved_at, liked_at, taken_at) AS INTEGER) DESC, pk DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_posts_activity_order ON posts(CAST(COALESCE(saved_at, liked_at, taken_at) AS INTEGER) DESC, pk DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_posts_saved_at_order ON posts(CAST(saved_at AS INTEGER) DESC, pk DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_posts_liked_at_order ON posts(CAST(liked_at AS INTEGER) DESC, pk DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_posts_status_updated_order ON posts(status_updated_at DESC, pk DESC)")
    cursor.execute("CREATE TABLE IF NOT EXISTS export_collections (name TEXT NOT NULL, post_pk TEXT NOT NULL, PRIMARY KEY(name, post_pk))")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_export_collections_post ON export_collections(post_pk)")
    cursor.execute("CREATE TABLE IF NOT EXISTS download_items (job_id TEXT NOT NULL, post_pk TEXT NOT NULL, stage TEXT NOT NULL, updated_at INTEGER NOT NULL, PRIMARY KEY(job_id, post_pk))")
    cursor.execute("CREATE TABLE IF NOT EXISTS download_events (post_pk TEXT NOT NULL, timestamp INTEGER NOT NULL, outcome TEXT NOT NULL)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_download_events_time ON download_events(timestamp)")
    media_columns = {row[1] for row in cursor.execute("PRAGMA table_info(media_files)")}
    for column, kind in (("width", "INTEGER"), ("height", "INTEGER"), ("size_bytes", "INTEGER"),
                         ("duration_seconds", "REAL"), ("bitrate_bps", "INTEGER"), ("sha256", "TEXT")):
        if column not in media_columns:
            cursor.execute(f"ALTER TABLE media_files ADD COLUMN {column} {kind}")
    
    # Initialize pagination state if empty
    cursor.execute("SELECT COUNT(*) FROM pagination_state")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO pagination_state (id, historical_scan_cursor, last_seen_newest_pk, pending_newest_pk) VALUES (1, NULL, NULL, NULL)")
    state_columns = {row[1] for row in cursor.execute("PRAGMA table_info(pagination_state)")}
    if "recent_scan_cursor" not in state_columns:
        cursor.execute("ALTER TABLE pagination_state ADD COLUMN recent_scan_cursor TEXT")
    if "historical_complete" not in state_columns:
        cursor.execute("ALTER TABLE pagination_state ADD COLUMN historical_complete INTEGER DEFAULT 0")
    if "owner_username" in columns:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_posts_owner ON posts(owner_username)")
    if "media_type" in columns:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_posts_format ON posts(media_type)")
        
    cursor.execute("CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT)")
    
    # Initialize FTS5 Full-Text Search Virtual Table
    try:
        cursor.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS posts_fts USING fts5(
            pk UNINDEXED,
            caption,
            original_hashtags,
            owner_username,
            shortcode,
            ai_summary,
            ai_tags,
            ai_category,
            tokenize = 'unicode61'
        )
        """)
        cursor.execute("DROP TRIGGER IF EXISTS trg_posts_ai")
        cursor.execute("DROP TRIGGER IF EXISTS trg_posts_au")
        cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_posts_ai AFTER INSERT ON posts BEGIN
            INSERT INTO posts_fts (pk, caption, original_hashtags, owner_username, shortcode, ai_summary, ai_tags, ai_category)
            VALUES (
                new.pk,
                REPLACE(REPLACE(REPLACE(REPLACE(COALESCE(new.caption, ''), 'ي', 'ی'), 'ك', 'ک'), char(8204), ' '), 'ة', 'ه'),
                REPLACE(REPLACE(REPLACE(REPLACE(COALESCE(new.original_hashtags, ''), 'ي', 'ی'), 'ك', 'ک'), char(8204), ' '), 'ة', 'ه'),
                COALESCE(new.owner_username, ''),
                COALESCE(new.shortcode, ''),
                REPLACE(REPLACE(REPLACE(REPLACE(COALESCE(new.ai_summary, '') || ' ' || COALESCE(new.transcript, ''), 'ي', 'ی'), 'ك', 'ک'), char(8204), ' '), 'ة', 'ه'),
                REPLACE(REPLACE(REPLACE(REPLACE(COALESCE(new.ai_tags, ''), 'ي', 'ی'), 'ك', 'ک'), char(8204), ' '), 'ة', 'ه'),
                REPLACE(REPLACE(REPLACE(REPLACE(COALESCE(new.ai_category, ''), 'ي', 'ی'), 'ك', 'ک'), char(8204), ' '), 'ة', 'ه')
            );
        END;
        """)
        cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_posts_ad AFTER DELETE ON posts BEGIN
            DELETE FROM posts_fts WHERE pk = old.pk;
        END;
        """)
        cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_posts_au AFTER UPDATE ON posts BEGIN
            DELETE FROM posts_fts WHERE pk = old.pk;
            INSERT INTO posts_fts (pk, caption, original_hashtags, owner_username, shortcode, ai_summary, ai_tags, ai_category)
            VALUES (
                new.pk,
                REPLACE(REPLACE(REPLACE(REPLACE(COALESCE(new.caption, ''), 'ي', 'ی'), 'ك', 'ک'), char(8204), ' '), 'ة', 'ه'),
                REPLACE(REPLACE(REPLACE(REPLACE(COALESCE(new.original_hashtags, ''), 'ي', 'ی'), 'ك', 'ک'), char(8204), ' '), 'ة', 'ه'),
                COALESCE(new.owner_username, ''),
                COALESCE(new.shortcode, ''),
                REPLACE(REPLACE(REPLACE(REPLACE(COALESCE(new.ai_summary, '') || ' ' || COALESCE(new.transcript, ''), 'ي', 'ی'), 'ك', 'ک'), char(8204), ' '), 'ة', 'ه'),
                REPLACE(REPLACE(REPLACE(REPLACE(COALESCE(new.ai_tags, ''), 'ي', 'ی'), 'ك', 'ک'), char(8204), ' '), 'ة', 'ه'),
                REPLACE(REPLACE(REPLACE(REPLACE(COALESCE(new.ai_category, ''), 'ي', 'ی'), 'ك', 'ک'), char(8204), ' '), 'ة', 'ه')
            );
        END;
        """)

        fts_norm_check = cursor.execute("SELECT value FROM app_settings WHERE key = 'fts_persian_normalized_v1'").fetchone()
        fts_count = cursor.execute("SELECT COUNT(*) FROM posts_fts").fetchone()[0]
        posts_count = cursor.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
        if (not fts_norm_check) or (fts_count == 0 and posts_count > 0):
            cursor.execute("DELETE FROM posts_fts")
            cursor.execute("""
            INSERT INTO posts_fts (pk, caption, original_hashtags, owner_username, shortcode, ai_summary, ai_tags, ai_category)
            SELECT pk,
                   REPLACE(REPLACE(REPLACE(REPLACE(COALESCE(caption, ''), 'ي', 'ی'), 'ك', 'ک'), char(8204), ' '), 'ة', 'ه'),
                   REPLACE(REPLACE(REPLACE(REPLACE(COALESCE(original_hashtags, ''), 'ي', 'ی'), 'ك', 'ک'), char(8204), ' '), 'ة', 'ه'),
                   COALESCE(owner_username, ''),
                   COALESCE(shortcode, ''),
                   REPLACE(REPLACE(REPLACE(REPLACE(COALESCE(ai_summary, ''), 'ي', 'ی'), 'ك', 'ک'), char(8204), ' '), 'ة', 'ه'),
                   REPLACE(REPLACE(REPLACE(REPLACE(COALESCE(ai_tags, ''), 'ي', 'ی'), 'ك', 'ک'), char(8204), ' '), 'ة', 'ه'),
                   REPLACE(REPLACE(REPLACE(REPLACE(COALESCE(ai_category, ''), 'ي', 'ی'), 'ك', 'ک'), char(8204), ' '), 'ة', 'ه')
            FROM posts
            """)
            cursor.execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES ('fts_persian_normalized_v1', '1')")
    except sqlite3.OperationalError:
        pass

    # Custom Categories and Folders
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS custom_categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        folder_name TEXT NOT NULL,
        description TEXT,
        color TEXT DEFAULT '#8b5cf6',
        created_at INTEGER NOT NULL
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS post_custom_categories (
        post_pk TEXT NOT NULL,
        category_id INTEGER NOT NULL,
        added_at INTEGER NOT NULL,
        PRIMARY KEY(post_pk, category_id),
        FOREIGN KEY(post_pk) REFERENCES posts(pk) ON DELETE CASCADE,
        FOREIGN KEY(category_id) REFERENCES custom_categories(id) ON DELETE CASCADE
    )
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pcc_cat ON post_custom_categories(category_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pcc_post ON post_custom_categories(post_pk)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_posts_status_time ON posts(status, CAST(COALESCE(saved_at, liked_at, taken_at) AS INTEGER) DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_files_pk ON media_files(post_pk, media_index)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_files_sha256 ON media_files(sha256)")

    conn.commit()
    conn.close()
    # One-time migration/repair; do not re-run heavy scans on every startup
    if not get_setting('persian_encodings_repaired_v2'):
        repair_persian_encodings()
        set_setting('persian_encodings_repaired_v2', '1')

def resolve_media_path(file_path: str | Path, base_dir: Path = None) -> Path:
    """
    Resolves a stored file_path (relative or absolute) against base_dir (defaults to DATA_DIR).
    Guarantees portable resolution even if the archive was moved across folders or drives.
    """
    if not file_path:
        return Path("")
    target_base = (base_dir or DATA_DIR).resolve()
    p = Path(file_path)
    if p.is_absolute():
        if p.exists():
            return p
        # Attempt to map from media/canonical_files part
        parts = p.parts
        if 'media' in parts:
            idx = parts.index('media')
            candidate = target_base.joinpath(*parts[idx:])
            if candidate.exists():
                return candidate
        return p
    return target_base / p

def to_relative_media_path(path: str | Path, base_dir: Path = None) -> str:
    """
    Converts an absolute Path into a forward-slash relative string from DATA_DIR.
    """
    target_base = (base_dir or DATA_DIR).resolve()
    p = Path(path).resolve()
    try:
        return p.relative_to(target_base).as_posix()
    except ValueError:
        return str(path)

def sync_fts_index():
    """Manually re-indexes all posts in the FTS5 virtual table with full Persian/Arabic normalization."""
    conn = get_db()
    try:
        with conn:
            conn.execute("DELETE FROM posts_fts")
            conn.execute("""
            INSERT INTO posts_fts (pk, caption, original_hashtags, owner_username, shortcode, ai_summary, ai_tags, ai_category)
            SELECT pk,
                   REPLACE(REPLACE(REPLACE(REPLACE(COALESCE(caption, ''), 'ي', 'ی'), 'ك', 'ک'), char(8204), ' '), 'ة', 'ه'),
                   REPLACE(REPLACE(REPLACE(REPLACE(COALESCE(original_hashtags, ''), 'ي', 'ی'), 'ك', 'ک'), char(8204), ' '), 'ة', 'ه'),
                   COALESCE(owner_username, ''),
                   COALESCE(shortcode, ''),
                   REPLACE(REPLACE(REPLACE(REPLACE(COALESCE(ai_summary, '') || ' ' || COALESCE(transcript, ''), 'ي', 'ی'), 'ك', 'ک'), char(8204), ' '), 'ة', 'ه'),
                   REPLACE(REPLACE(REPLACE(REPLACE(COALESCE(ai_tags, ''), 'ي', 'ی'), 'ك', 'ک'), char(8204), ' '), 'ة', 'ه'),
                   REPLACE(REPLACE(REPLACE(REPLACE(COALESCE(ai_category, ''), 'ي', 'ی'), 'ك', 'ک'), char(8204), ' '), 'ة', 'ه')
            FROM posts
            """)
            conn.execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES ('fts_persian_normalized_v1', '1')")
    finally:
        conn.close()

def get_setting(key: str, default: str = None) -> str:
    conn = get_db()
    try:
        row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
        return row['value'] if row and row['value'] is not None else default
    finally:
        conn.close()

def set_setting(key: str, value: str):
    conn = get_db()
    try:
        with conn:
            conn.execute("INSERT INTO app_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                         (key, str(value) if value is not None else ''))
    finally:
        conn.close()

def get_daily_download_limit() -> int:
    val = get_setting('daily_download_limit', '50000')
    try:
        return max(10, min(1000000, int(val)))
    except (ValueError, TypeError):
        return 50000

def get_proxies() -> list:
    raw = get_setting('proxies', '') or ''
    # lines or comma separated
    proxies = []
    for line in re.split(r'[\r\n,]+', raw):
        item = line.strip()
        if item and not item.startswith('#'):
            if not item.startswith(('http://', 'https://', 'socks5://', 'socks5h://', 'socks4://')):
                item = 'http://' + item
            proxies.append(item)
    return proxies

def get_download_delay_range() -> tuple:
    proxies = get_proxies()
    min_d = get_setting('download_delay_min')
    max_d = get_setting('download_delay_max')
    try:
        if min_d and max_d:
            return float(min_d), float(max_d)
    except (ValueError, TypeError):
        pass
    if proxies:
        return (1.0, 3.0)
    return (4.0, 10.0)

def get_download_concurrency() -> int:
    val = get_setting('download_concurrency', '1')
    try:
        return max(1, min(10, int(val)))
    except (ValueError, TypeError):
        return 1

def rebase_media_paths(target_dir=None):
    """
    Self-healing: if an archive folder was moved, copied, or opened from another path,
    re-anchors media_files paths to the current DATA_DIR canonical location.
    """
    base_dir = (target_dir or DATA_DIR).resolve()
    canonical_root = base_dir / "media" / "canonical_files"
    if not canonical_root.is_dir():
        return 0
        
    conn = get_db()
    updates = []
    try:
        rows = conn.execute("SELECT id, post_pk, file_path, media_index FROM media_files").fetchall()
        for row in rows:
            path_str = row['file_path']
            if not path_str or os.path.exists(path_str):
                continue
            # Try finding the file under canonical_root / post_pk / filename
            original_filename = Path(path_str).name
            expected_file = canonical_root / row['post_pk'] / original_filename
            if expected_file.is_file():
                updates.append((str(expected_file), row['id']))
            else:
                # Check if any file in post folder matches
                post_dir = canonical_root / row['post_pk']
                if post_dir.is_dir():
                    candidates = list(post_dir.glob(f"*_{row['post_pk']}_{row['media_index'] + 1}.*"))
                    if candidates and candidates[0].is_file():
                        updates.append((str(candidates[0]), row['id']))
                        
        if updates:
            with conn:
                conn.executemany("UPDATE media_files SET file_path = ? WHERE id = ?", updates)
        return len(updates)
    except Exception:
        return 0
    finally:
        conn.close()

def recover_orphans():
    """
    Resets any stuck _PENDING statuses to their previous safe state,
    assuming the script crashed during execution.
    """
    conn = get_db()
    cursor = conn.cursor()
    now = int(time.time())
    
    cursor.execute("""
        UPDATE posts 
        SET status = 'DISCOVERED', status_updated_at = ? 
        WHERE status = 'DOWNLOAD_PENDING'
    """, (now,))
    
    cursor.execute("""
        UPDATE posts 
        SET status = 'DOWNLOAD_OK', status_updated_at = ? 
        WHERE status = 'ANALYSIS_PENDING'
    """, (now,))
    
    conn.commit()
    conn.close()

def recover_jobs():
    conn = get_db()
    conn.execute("UPDATE jobs SET status = 'INTERRUPTED', message = 'Application stopped during this job', updated_at = ? WHERE status IN ('QUEUED', 'RUNNING')", (int(time.time()),))
    conn.commit()
    conn.close()

def get_instagram_pause():
    conn = get_db()
    row = conn.execute("SELECT paused_reason FROM instagram_control WHERE id = 1").fetchone()
    conn.close()
    return row['paused_reason'] if row else None

def pause_instagram(reason):
    conn = get_db()
    conn.execute("UPDATE instagram_control SET paused_reason = ? WHERE id = 1", (str(reason)[:500],))
    conn.commit()
    conn.close()

def clear_instagram_pause():
    conn = get_db()
    conn.execute("UPDATE instagram_control SET paused_reason = NULL WHERE id = 1")
    conn.commit()
    conn.close()

def get_pagination_state():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT historical_scan_cursor, recent_scan_cursor, last_seen_newest_pk, pending_newest_pk, historical_complete FROM pagination_state WHERE id = 1")
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else {'historical_scan_cursor': None, 'last_seen_newest_pk': None, 'pending_newest_pk': None}

def bind_archive_account(account_id):
    if not account_id:
        raise ValueError("Instagram session has no account ID; log in again")
    conn = get_db()
    try:
        with conn:
            row = conn.execute("SELECT account_id FROM archive_account WHERE id=1").fetchone()
            if row and row['account_id'] != str(account_id):
                raise ValueError("This archive belongs to another Instagram account; choose a separate storage folder")
            conn.execute("INSERT OR IGNORE INTO archive_account (id, account_id) VALUES (1, ?)", (str(account_id),))
    finally:
        conn.close()

def save_discovery_page(posts, mode, next_cursor, pending_head, finished, checked, source="saved"):
    """Commit discovered posts and the matching checkpoint together."""
    conn = get_db()
    try:
        with conn:
            now = int(time.time())
            pks = [p['pk'] for p in posts]
            existing_pks = set()
            if pks:
                placeholders = ','.join('?' for _ in pks)
                existing_pks = {r[0] for r in conn.execute(f"SELECT pk FROM posts WHERE pk IN ({placeholders})", pks).fetchall()}
            inserted = 0
            for p in posts:
                is_saved = 1 if (source in ('saved', 'all') or p.get('is_saved')) else 0
                is_liked = 1 if (source in ('liked', 'all') or p.get('is_liked')) else 0
                conn.execute("""INSERT INTO posts
                    (pk, shortcode, media_type, owner_username, owner_id, caption, original_hashtags, original_tagged_users,
                     taken_at, saved_at, liked_at, is_saved, is_liked, status, status_updated_at, carousel_media_count, retry_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'DISCOVERED', ?, ?, 0)
                    ON CONFLICT(pk) DO UPDATE SET
                      is_saved = CASE WHEN excluded.is_saved=1 THEN 1 ELSE posts.is_saved END,
                      is_liked = CASE WHEN excluded.is_liked=1 THEN 1 ELSE posts.is_liked END,
                      saved_at = COALESCE(excluded.saved_at, posts.saved_at),
                      liked_at = COALESCE(excluded.liked_at, posts.liked_at)
                    """,
                    (p['pk'], p['shortcode'], p['media_type'], p['owner_username'], p.get('owner_id'),
                     p['caption'], p.get('original_hashtags', ''), p.get('original_tagged_users', '[]'), p['taken_at'],
                     p.get('saved_at'), p.get('liked_at'), is_saved, is_liked,
                     now, p.get('carousel_media_count', 0)))
                if p['pk'] not in existing_pks:
                    inserted += 1
            column = 'recent_scan_cursor' if mode == 'recent' else 'historical_scan_cursor'
            conn.execute(f"UPDATE pagination_state SET {column}=? WHERE id=1", (None if finished else next_cursor,))
            if mode == 'history' and finished:
                conn.execute("UPDATE pagination_state SET historical_complete=1 WHERE id=1")
            if mode == 'recent':
                if pending_head:
                    conn.execute("UPDATE pagination_state SET pending_newest_pk=COALESCE(pending_newest_pk, ?) WHERE id=1", (pending_head,))
                if finished:
                    conn.execute("UPDATE pagination_state SET last_seen_newest_pk=COALESCE(pending_newest_pk,last_seen_newest_pk), pending_newest_pk=NULL WHERE id=1")
            return inserted
    finally:
        conn.close()

def record_sync(job_id, mode, **changes):
    allowed = {'pages', 'discovered', 'checked', 'duplicates', 'outcome', 'error', 'finished_at'}
    if set(changes) - allowed:
        raise ValueError('Invalid sync field')
    conn = get_db()
    try:
        with conn:
            conn.execute("INSERT OR IGNORE INTO sync_runs (id, mode, started_at, outcome) VALUES (?, ?, ?, 'RUNNING')", (job_id, mode, int(time.time())))
            for key, value in changes.items():
                if key in {'pages', 'discovered', 'checked', 'duplicates'}:
                    conn.execute(f"UPDATE sync_runs SET {key}={key}+? WHERE id=?", (value, job_id))
                else:
                    conn.execute(f"UPDATE sync_runs SET {key}=? WHERE id=?", (value, job_id))
    finally:
        conn.close()

def record_sync_download(sync_id, success=0, failed=0):
    if not sync_id:
        return
    conn = get_db()
    try:
        with conn:
            conn.execute("UPDATE sync_runs SET downloaded=downloaded+?, download_failed=download_failed+? WHERE id=?",
                         (success, failed, sync_id))
    finally:
        conn.close()

def published_at(value):
    try:
        return datetime.fromtimestamp(int(value), timezone.utc).isoformat() if value is not None else None
    except (TypeError, ValueError, OverflowError):
        return str(value) if value else None

def update_historical_scan_cursor(cursor_str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE pagination_state SET historical_scan_cursor = ? WHERE id = 1", (cursor_str,))
    conn.commit()
    conn.close()

def update_last_seen_newest_pk(pk):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE pagination_state SET last_seen_newest_pk = ? WHERE id = 1", (pk,))
    conn.commit()
    conn.close()

def update_pending_newest_pk(pk):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE pagination_state SET pending_newest_pk = ? WHERE id = 1", (pk,))
    conn.commit()
    conn.close()

def insert_post(post_data, status="DISCOVERED"):
    conn = get_db()
    cursor = conn.cursor()
    now = int(time.time())
    cursor.execute("""
    INSERT OR IGNORE INTO posts 
    (pk, shortcode, media_type, owner_username, owner_id, caption, original_hashtags, taken_at, status, status_updated_at, carousel_media_count, retry_count)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
    """, (
        post_data['pk'],
        post_data['shortcode'],
        post_data['media_type'],
        post_data['owner_username'],
        post_data.get('owner_id'),
        post_data['caption'],
        post_data.get('original_hashtags', ''),
        post_data['taken_at'],
        status,
        now,
        post_data.get('carousel_media_count', 0)
    ))
    # Return true if row was actually inserted
    inserted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return inserted

def post_exists(pk):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM posts WHERE pk = ?", (pk,))
    exists = cursor.fetchone() is not None
    conn.close()
    return exists

def existing_pks(pks):
    if not pks:
        return set()
    conn = get_db()
    placeholders = ','.join('?' for _ in pks)
    rows = conn.execute(f"SELECT pk FROM posts WHERE pk IN ({placeholders})", tuple(pks)).fetchall()
    conn.close()
    return {row['pk'] for row in rows}

def insert_posts(posts):
    if not posts:
        return 0
    conn = get_db()
    now = int(time.time())
    try:
        cursor = conn.executemany("""
            INSERT OR IGNORE INTO posts
            (pk, shortcode, media_type, owner_username, owner_id, caption, original_hashtags, taken_at, status, status_updated_at, carousel_media_count, retry_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'DISCOVERED', ?, ?, 0)
        """, [(
            p['pk'], p['shortcode'], p['media_type'], p['owner_username'], p.get('owner_id'),
            p['caption'], p.get('original_hashtags', ''), p['taken_at'], now, p.get('carousel_media_count', 0)
        ) for p in posts])
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()

def update_post_status(pk, status):
    conn = get_db()
    cursor = conn.cursor()
    now = int(time.time())
    cursor.execute("UPDATE posts SET status = ?, status_updated_at = ? WHERE pk = ?", (status, now, pk))
    conn.commit()
    conn.close()

def get_retry_count(pk):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT retry_count FROM posts WHERE pk = ?", (pk,))
    row = cursor.fetchone()
    conn.close()
    return row['retry_count'] if row else 0

def increment_retry_count_and_status(pk, max_retries=3):
    """
    Increments retry_count. If >= max_retries, sets status to DOWNLOAD_FAILED.
    Otherwise sets status back to DISCOVERED for next run.
    """
    conn = get_db()
    cursor = conn.cursor()
    now = int(time.time())
    
    current = get_retry_count(pk)
    new_count = current + 1
    new_status = 'DOWNLOAD_FAILED' if new_count >= max_retries else 'DISCOVERED'
    
    cursor.execute("UPDATE posts SET retry_count = ?, status = ?, status_updated_at = ? WHERE pk = ?", (new_count, new_status, now, pk))
    conn.commit()
    conn.close()

def reset_failed_posts():
    """
    Resets all DOWNLOAD_FAILED posts back to DISCOVERED and clears their retry_count.
    """
    conn = get_db()
    cursor = conn.cursor()
    now = int(time.time())
    cursor.execute("UPDATE posts SET status = 'DISCOVERED', retry_count = 0, status_updated_at = ? WHERE status = 'DOWNLOAD_FAILED'", (now,))
    reset_count = cursor.rowcount
    conn.commit()
    conn.close()
    return reset_count

def update_ai_analysis(pk, summary, categories, tags, confidence="MEDIUM", transcript=None):
    conn = get_db()
    cursor = conn.cursor()
    now = int(time.time())
    cursor.execute("""
        UPDATE posts 
        SET ai_summary = ?, ai_category = ?, ai_categories = ?, ai_tags = ?, ai_confidence = ?,
            transcript = COALESCE(?, transcript),
            ai_error = NULL, ai_retry_count = 0, ai_next_retry_at = 0, status = ?, status_updated_at = ?
        WHERE pk = ?
    """, (summary, categories[0], json.dumps(categories, ensure_ascii=False), tags, confidence,
          transcript,
          'REVIEW_REQUIRED' if confidence == 'LOW' or categories[0] == 'Other' else 'APPROVED', now, pk))
    conn.commit()
    conn.close()

def fail_ai_analysis(pk, error):
    conn = get_db()
    try:
        with conn:
            row = conn.execute("SELECT COALESCE(ai_retry_count,0) FROM posts WHERE pk=?", (pk,)).fetchone()
            count = (row[0] if row else 0) + 1
            status = 'ANALYSIS_FAILED' if count >= 3 else 'DOWNLOAD_OK'
            conn.execute("UPDATE posts SET status=?, ai_error=?, ai_retry_count=?, ai_next_retry_at=?, status_updated_at=? WHERE pk=?",
                         (status, str(error)[:200], count, int(time.time()) + min(3600, 60 * 2 ** count), int(time.time()), pk))
    finally:
        conn.close()

def mark_as_organized(pk, category_path):
    conn = get_db()
    cursor = conn.cursor()
    now = int(time.time())
    cursor.execute("""
        UPDATE posts 
        SET status = 'ORGANIZED', ai_category = ?, export_category = ?, status_updated_at = ?
        WHERE pk = ?
    """, (category_path, category_path, now, pk))
    conn.commit()
    conn.close()

def add_media_file(post_pk, file_path, index=0):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO media_files (post_pk, file_path, media_index)
    VALUES (?, ?, ?)
    ON CONFLICT(post_pk, media_index) DO UPDATE SET file_path=excluded.file_path
    """, (post_pk, file_path, index))
    conn.commit()
    conn.close()

def complete_download(post_pk, files):
    conn = get_db()
    try:
        with conn:
            conn.execute("DELETE FROM media_files WHERE post_pk=?", (post_pk,))
            media_entries = []
            import hashlib
            for path, index in files:
                rel = to_relative_media_path(path)
                abs_path = resolve_media_path(path)
                size_bytes = None
                sha256_hash = None
                try:
                    if abs_path.is_file():
                        size_bytes = abs_path.stat().st_size
                        h = hashlib.sha256()
                        with open(abs_path, 'rb') as f:
                            while chunk := f.read(65536):
                                h.update(chunk)
                        sha256_hash = h.hexdigest()
                except OSError:
                    pass
                media_entries.append((post_pk, rel, index, size_bytes, sha256_hash))

            conn.executemany("""
                INSERT INTO media_files (post_pk, file_path, media_index, size_bytes, sha256)
                VALUES (?, ?, ?, ?, ?)
            """, media_entries)
            conn.execute("""UPDATE posts SET status=CASE
                WHEN repair_from_status IN ('APPROVED','ORGANIZED') AND ai_category IS NOT NULL THEN 'APPROVED'
                WHEN repair_from_status='REVIEW_REQUIRED' THEN 'REVIEW_REQUIRED'
                ELSE 'DOWNLOAD_OK' END,
                repair_from_status=NULL, retry_count=0, status_updated_at=? WHERE pk=?""",
                (int(time.time()), post_pk))
    finally:
        conn.close()

def mark_media_missing(pk, status):
    conn = get_db()
    try:
        with conn:
            new_status = 'MISSING_LOCAL' if pk.startswith('local-') else 'DISCOVERED'
            conn.execute("UPDATE posts SET repair_from_status=?, status=?, status_updated_at=? WHERE pk=?",
                         (status, new_status, int(time.time()), pk))
    finally:
        conn.close()

def get_existing_categories():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT ai_category FROM posts WHERE ai_category IS NOT NULL AND status IN ('ANALYSIS_OK', 'APPROVED', 'ORGANIZED')")
    rows = cursor.fetchall()
    conn.close()
    return [r['ai_category'] for r in rows if r['ai_category']]

def get_categories_summary():
    conn = get_db()
    try:
        # 1. Instagram export collections
        collections = [
            {'name': r['name'], 'count': r['count'], 'type': 'collection'}
            for r in conn.execute("SELECT name, COUNT(*) AS count FROM export_collections GROUP BY name ORDER BY count DESC")
        ]
        # 2. AI categories
        ai_cats = [
            {'name': r['ai_category'], 'count': r['count'], 'type': 'ai'}
            for r in conn.execute("""
                SELECT ai_category, COUNT(*) AS count FROM posts 
                WHERE ai_category IS NOT NULL AND ai_category != '' 
                AND status IN ('ANALYSIS_OK', 'APPROVED', 'ORGANIZED')
                GROUP BY ai_category ORDER BY count DESC
            """)
        ]
        return {
            'collections': collections,
            'ai_categories': ai_cats
        }
    finally:
        conn.close()

def fix_mojibake_text(text: str) -> str:
    if not text or not isinstance(text, str):
        return text or ""
    if any(0x80 <= ord(c) <= 0xFF for c in text):
        try:
            return text.encode('latin1').decode('utf-8')
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
        # Handle mixed strings where valid unicode coexists with mojibake chunks
        def _fix_chunk(m):
            try:
                return m.group(0).encode('latin1').decode('utf-8')
            except (UnicodeEncodeError, UnicodeDecodeError):
                return m.group(0)
        return re.sub(r'[\u0080-\u00FF]{2,}', _fix_chunk, text)
    return text

def repair_persian_encodings(conn=None):
    close_when_done = False
    if conn is None:
        conn = get_db()
        close_when_done = True
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT pk, caption, original_hashtags, owner_username FROM posts WHERE caption IS NOT NULL OR original_hashtags IS NOT NULL OR owner_username IS NOT NULL")
        rows = cursor.fetchall()
        updates = []
        for r in rows:
            pk = r['pk']
            orig_caption = r['caption'] or ""
            orig_tags = r['original_hashtags'] or ""
            orig_user = r['owner_username'] or ""
            
            fixed_caption = fix_mojibake_text(orig_caption)
            fixed_tags = fix_mojibake_text(orig_tags)
            fixed_user = fix_mojibake_text(orig_user)
            
            if fixed_caption != orig_caption or fixed_tags != orig_tags or fixed_user != orig_user:
                updates.append((fixed_caption, fixed_tags, fixed_user, pk))
                
        if updates:
            cursor.executemany("UPDATE posts SET caption=?, original_hashtags=?, owner_username=? WHERE pk=?", updates)
            conn.commit()
            
        cursor.execute("SELECT DISTINCT name FROM export_collections")
        coll_rows = cursor.fetchall()
        for cr in coll_rows:
            old_name = cr['name']
            new_name = fix_mojibake_text(old_name)
            if new_name != old_name:
                cursor.execute("UPDATE OR IGNORE export_collections SET name=? WHERE name=?", (new_name, old_name))
                cursor.execute("DELETE FROM export_collections WHERE name=?", (old_name,))
        conn.commit()
    except Exception as e:
        print(f"Error repairing encodings: {e}")
    finally:
        if close_when_done:
            conn.close()

def create_custom_category(name: str, folder_name: str = None, description: str = '', color: str = '#8b5cf6') -> dict:
    name = name.strip()
    if not name:
        raise ValueError("Category name cannot be empty")
    folder = (folder_name or name).strip()
    folder = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '-', folder).strip()[:80] or "Category"
    conn = get_db()
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO custom_categories (name, folder_name, description, color, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (name, folder, description or '', color or '#8b5cf6', int(time.time())))
            cat_id = cursor.lastrowid
            return {"id": cat_id, "name": name, "folder_name": folder, "description": description, "color": color, "count": 0}
    finally:
        conn.close()

def get_custom_categories() -> list:
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT c.*, COUNT(pcc.post_pk) AS count
            FROM custom_categories c
            LEFT JOIN post_custom_categories pcc ON c.id = pcc.category_id
            GROUP BY c.id
            ORDER BY c.name COLLATE NOCASE ASC
        """)
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()

def update_custom_category(category_id: int, name: str = None, folder_name: str = None, description: str = None, color: str = None):
    conn = get_db()
    try:
        with conn:
            cursor = conn.cursor()
            fields = []
            params = []
            if name is not None:
                name = name.strip()
                if not name:
                    raise ValueError("Category name cannot be empty")
                fields.append("name = ?")
                params.append(name)
            if folder_name is not None:
                folder = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '-', folder_name).strip()[:80] or "Category"
                fields.append("folder_name = ?")
                params.append(folder)
            if description is not None:
                fields.append("description = ?")
                params.append(description)
            if color is not None:
                fields.append("color = ?")
                params.append(color)
            if not fields:
                return
            params.append(category_id)
            cursor.execute(f"UPDATE custom_categories SET {', '.join(fields)} WHERE id = ?", tuple(params))
    finally:
        conn.close()

def delete_custom_category(category_id: int):
    conn = get_db()
    try:
        with conn:
            conn.execute("DELETE FROM post_custom_categories WHERE category_id = ?", (category_id,))
            conn.execute("DELETE FROM custom_categories WHERE id = ?", (category_id,))
    finally:
        conn.close()

def assign_posts_to_custom_category(category_id: int, post_pks: list) -> int:
    conn = get_db()
    now = int(time.time())
    try:
        with conn:
            records = [(pk, category_id, now) for pk in post_pks if pk]
            conn.executemany("INSERT OR IGNORE INTO post_custom_categories (post_pk, category_id, added_at) VALUES (?, ?, ?)", records)
            return len(records)
    finally:
        conn.close()

def remove_posts_from_custom_category(category_id: int, post_pks: list) -> int:
    conn = get_db()
    try:
        with conn:
            placeholders = ','.join('?' for _ in post_pks)
            cursor = conn.cursor()
            cursor.execute(f"DELETE FROM post_custom_categories WHERE category_id = ? AND post_pk IN ({placeholders})", (category_id, *post_pks))
            return cursor.rowcount
    finally:
        conn.close()

def get_post_custom_categories(post_pk: str) -> list:
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT c.id, c.name, c.folder_name, c.color
            FROM custom_categories c
            JOIN post_custom_categories pcc ON c.id = pcc.category_id
            WHERE pcc.post_pk = ?
            ORDER BY c.name ASC
        """, (post_pk,))
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()

def get_all_posts_custom_categories(post_pks: list) -> dict:
    if not post_pks:
        return {}
    conn = get_db()
    try:
        cursor = conn.cursor()
        placeholders = ','.join('?' for _ in post_pks)
        cursor.execute(f"""
            SELECT pcc.post_pk, c.id, c.name, c.folder_name, c.color
            FROM custom_categories c
            JOIN post_custom_categories pcc ON c.id = pcc.category_id
            WHERE pcc.post_pk IN ({placeholders})
            ORDER BY c.name ASC
        """, tuple(post_pks))
        result = {pk: [] for pk in post_pks}
        for r in cursor.fetchall():
            result[r['post_pk']].append({
                "id": r['id'],
                "name": r['name'],
                "folder_name": r['folder_name'],
                "color": r['color']
            })
        return result
    finally:
        conn.close()
