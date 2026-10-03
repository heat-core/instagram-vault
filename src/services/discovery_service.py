import os
import time
import random
import threading
import re
import json
from instagrapi import Client
from instagrapi.exceptions import (
    ClientError, LoginRequired, RateLimitError, FeedbackRequired, 
    PleaseWaitFewMinutes, ClientThrottledError, ChallengeRequired
)
from .. import database
from .. import session_store
from ..job_manager import manager

SESSION_FILE = os.environ.get("INSTAGRAM_SESSION_FILE", "archive/session.enc")
MAX_PAGES_PER_RUN = 5
DELAY_BETWEEN_PAGES = (3, 7)

class DiscoveryService:
    @staticmethod
    def get_client(job_id: str = None) -> Client:
        paused = database.get_instagram_pause()
        if paused:
            raise RuntimeError(f"Instagram access is paused: {paused}")
        cl = Client()
        if os.path.exists(SESSION_FILE):
            settings = session_store.load_session(SESSION_FILE)
            account_id = session_store.account_id(settings)
            database.bind_archive_account(account_id)
            cl.set_settings(settings)
        else:
            msg = "Session not found. Please login first."
            if job_id: manager.log(job_id, "ERROR", msg)
            raise RuntimeError(msg)
        
        return cl

    @classmethod
    def run_discovery(cls, job_id: str, cancel_event: threading.Event, max_pages: int = MAX_PAGES_PER_RUN, mode: str = "recent", source: str = "saved"):
        database.init_db()
        if mode not in {"recent", "history"}:
            raise ValueError("Invalid discovery mode")
        if source not in {"saved", "liked", "all"}:
            source = "saved"
        database.record_sync(job_id, f"{mode}_{source}")
        pages = found = checked = known_pages = 0
        try:
            cl = cls.get_client(job_id)
            state = database.get_pagination_state()
            if mode == "history" and state["historical_complete"]:
                database.record_sync(job_id, mode, outcome="COMPLETED", finished_at=int(time.time()))
                return {"new_items": 0, "pages_fetched": 0, "complete": True}
            column = "recent_scan_cursor" if mode == "recent" else "historical_scan_cursor"
            cursor = state[column]
            first_recent_page = mode == "recent" and not state["last_seen_newest_pk"] and not cursor
            while pages < max_pages and not cancel_event.is_set():
                source_label = "پست‌های لایک‌شده" if source == "liked" else "پست‌های ذخیره‌شده"
                manager.update_progress(job_id, 10 + 90 * pages / max_pages, f"دریافت صفحه {pages + 1} از {source_label}...")
                endpoint = "feed/liked/" if source == "liked" else "feed/saved/posts/"
                try:
                    response = cl.private_request(endpoint, params={"max_id": cursor} if cursor else {})
                except (LoginRequired, RateLimitError, FeedbackRequired, PleaseWaitFewMinutes, ClientThrottledError, ChallengeRequired, ClientError) as exc:
                    database.pause_instagram(type(exc).__name__)
                    raise RuntimeError(f"Instagram access paused: {type(exc).__name__}") from exc
                items = response.get("items") or []
                if not isinstance(items, list):
                    raise ValueError('Invalid post response from Instagram')
                pages += 1
                known = database.existing_pks([str((item.get("media") or item).get("pk")) for item in items])
                posts = []
                head = None
                for item in items:
                    media = item.get("media") or item
                    pk = media.get("pk")
                    if pk is None:
                        continue
                    pk = str(pk)
                    if not pk.isdigit():
                        continue
                    head = head or pk
                    caption = (media.get("caption") or {}).get("text") or ""
                    owner = media.get("user") or {}
                    raw_tags = media.get('usertags') or item.get('usertags') or media.get('tagged_users') or []
                    raw_tags = raw_tags.get('in') or [] if isinstance(raw_tags, dict) else raw_tags
                    tagged = []
                    for tag in raw_tags if isinstance(raw_tags, list) else []:
                        user = tag.get('user') or tag if isinstance(tag, dict) else {}
                        if not isinstance(user, dict):
                            continue
                        if user.get('username'):
                            tagged.append({'username': user['username'], 'id': str(user['pk']) if user.get('pk') is not None else None})
                    
                    saved_at = item.get("saved_at") or item.get("saved_at_timestamp")
                    liked_at = item.get("taken_at") or int(time.time()) if source == "liked" else None
                    if source == "saved" and not saved_at:
                        saved_at = int(time.time())

                    posts.append({
                        "pk": pk, "shortcode": media.get("code"), "media_type": media.get("media_type"),
                        "owner_username": owner.get("username"),
                        "owner_id": str(owner["pk"]) if owner.get("pk") is not None else None,
                        "caption": caption,
                        "original_hashtags": ", ".join(dict.fromkeys("#" + tag for tag in re.findall(r"(?<!\w)#([\w]+)", caption))),
                        "original_tagged_users": json.dumps(tagged, ensure_ascii=False),
                        "taken_at": media.get("taken_at"),
                        "saved_at": saved_at,
                        "liked_at": liked_at,
                        "is_saved": 1 if source in ("saved", "all") else 0,
                        "is_liked": 1 if source in ("liked", "all") else 0,
                        "carousel_media_count": media.get("carousel_media_count") or len(media.get("carousel_media") or []) or len(media.get("resources") or []) or 0,
                    })
                checked += len(items)
                known_pages = known_pages + 1 if items and not [p for p in posts if p['pk'] not in known] else 0
                next_cursor = response.get("next_max_id") if response.get("more_available") else None
                if response.get("more_available") and not next_cursor:
                    raise ValueError('Saved/liked post page has no continuation cursor')
                finished = not items or not next_cursor or first_recent_page or (mode == "recent" and known_pages >= 2)
                inserted = database.save_discovery_page(posts, mode, next_cursor, head if mode == "recent" and not cursor else None, finished, len(items), source=source)
                if first_recent_page and next_cursor and not state["historical_scan_cursor"] and not state["historical_complete"]:
                    database.update_historical_scan_cursor(next_cursor)
                if first_recent_page and not next_cursor:
                    database.save_discovery_page([], "history", None, None, True, 0, source=source)
                found += inserted
                database.record_sync(job_id, f"{mode}_{source}", pages=1, discovered=inserted, checked=len(items),
                                     duplicates=max(0, sum(str((item.get('media') or item).get('pk')).isdigit() for item in items) - inserted))
                manager.log(job_id, "INFO", f"Page {pages}: {len(items)} checked, {inserted} new")
                if finished:
                    break
                cursor = next_cursor
                if pages < max_pages and not cancel_event.is_set():
                    time.sleep(random.uniform(*DELAY_BETWEEN_PAGES))
            database.record_sync(job_id, f"{mode}_{source}", outcome="CANCELLED" if cancel_event.is_set() else "COMPLETED", finished_at=int(time.time()))
            return {"new_items": found, "pages_fetched": pages, "checked": checked,
                    "has_more": bool(database.get_pagination_state()[column])}
        except Exception as exc:
            database.record_sync(job_id, f"{mode}_{source}", outcome="FAILED", error=type(exc).__name__, finished_at=int(time.time()))
            raise
