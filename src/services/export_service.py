"""Offline reader for Instagram's saved and liked activity export."""

import json
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

from instagrapi.utils.ids import InstagramIdCodec

from .. import database
from ..job_manager import manager


def _clean_text(s):
    if not s or not isinstance(s, str):
        return s or ""
    if any(0x80 <= ord(c) <= 0xFF for c in s):
        try:
            return s.encode('latin1').decode('utf-8')
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
        # Handle mixed strings where valid unicode coexists with mojibake chunks
        def _fix_chunk(m):
            try:
                return m.group(0).encode('latin1').decode('utf-8')
            except (UnicodeEncodeError, UnicodeDecodeError):
                return m.group(0)
        return re.sub(r'[\u0080-\u00FF]{2,}', _fix_chunk, s)
    return s


def _labels(items):
    return {item.get('label'): _clean_text(item.get('value', '')) for item in items if isinstance(item, dict) and item.get('label')}


def _parse_post(item):
    if not isinstance(item, dict):
        return None
    labels = item.get('label_values') or []
    if not isinstance(labels, list):
        return None
    values = _labels(labels)
    url = values.get('URL', '')
    if not isinstance(url, str):
        return None
    parsed = urlsplit(url)
    match = re.fullmatch(r'/(p|reel|tv)/([A-Za-z0-9_-]{5,64})/?', parsed.path)
    if parsed.scheme != 'https' or parsed.hostname not in {'instagram.com', 'www.instagram.com'} or not match:
        return None
    kind, code = match.groups()
    owner = next((entry for entry in labels if isinstance(entry, dict) and entry.get('title') == 'Owner'), {})
    owner_groups = owner.get('dict')
    owner_items = owner_groups[0].get('dict') if isinstance(owner_groups, list) and owner_groups and isinstance(owner_groups[0], dict) else []
    if not isinstance(owner_items, list):
        owner_items = []
    hashtags = next((entry for entry in labels if isinstance(entry, dict) and entry.get('title') == 'Hashtags'), {})
    tags = [f"#{_clean_text(_labels(entry.get('dict') or []).get('Name', ''))}" for entry in hashtags.get('dict') or [] if isinstance(entry, dict)]
    raw_caption = _clean_text(str(values.get('Caption') or ''))
    if not any(len(tag) > 1 for tag in tags):
        tags = re.findall(r'(?<!\w)#[\w\u0600-\u06FF]+', raw_caption)
    timestamp = item.get('timestamp')
    if not isinstance(timestamp, int) or timestamp <= 0:
        timestamp = None
    try:
        pk = str(InstagramIdCodec.decode(code[:11]))
    except (TypeError, ValueError):
        return None
    return {
        'pk': pk, 'shortcode': code,
        'original_url': f'https://www.instagram.com/{kind}/{code}/',
        'media_type': 2 if kind in {'reel', 'tv'} else 0,
        'owner_username': _clean_text(_labels(owner_items).get('Username', ''))[:100],
        'caption': raw_caption[:100000],
        'hashtags': ', '.join(dict.fromkeys(tag for tag in tags if len(tag) > 1))[:20000],
        'timestamp': timestamp, 'fbid': str(item.get('fbid') or '')[:100],
    }


def validate_export_directory(directory):
    root = Path(directory).resolve()
    if not root.is_dir():
        raise ValueError('Export folder does not exist')
    if (root / 'your_instagram_activity').is_dir():
        root = root / 'your_instagram_activity'
    paths = {name: root / subdir / filename for name, subdir, filename in (
        ('saved', 'saved', 'saved_posts.json'), ('liked', 'likes', 'liked_posts.json'),
        ('collections', 'saved', 'saved_collections.json'))}
    if not paths['saved'].is_file() and not paths['liked'].is_file():
        raise ValueError('No saved_posts.json or liked_posts.json found in this export')
    for path in paths.values():
        if path.is_file() and (not path.resolve().is_relative_to(root.resolve()) or path.stat().st_size > 100_000_000):
            raise ValueError('Invalid export file location or size')
    return root, paths


def read_export(directory):
    root, paths = validate_export_directory(directory)
    result = {}
    for name, path in paths.items():
        if not path.is_file():
            result[name] = []
            continue
        data = json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(data, list) or len(data) > 100_000:
            raise ValueError('Unsupported export JSON format')
        result[name] = data
    return result


