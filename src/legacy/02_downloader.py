import os
import time
import random
import shutil
import cv2
from PIL import Image
from pathlib import Path
from instagrapi import Client
from instagrapi.exceptions import (
    ClientError, RateLimitError, FeedbackRequired, 
    PleaseWaitFewMinutes, ClientThrottledError, ChallengeRequired
)
import database

SESSION_FILE = "session.json"
MEDIA_DIR = Path("archive/media/canonical_files")
BATCH_SIZE = 50

def get_client():
    cl = Client()
    if os.path.exists(SESSION_FILE):
        cl.load_settings(SESSION_FILE)
    else:
        raise SystemExit("سشن یافت نشد. لطفاً ابتدا 00_login.py را اجرا کنید.")
    cl.get_timeline_feed()
    return cl

def verify_media_file(file_path, original_suffix):
    """
    Verifies that the downloaded file is actually decodable.
    original_suffix is used because file_path has a .part suffix.
    """
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

def download_post_media(cl, pk, media_type):
    out_dir = MEDIA_DIR / pk
    out_dir.mkdir(parents=True, exist_ok=True)
    
    temp_dir = out_dir / "temp_parts"
    temp_dir.mkdir(exist_ok=True)
    
    paths = []
    try:
        if media_type == 1:  # photo
            p = cl.photo_download(pk, folder=temp_dir)
            paths.append(p)
        elif media_type == 2:  # video / reel
            p = cl.video_download(pk, folder=temp_dir)
            paths.append(p)
        elif media_type == 8:  # carousel/album
            ps = cl.album_download(pk, folder=temp_dir)
            paths.extend(ps)
            
        final_paths = []
        for i, p in enumerate(paths):
            temp_file = Path(p)
            original_suffix = temp_file.suffix
            
            part_file = temp_file.with_suffix(original_suffix + ".part")
            shutil.move(str(temp_file), str(part_file))
            
            if not verify_media_file(part_file, original_suffix):
                raise ValueError(f"فایل نامعتبر یا خراب است: {part_file.name}")
                
            final_file = out_dir / temp_file.name
            shutil.move(str(part_file), str(final_file))
            final_paths.append((str(final_file), i))
            
        shutil.rmtree(temp_dir, ignore_errors=True)
        
        if not final_paths:
            raise ValueError(f"هیچ فایلی برای پست {pk} دانلود نشد!")
            
        return final_paths
        
    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise e

def main():
    database.init_db()
    conn = database.get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT pk, media_type, carousel_media_count FROM posts WHERE status = 'DISCOVERED' LIMIT ?", (BATCH_SIZE,))
    todo = cursor.fetchall()
    conn.close()
    
    if not todo:
        print("هیچ پستی برای دانلود یافت نشد.")
        return
        
    cl = get_client()
    print(f"شروع دانلود برای {len(todo)} پست...")
    
    for row in todo:
        pk = row['pk']
        media_type = row['media_type']
        expected_assets = row['carousel_media_count'] or 1
        if media_type == 8 and expected_assets == 0:
            expected_assets = 1 # Fallback just in case
            
        database.update_post_status(pk, 'DOWNLOAD_PENDING')
        
        try:
            print(f"در حال دانلود {pk}...")
            final_paths = download_post_media(cl, pk, media_type)
            
            if len(final_paths) < expected_assets:
                raise ValueError(f"تعداد فایل‌های دانلود شده ({len(final_paths)}) کمتر از حد انتظار ({expected_assets}) است.")
                
            for path, index in final_paths:
                database.add_media_file(pk, path, index)
                
            database.update_post_status(pk, 'DOWNLOAD_OK')
            print(f"موفقیت: {pk}")
            
        except (RateLimitError, FeedbackRequired, PleaseWaitFewMinutes, ClientThrottledError) as e:
            print(f"محدودیت اینستاگرام ({e})! توقف کامل.")
            database.update_post_status(pk, 'DISCOVERED')
            break
        except ChallengeRequired as e:
            print(f"اینستاگرام Challenge (تاییدیه) درخواست کرده است! {e}")
            database.update_post_status(pk, 'DISCOVERED')
            break
        except Exception as e:
            print(f"خطا در دانلود {pk}: {e}")
            database.increment_retry_count_and_status(pk, max_retries=3)
            
        time.sleep(random.uniform(2, 5))
        
    print("پایان عملیات دانلود این دوره.")

if __name__ == "__main__":
    main()
