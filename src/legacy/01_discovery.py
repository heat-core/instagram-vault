import os
import time
import random
from instagrapi import Client
from instagrapi.exceptions import (
    ClientError, LoginRequired, RateLimitError, FeedbackRequired, 
    PleaseWaitFewMinutes, ClientThrottledError, ChallengeRequired
)
import database

SESSION_FILE = "session.json"
MAX_PAGES_PER_RUN = 5
DELAY_BETWEEN_PAGES = (3, 7)

def get_client():
    cl = Client()
    if os.path.exists(SESSION_FILE):
        cl.load_settings(SESSION_FILE)
    else:
        raise SystemExit("سشن یافت نشد. لطفاً ابتدا 00_login.py را اجرا کنید.")
    
    try:
        cl.get_timeline_feed()
    except LoginRequired:
        raise SystemExit("سشن باطل شده است. دوباره لاگین کنید.")
    
    return cl

def discover_saved_posts():
    database.init_db()
    cl = get_client()
    
    pagination = database.get_pagination_state()
    historical_cursor = pagination['historical_scan_cursor']
    last_seen_pk = pagination['last_seen_newest_pk']
    pending_pk = pagination['pending_newest_pk']
    
    pages_fetched = 0
    new_items_found = 0
    first_pk_in_run = None
    
    print("شروع واکشی لیست ذخیره‌شده‌ها...")
    if last_seen_pk:
        print(f"Incremental Scan Mode (Target PK to stop: {last_seen_pk})")
        if pending_pk:
            print(f"Pending PK from previous interrupted scan: {pending_pk}")
    else:
        print("Historical Scan Mode (Full Archive)")
        
    while pages_fetched < MAX_PAGES_PER_RUN:
        params = {}
        if historical_cursor:
            params['max_id'] = historical_cursor
            
        try:
            response = cl.private_request("feed/saved/posts/", params=params)
        except (RateLimitError, FeedbackRequired, PleaseWaitFewMinutes, ClientThrottledError) as e:
            print(f"خطای محدودیت/Throttling اینستاگرام: {e}")
            print("اجرا فوراً متوقف شد تا اکانت مسدود نشود. لطفاً تا فردا یا چند ساعت آینده اجرا نکنید.")
            break
        except ChallengeRequired as e:
            print(f"اینستاگرام Challenge (تاییدیه) درخواست کرده است! {e}")
            print("اسکریپت متوقف شد. لاگین مجدد یا حل Challenge روی گوشی نیاز است.")
            break
        except ClientError as e:
            print(f"خطای شبکه/کلاینت: {e}")
            break
            
        items = response.get('items', [])
        if not items:
            print("هیچ آیتم دیگری یافت نشد. (پایان کامل)")
            database.update_historical_scan_cursor(None)
            break
            
        page_new_items = 0
        hit_last_seen = False
        
        for item in items:
            media = item.get('media') or item
            pk = str(media.get('pk'))
            
            if not pk or pk == "None":
                continue
                
            # Grab the very first PK we see if we started from the absolute top
            if first_pk_in_run is None and not historical_cursor:
                first_pk_in_run = pk
                # Save it immediately as pending_pk in case we don't finish
                if pending_pk is None or pending_pk != pk:
                    database.update_pending_newest_pk(pk)
                    pending_pk = pk
                
            # Incremental Scan Check (Stop if we hit ANY known item)
            if database.post_exists(pk):
                print("\n[STOP] به آیتمی رسیدیم که قبلاً در دیتابیس وجود داشت.")
                hit_last_seen = True
                break
                
            carousel_count = media.get("carousel_media_count") or len(media.get("carousel_media", [])) or len(media.get("resources", [])) or 0
            
            post_data = {
                'pk': pk,
                'shortcode': media.get('code'),
                'media_type': media.get('media_type'),
                'owner_username': media.get('user', {}).get('username'),
                'caption': media.get('caption', {}).get('text') if media.get('caption') else "",
                'taken_at': media.get('taken_at'),
                'carousel_media_count': carousel_count
            }
            
            inserted = database.insert_post(post_data)
            if inserted:
                page_new_items += 1
                new_items_found += 1
                
        print(f"صفحه {pages_fetched + 1}: {len(items)} آیتم بررسی شد ({page_new_items} آیتم جدید).")
        
        if hit_last_seen:
            # We successfully bridged the gap to the old archive!
            # We can now safely promote the pending_newest_pk to last_seen_newest_pk
            if pending_pk:
                database.update_last_seen_newest_pk(pending_pk)
                database.update_pending_newest_pk(None)
                print(f"Last Seen PK با موفقیت ارتقا یافت به: {pending_pk}")
            database.update_historical_scan_cursor(None)
            break
            
        if not response.get('more_available'):
            print("به انتهای کامل لیست Saved Posts رسیدیم.")
            database.update_historical_scan_cursor(None)
            # If we reached the end of history, we also successfully bridged the gap
            if pending_pk:
                database.update_last_seen_newest_pk(pending_pk)
                database.update_pending_newest_pk(None)
                print(f"Last Seen PK با موفقیت ارتقا یافت به: {pending_pk}")
            break
            
        historical_cursor = response.get('next_max_id')
        database.update_historical_scan_cursor(historical_cursor)
        
        pages_fetched += 1
        time.sleep(random.uniform(*DELAY_BETWEEN_PAGES))
        
    print(f"عملیات دیسکاوری به پایان رسید. در مجموع {new_items_found} پست جدید پیدا شد.")

if __name__ == "__main__":
    discover_saved_posts()