def preview(directory):
    data = read_export(directory)
    parsed = {name: [post for item in data[name] if (post := _parse_post(item))]
              for name in ('saved', 'liked')}
    collections = [str(_labels(item.get('label_values') or []).get('Name', ''))
                   for item in data['collections'] if isinstance(item, dict)]
    return {'saved': len(parsed['saved']), 'liked': len(parsed['liked']),
            'overlap': len({p['pk'] for p in parsed['saved']} & {p['pk'] for p in parsed['liked']}),
            'collections': len([name for name in collections if name]),
            'invalid_links': sum(len(data[name]) - len(parsed[name]) for name in ('saved', 'liked')),
            'contains_media_files': False}


def run_import(job_id, cancel_event, directory):
    manager.update_progress(job_id, 1, 'Reading export JSON')
    data = read_export(directory)
    conn = database.get_db()
    count = 0
    now = int(time.time())
    try:
        with conn:
            total = len(data['saved']) + len(data['liked']) + len(data['collections'])
            for source in ('saved', 'liked'):
                if cancel_event.is_set():
                    break
                for item in data[source]:
                    if cancel_event.is_set():
                        break
                    post = _parse_post(item)
                    if post is None:
                        continue
                    conn.execute('''INSERT INTO posts
                        (pk, shortcode, original_url, media_type, owner_username, caption, original_hashtags,
                         taken_at, status, status_updated_at, saved_at, liked_at, is_saved, is_liked, export_fbid)
                        VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 'DISCOVERED', ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(pk) DO UPDATE SET
                          original_url=COALESCE(NULLIF(posts.original_url,''), excluded.original_url),
                          owner_username=CASE WHEN posts.owner_username IS NULL OR posts.owner_username='' THEN excluded.owner_username ELSE posts.owner_username END,
                          caption=CASE WHEN posts.caption IS NULL OR posts.caption='' OR posts.caption LIKE '%Ã%' OR posts.caption LIKE '%Ø%' OR posts.caption LIKE '%\x80%' THEN excluded.caption ELSE posts.caption END,
                          original_hashtags=CASE WHEN posts.original_hashtags IS NULL OR posts.original_hashtags='' OR posts.original_hashtags LIKE '%Ã%' OR posts.original_hashtags LIKE '%Ø%' THEN excluded.original_hashtags ELSE posts.original_hashtags END,
                          saved_at=COALESCE(posts.saved_at, excluded.saved_at),
                          liked_at=COALESCE(posts.liked_at, excluded.liked_at),
                          is_saved=MAX(posts.is_saved, excluded.is_saved),
                          is_liked=MAX(posts.is_liked, excluded.is_liked),
                          export_fbid=COALESCE(posts.export_fbid, excluded.export_fbid)''',
                        (post['pk'], post['shortcode'], post['original_url'], post['media_type'], post['owner_username'],
                         post['caption'], post['hashtags'], now,
                         post['timestamp'] if source == 'saved' else None,
                         post['timestamp'] if source == 'liked' else None,
                         int(source == 'saved'), int(source == 'liked'), post['fbid']))
                    count += 1
                    if count % 250 == 0:
                        conn.commit()
                        manager.update_progress(job_id, 100 * count / max(total, 1), f'Imported {count}/{total} records')
            for collection in data['collections']:
                if cancel_event.is_set():
                    break
                if not isinstance(collection, dict):
                    continue
                labels = collection.get('label_values') or []
                name = _clean_text(str(_labels(labels).get('Name', ''))).strip()[:100]
                if not name:
                    continue
                media = next((entry for entry in labels if isinstance(entry, dict) and entry.get('title') == 'Media'), {})
                for member in media.get('dict') or []:
                    post = _parse_post({'label_values': member.get('dict') or []}) if isinstance(member, dict) else None
                    if post:
                        conn.execute('INSERT OR IGNORE INTO export_collections (name, post_pk) VALUES (?, ?)', (name, post['pk']))
        manager.update_progress(job_id, 100, f'Imported {count} saved/liked records')
        return {'processed': count, 'cancelled': cancel_event.is_set()}
    finally:
        conn.close()
