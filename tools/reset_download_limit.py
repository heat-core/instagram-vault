import os
import sys
import json
import sqlite3
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

def find_active_db():
    candidates = []
    # 1. Electron preferences file
    appdata = os.environ.get('APPDATA')
    if appdata:
        for folder_name in ['desktop', 'Saved Archive']:
            pref = Path(appdata) / folder_name / 'saved-archive-settings.json'
            if pref.is_file():
                try:
                    data = json.loads(pref.read_text(encoding='utf-8'))
                    d = data.get('dataDir')
                    if d:
                        candidates.append(Path(d) / 'database' / 'library.db')
                except Exception:
                    pass

    # 2. Known standard paths
    candidates.extend([
        Path.cwd() / 'archive' / 'database' / 'library.db',
        Path(__file__).resolve().parent.parent / 'archive' / 'database' / 'library.db'
    ])

    found = []
    for p in candidates:
        try:
            if p.is_file() and p not in found:
                found.append(p)
        except Exception:
            pass
    return found

def reset_db(db_path: Path):
    print(f"\n--- Checking DB: {db_path} ---")
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    # 1. Clear download_events
    try:
        cursor.execute("SELECT COUNT(*) FROM download_events")
        old_events = cursor.fetchone()[0]
        cursor.execute("DELETE FROM download_events")
        print(f"[OK] Cleared {old_events} old download event records. 24h limit is now reset to 0.")
    except Exception as e:
        print(f"[WARN] Error with download_events: {e}")
    
    # 2. Set daily_download_limit to 5000
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        cursor.execute("""
            INSERT INTO app_settings (key, value) VALUES ('daily_download_limit', '5000')
            ON CONFLICT(key) DO UPDATE SET value='5000'
        """)
        print("[OK] Set daily_download_limit to 5000 in app_settings.")
    except Exception as e:
        print(f"[WARN] Error setting app_settings: {e}")

    # 3. Reset failed posts
    try:
        cursor.execute("SELECT COUNT(*) FROM posts WHERE status = 'DOWNLOAD_FAILED'")
        failed_count = cursor.fetchone()[0]
        if failed_count > 0:
            cursor.execute("UPDATE posts SET status = 'DISCOVERED', retry_count = 0 WHERE status = 'DOWNLOAD_FAILED'")
            print(f"[OK] Reset {failed_count} DOWNLOAD_FAILED posts back to DISCOVERED.")
    except Exception as e:
        print(f"[WARN] Error resetting failed posts: {e}")

    # 4. Resume instagram if paused
    try:
        cursor.execute("DELETE FROM app_settings WHERE key = 'instagram_paused_reason'")
        print("[OK] Cleared instagram_paused_reason.")
    except Exception:
        pass
    
    conn.commit()
    conn.close()

def main():
    print("Starting download limit reset...")
    dbs = find_active_db()
    if not dbs:
        print("[ERROR] No active library.db found.")
        return
    for db in dbs:
        try:
            reset_db(db)
        except Exception as e:
            print(f"[ERROR] Failed to update {db}: {e}")
    print("\n[SUCCESS] The application limit has been unlocked! You can now resume downloads.")

if __name__ == '__main__':
    main()
