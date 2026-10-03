import os
import re
import shutil
import html
import urllib.parse
import threading
import json
import time
from pathlib import Path
from .. import database
from ..job_manager import manager

EXPORT_DIR = database.DATA_DIR / "categories"
INDEX_HTML_PATH = database.DATA_DIR / "index.html"

class TaxonomyService:
    @staticmethod
    def sanitize_windows_name(name: str) -> str:
        safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '-', name).strip()[:100].rstrip('. ')
        
        if not safe_name:
            safe_name = "Unnamed"
            
        reserved = ["CON", "PRN", "AUX", "NUL"] + [f"COM{i}" for i in range(1, 10)] + [f"LPT{i}" for i in range(1, 10)]
        if safe_name.split('.')[0].upper() in reserved:
            safe_name = f"{safe_name}_Category"
            
        return safe_name

    @classmethod
    def _safe_link(cls, src: Path, dest: Path, is_auxiliary: bool = False):
        """
        Safely links a source media file to a destination folder.
        1. Tries NTFS hardlink (os.link) -> 0 extra disk bytes used.
        2. Tries symlink (os.symlink) -> 0 extra disk bytes used.
        3. If neither works (e.g. exFAT, FAT32, or permissions):
           - For primary view (is_auxiliary=False): copies the file.
           - For auxiliary views (by-creator, by-format, by-year, by-collection):
             If file is small (<= 2 MB), copies it.
             If file is large (> 2 MB), creates a lightweight .ref.txt pointer
             to prevent multi-megabyte/gigabyte duplication across 4+ views.
        """
        if dest.exists():
            try:
                if os.path.samefile(src, dest):
                    return
                dest.unlink()
            except OSError:
                pass

        try:
            os.link(src, dest)
            return
        except OSError:
            pass

        try:
            os.symlink(src, dest)
            return
        except OSError:
            pass

        try:
            file_size = src.stat().st_size
        except OSError:
            file_size = 0

        if is_auxiliary and file_size > 2 * 1024 * 1024:
            ref_path = dest.with_name(dest.name + ".ref.txt")
            try:
                with open(ref_path, "w", encoding="utf-8") as f:
                    f.write(f"Canonical Media Reference\n")
                    f.write(f"Source: {src.name}\n")
                    f.write(f"Path: {src.resolve()}\n")
            except OSError:
                pass
        else:
            try:
                shutil.copy2(src, dest)
            except OSError:
                pass

    @classmethod
    def link_view(cls, source_dir, axis, label, pk, files):
        view = database.DATA_DIR / axis / cls.sanitize_windows_name(label) / pk
        view.mkdir(parents=True, exist_ok=True)
        info_src = source_dir / 'info.md'
        if info_src.is_file():
            try:
                shutil.copy2(info_src, view / 'info.md')
            except OSError:
                pass
        for src in files:
            dest = view / src.name
            cls._safe_link(src, dest, is_auxiliary=True)

    @classmethod
    def refresh_media_views(cls, row, files):
        """Refresh hardlinks after a verified canonical quality upgrade."""
        category = row.get('export_category')
        if not category or len(category.split('/')) != 2:
            return
        pk = row['pk']
        parts = [cls.sanitize_windows_name(part) for part in category.split('/')]
        source_dir = EXPORT_DIR / parts[0] / parts[1] / pk
        if not source_dir.is_dir() or not (source_dir / 'info.md').is_file():
            return
        sources = [database.resolve_media_path(path) for path, _ in files]
        for src in sources:
            dest = source_dir / src.name
            cls._safe_link(src, dest, is_auxiliary=False)
        format_name = {1: 'Photo', 2: 'Video', 8: 'Carousel'}.get(row['media_type'], 'Other')
        year = (database.published_at(row['taken_at']) or 'Unknown')[:4]
        for axis, label in (('by-creator', row['owner_username'] or 'Unknown'),
                            ('by-format', format_name), ('by-year', year)):
            cls.link_view(source_dir, axis, label, pk, sources)
        conn = database.get_db()
        try:
            for membership in conn.execute('SELECT name FROM export_collections WHERE post_pk=?', (pk,)):
                cls.link_view(source_dir, 'by-collection', membership['name'], pk, sources)
        finally:
            conn.close()

    @staticmethod
    def generate_html_index(all_items):
        records = []
        categories_set = set()
        for item in all_items:
            cat_path = str(item.get('ai_category') or 'Uncategorized/General').strip()
            categories_set.add(cat_path)
            encoded_cat_path = "/".join([urllib.parse.quote(p) for p in cat_path.split("/")])
            rel_path = f"categories/{encoded_cat_path}/{item['pk']}"
            
            caption = str(item.get('caption') or '')
            ai_tags = str(item.get('ai_tags') or '')
            original_hashtags = str(item.get('original_hashtags') or '')
            username = str(item.get('owner_username') or '')
            
            topics_raw = item.get('ai_categories') or '[]'
            try:
                topics_list = json.loads(topics_raw) if isinstance(topics_raw, str) else topics_raw
            except Exception:
                topics_list = []
            topics_str = ', '.join(topics_list)

            thumb_url = ""
            is_video = False
            first_file = item.get('first_file')
            if first_file:
                fname = Path(first_file).name
                thumb_url = f"{rel_path}/{urllib.parse.quote(fname)}"
                is_video = thumb_url.lower().endswith(('.mp4', '.mov'))

            search_blob = f"{caption} {ai_tags} {original_hashtags} {topics_str} {cat_path} {username}".lower()

            records.append({
                "pk": str(item.get('pk', '')),
                "shortcode": str(item.get('shortcode', '')),
                "username": username,
                "caption": caption,
                "tags": ai_tags,
                "hashtags": original_hashtags,
                "topics": topics_str,
                "category": cat_path,
                "thumb": thumb_url,
                "is_video": is_video,
                "rel_path": rel_path,
                "search": search_blob
            })

        categories_list = sorted(list(categories_set))
        catalog_json = json.dumps(records, indent=2, ensure_ascii=False)
        categories_json = json.dumps(categories_list, ensure_ascii=False)

        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Instagram Saved Archive Catalog</title>
    <style>
        :root {{
            --bg-color: #0b0f19;
            --surface-color: #151d30;
            --surface-hover: #1c2742;
            --border-color: #233152;
            --primary-color: #38bdf8;
            --text-color: #f1f5f9;
            --text-muted: #94a3b8;
            --tag-bg: #1e293b;
            --tag-color: #7dd3fc;
            --font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: var(--font-family);
            background: var(--bg-color);
            color: var(--text-color);
            min-height: 100vh;
            padding: 24px;
        }}
        .header {{
            max-width: 1400px;
            margin: 0 auto 24px auto;
            display: flex;
            flex-direction: column;
            gap: 16px;
        }}
        .title-row {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 12px;
        }}
        h1 {{ font-size: 26px; font-weight: 700; color: #fff; }}
        .badge {{
            background: rgba(56, 189, 248, 0.15);
            color: var(--primary-color);
            padding: 4px 12px;
            border-radius: 9999px;
            font-size: 13px;
            font-weight: 600;
        }}
        .controls-row {{
            display: flex;
            gap: 12px;
            flex-wrap: wrap;
            background: var(--surface-color);
            padding: 14px;
            border-radius: 12px;
            border: 1px solid var(--border-color);
        }}
        .search-box {{
            flex: 1;
            min-width: 250px;
            position: relative;
        }}
        input[type="text"], select {{
            width: 100%;
            background: var(--bg-color);
            border: 1px solid var(--border-color);
            color: var(--text-color);
            padding: 10px 14px;
            border-radius: 8px;
            font-size: 14px;
            outline: none;
            transition: border-color 0.2s;
        }}
        input[type="text"]:focus, select:focus {{
            border-color: var(--primary-color);
        }}
        .filter-select {{
            width: auto;
            min-width: 180px;
            cursor: pointer;
        }}
        .grid {{
            max-width: 1400px;
            margin: 0 auto;
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(290px, 1fr));
            gap: 20px;
        }}
        .card {{
            background: var(--surface-color);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            overflow: hidden;
            display: flex;
            flex-direction: column;
            transition: transform 0.2s, box-shadow 0.2s, border-color 0.2s;
        }}
        .card:hover {{
            transform: translateY(-3px);
            border-color: var(--primary-color);
            box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5);
        }}
        .thumb-wrapper {{
            position: relative;
            width: 100%;
            height: 220px;
            background: #000;
            overflow: hidden;
        }}
        .thumb {{
            width: 100%;
            height: 100%;
            object-fit: cover;
            display: block;
        }}
        .thumb-placeholder {{
            width: 100%;
            height: 100%;
            display: flex;
            align-items: center;
            justify-content: center;
            color: var(--text-muted);
            font-size: 13px;
        }}
        .card-body {{
            padding: 16px;
            display: flex;
            flex-direction: column;
            gap: 10px;
            flex: 1;
        }}
        .cat-pill {{
            font-size: 11px;
            background: rgba(56, 189, 248, 0.1);
            color: var(--primary-color);
            padding: 3px 8px;
            border-radius: 6px;
            display: inline-block;
            align-self: flex-start;
            font-weight: 500;
        }}
        .username {{
            font-size: 15px;
            font-weight: 600;
            color: #fff;
            text-decoration: none;
        }}
        .caption {{
            font-size: 13px;
            color: var(--text-muted);
            line-height: 1.4;
            max-height: 55px;
            overflow: hidden;
            display: -webkit-box;
            -webkit-line-clamp: 3;
            -webkit-box-orient: vertical;
        }}
        .tag-list {{
            display: flex;
            flex-wrap: wrap;
            gap: 4px;
            margin-top: auto;
        }}
        .tag {{
            font-size: 11px;
            background: var(--tag-bg);
            color: var(--tag-color);
            padding: 2px 6px;
            border-radius: 4px;
        }}
        .folder-btn {{
            display: block;
            margin-top: 10px;
            text-decoration: none;
            color: #fff;
            background: var(--border-color);
            text-align: center;
            padding: 8px 12px;
            border-radius: 6px;
            font-size: 13px;
            font-weight: 500;
            transition: background 0.2s;
        }}
        .folder-btn:hover {{
            background: var(--primary-color);
            color: #0b0f19;
        }}
        .pagination {{
            max-width: 1400px;
            margin: 30px auto 10px auto;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 14px;
            background: var(--surface-color);
            padding: 12px 18px;
            border-radius: 10px;
            border: 1px solid var(--border-color);
        }}
        .page-buttons {{
            display: flex;
            gap: 6px;
            align-items: center;
        }}
        .page-btn {{
            background: var(--bg-color);
            border: 1px solid var(--border-color);
            color: var(--text-color);
            padding: 6px 12px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 13px;
            transition: all 0.2s;
        }}
        .page-btn:hover:not(:disabled) {{
            border-color: var(--primary-color);
            color: var(--primary-color);
        }}
        .page-btn.active {{
            background: var(--primary-color);
            color: #0b0f19;
            font-weight: 600;
            border-color: var(--primary-color);
        }}
        .page-btn:disabled {{
            opacity: 0.4;
            cursor: not-allowed;
        }}
        .empty-state {{
            grid-column: 1 / -1;
            text-align: center;
            padding: 60px 20px;
            color: var(--text-muted);
            font-size: 16px;
        }}
    </style>
</head>
<body>
    <div class="header">
        <div class="title-row">
            <h1>Saved Posts Archive</h1>
            <span class="badge" id="statsBadge">Loading archive...</span>
        </div>
        <div class="controls-row">
            <div class="search-box">
                <input type="text" id="searchInput" placeholder="Search caption, tags, user, or category..." autocomplete="off">
            </div>
            <select id="categorySelect" class="filter-select">
                <option value="">All Categories</option>
            </select>
            <select id="pageSizeSelect" class="filter-select" style="min-width: 120px;">
                <option value="48" selected>48 / page</option>
                <option value="96">96 / page</option>
                <option value="192">192 / page</option>
                <option value="All">Show All</option>
            </select>
        </div>
    </div>

    <div class="grid" id="grid"></div>

    <div class="pagination" id="paginationBar">
        <span id="pageInfo" style="font-size: 13px; color: var(--text-muted);"></span>
        <div class="page-buttons" id="pageButtons"></div>
    </div>

    <script id="catalogData" type="application/json">
{catalog_json}
    </script>
    <script id="categoriesData" type="application/json">
{categories_json}
    </script>

    <script>
        (function() {{
            const rawData = JSON.parse(document.getElementById('catalogData').textContent);
            const categories = JSON.parse(document.getElementById('categoriesData').textContent);
            
            let filteredItems = rawData;
            let currentPage = 1;
            let pageSize = 48;

            const grid = document.getElementById('grid');
            const searchInput = document.getElementById('searchInput');
            const categorySelect = document.getElementById('categorySelect');
            const pageSizeSelect = document.getElementById('pageSizeSelect');
            const statsBadge = document.getElementById('statsBadge');
            const pageInfo = document.getElementById('pageInfo');
            const pageButtons = document.getElementById('pageButtons');

            // Populate categories dropdown
            categories.forEach(cat => {{
                const opt = document.createElement('option');
                opt.value = cat;
                opt.textContent = cat;
                categorySelect.appendChild(opt);
            }});

            function filterItems() {{
                const q = searchInput.value.trim().toLowerCase();
                const selCat = categorySelect.value;

                filteredItems = rawData.filter(item => {{
                    if (selCat && item.category !== selCat) return false;
                    if (q && !item.search.includes(q)) return false;
                    return true;
                }});

                currentPage = 1;
                render();
            }}

            function render() {{
                const total = filteredItems.length;
                statsBadge.textContent = `${{total.toLocaleString()}} posts`;

                if (total === 0) {{
                    grid.innerHTML = '<div class="empty-state">No matching saved posts found.</div>';
                    pageInfo.textContent = 'Showing 0 posts';
                    pageButtons.innerHTML = '';
                    return;
                }}

                const effectivePageSize = pageSize === 'All' ? total : parseInt(pageSize, 10);
                const totalPages = Math.ceil(total / effectivePageSize);
                if (currentPage > totalPages) currentPage = totalPages;
                if (currentPage < 1) currentPage = 1;

                const startIdx = (currentPage - 1) * effectivePageSize;
                const endIdx = Math.min(startIdx + effectivePageSize, total);
                const pageSlice = filteredItems.slice(startIdx, endIdx);

                let cardsHtml = '';
                for (let i = 0; i < pageSlice.length; i++) {{
                    const it = pageSlice[i];
                    let mediaHtml = '';
                    if (it.thumb) {{
                        if (it.is_video) {{
                            mediaHtml = `<video src="${{it.thumb}}" class="thumb" muted loop onmouseover="this.play()" onmouseout="this.pause()"></video>`;
                        }} else {{
                            mediaHtml = `<img src="${{it.thumb}}" class="thumb" loading="lazy" alt="Media thumbnail">`;
                        }}
                    }} else {{
                        mediaHtml = '<div class="thumb-placeholder">No Preview</div>';
                    }}

                    const tagsArr = it.tags ? it.tags.split(',').map(t => t.trim()).filter(Boolean) : [];
                    const tagsHtml = tagsArr.slice(0, 3).map(t => `<span class="tag">#${{t}}</span>`).join('');

                    cardsHtml += `
                    <div class="card">
                        <div class="thumb-wrapper">${{mediaHtml}}</div>
                        <div class="card-body">
                            <span class="cat-pill">${{it.category}}</span>
                            <span class="username">${{it.username ? '@' + it.username : 'Unknown Creator'}}</span>
                            <p class="caption">${{it.caption || 'No caption'}}</p>
                            ${{tagsHtml ? '<div class="tag-list">' + tagsHtml + '</div>' : ''}}
                            <a href="${{it.rel_path}}" class="folder-btn" target="_blank">Open Local Folder</a>
                        </div>
                    </div>`;
                }}
                grid.innerHTML = cardsHtml;

                // Update pagination info
                pageInfo.textContent = `Showing ${{startIdx + 1}}-${{endIdx}} of ${{total.toLocaleString()}} posts (Page ${{currentPage}} of ${{totalPages}})`;

                // Render page buttons
                let buttonsHtml = '';
                if (totalPages > 1) {{
                    buttonsHtml += `<button class="page-btn" onclick="gotoPage(1)" ${{currentPage === 1 ? 'disabled' : ''}}>« First</button>`;
                    buttonsHtml += `<button class="page-btn" onclick="gotoPage(${{currentPage - 1}})" ${{currentPage === 1 ? 'disabled' : ''}}>‹ Prev</button>`;

                    const pageRange = [];
                    for (let p = Math.max(1, currentPage - 2); p <= Math.min(totalPages, currentPage + 2); p++) {{
                        pageRange.push(p);
                    }}

                    pageRange.forEach(p => {{
                        buttonsHtml += `<button class="page-btn ${{p === currentPage ? 'active' : ''}}" onclick="gotoPage(${{p}})">${{p}}</button>`;
                    }});

                    buttonsHtml += `<button class="page-btn" onclick="gotoPage(${{currentPage + 1}})" ${{currentPage === totalPages ? 'disabled' : ''}}>Next ›</button>`;
                    buttonsHtml += `<button class="page-btn" onclick="gotoPage(${{totalPages}})" ${{currentPage === totalPages ? 'disabled' : ''}}>Last »</button>`;
                }}
                pageButtons.innerHTML = buttonsHtml;
            }}

            window.gotoPage = function(page) {{
                currentPage = page;
                render();
                window.scrollTo({{ top: 0, behavior: 'smooth' }});
            }};

            let debounceTimer = null;
            searchInput.addEventListener('input', () => {{
                clearTimeout(debounceTimer);
                debounceTimer = setTimeout(filterItems, 150);
            }});

            categorySelect.addEventListener('change', filterItems);
            pageSizeSelect.addEventListener('change', (e) => {{
                pageSize = e.target.value;
                currentPage = 1;
                render();
            }});

            // Initial render
            filterItems();
        }})();
    </script>
</body>
</html>
"""
        with open(INDEX_HTML_PATH, "w", encoding="utf-8") as f:
            f.write(html_content)

    @classmethod
    def run_taxonomy(cls, job_id: str, cancel_event: threading.Event):
        database.init_db()
        conn = database.get_db()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM posts WHERE status IN ('APPROVED', 'ORGANIZED')")
        items = cursor.fetchall()
        
        if not items:
            manager.log(job_id, "INFO", "No classified posts found.")
            conn.close()
            return {"organized": 0}
            
        clusters = {}
        for item in items:
            clusters.setdefault(item['ai_category'] or 'Uncategorized/Miscellaneous', []).append(item)
                
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        total_clusters = len(clusters)
        organized_count = 0
        
        for idx, (cat_name, group) in enumerate(clusters.items()):
            if cancel_event.is_set():
                break
                
            manager.update_progress(job_id, 10.0 + (80.0 * (idx/total_clusters)), f"Organizing category {idx+1}/{total_clusters}...")
                
            parts = [p.strip() for p in cat_name.split("/")]
            if len(parts) == 1:
                parts.append("General")
                
            main_cat = cls.sanitize_windows_name(parts[0])
            sub_cat = cls.sanitize_windows_name(parts[1]) if len(parts) > 1 else "General"
            
            category_path = f"{main_cat}/{sub_cat}"
            cat_dir = EXPORT_DIR / main_cat / sub_cat
            cat_dir.mkdir(parents=True, exist_ok=True)
            
            for row in group:
                pk = row['pk']
                if cls.sanitize_windows_name(pk) != pk:
                    manager.log(job_id, 'ERROR', f'Unsafe post ID skipped: {pk}')
                    continue
                post_dir = cat_dir / pk
                old_category = row['export_category']
                if old_category and old_category != category_path:
                    old_parts = [cls.sanitize_windows_name(part) for part in old_category.split('/')]
                    if len(old_parts) == 2:
                        old_dir = EXPORT_DIR / old_parts[0] / old_parts[1] / pk
                        if old_dir.is_dir() and old_dir.resolve() != post_dir.resolve():
                            if post_dir.exists():
                                old_dir.rename(post_dir / f'_previous_export_{time.time_ns()}')
                            else:
                                old_dir.rename(post_dir)
                post_dir.mkdir(exist_ok=True)
                
                with open(post_dir / "info.md", "w", encoding="utf-8") as f:
                    f.write(f"# Post Information\n\n")
                    f.write(f"- **Creator:** @{row['owner_username']}\n")
                    f.write(f"- **Creator ID:** {row['owner_id'] or 'Unknown'}\n")
                    f.write(f"- **Original URL:** https://www.instagram.com/p/{row['shortcode']}/\n")
                    f.write(f"- **Saved ID (PK):** {pk}\n")
                    f.write(f"- **Published UTC:** {database.published_at(row['taken_at']) or 'Unknown'}\n")
                    f.write(f"- **Saved UTC:** {database.published_at(row['saved_at']) or 'Not provided by Instagram'}\n")
                    f.write(f"- **Liked UTC:** {database.published_at(row['liked_at']) or 'Not provided by Instagram'}\n")
                    f.write(f"- **Media Type:** {row['media_type']} (1=Photo, 2=Video, 8=Carousel)\n")
                    f.write(f"- **Category:** {main_cat} / {sub_cat}\n")
                    f.write(f"- **Tags:** {row['ai_tags']}\n\n")
                    f.write(f"- **AI confidence:** {row['ai_confidence'] or 'Unknown'}\n")
                    f.write(f"- **Related categories:** {', '.join(json.loads(row['ai_categories'] or '[]'))}\n")
                    f.write(f"- **Original hashtags:** {row['original_hashtags'] or ''}\n\n")
                    tagged = json.loads(row['original_tagged_users'] or '[]')
                    f.write(f"- **Tagged accounts:** {', '.join('@' + user['username'] for user in tagged if user.get('username'))}\n\n")
                    f.write(f"## AI Summary\n{row['ai_summary']}\n\n")
                    f.write(f"## Original Caption\n{row['caption']}\n")
                    
                cursor.execute("SELECT file_path FROM media_files WHERE post_pk = ?", (pk,))
                files = cursor.fetchall()
                present_files = []
                for f_row in files:
                    src_path = database.resolve_media_path(f_row['file_path'])
                    dst_path = post_dir / src_path.name
                    if src_path.exists():
                        present_files.append(src_path)
                        cls._safe_link(src_path, dst_path, is_auxiliary=False)
                format_name = {1: 'Photo', 2: 'Video', 8: 'Carousel'}.get(row['media_type'], 'Other')
                year = (database.published_at(row['taken_at']) or 'Unknown')[:4]
                for axis, label in (('by-creator', row['owner_username'] or 'Unknown'),
                                    ('by-format', format_name), ('by-year', year)):
                    cls.link_view(post_dir, axis, label, pk, present_files)
                for membership in cursor.execute('SELECT name FROM export_collections WHERE post_pk=?', (pk,)).fetchall():
                    cls.link_view(post_dir, 'by-collection', membership['name'], pk, present_files)
                if row['status'] == 'APPROVED':
                    cursor.execute("UPDATE posts SET status = 'ORGANIZED', ai_category = ?, export_category = ?, status_updated_at = ? WHERE pk = ?",
                                   (category_path, category_path, int(time.time()), pk))
                    organized_count += 1
            conn.commit()
                
        if not cancel_event.is_set():
            manager.update_progress(job_id, 95.0, "Generating HTML index...")
            cursor.execute("""
                SELECT p.*, (SELECT file_path FROM media_files m WHERE m.post_pk = p.pk ORDER BY media_index LIMIT 1) as first_file
                FROM posts p
                WHERE p.status = 'ORGANIZED'
            """)
            organized = cursor.fetchall()
            
            if organized:
                cls.generate_html_index([dict(item) for item in organized])
                
            manager.log(job_id, "INFO", "Taxonomy and Export complete.")
            
        conn.close()
        return {"organized": organized_count}

    @classmethod
    def export_custom_category_folder(cls, category_id: int, target_dir: str = None) -> dict:
        conn = database.get_db()
        try:
            cursor = conn.cursor()
            cat = cursor.execute("SELECT * FROM custom_categories WHERE id=?", (category_id,)).fetchone()
            if not cat:
                raise ValueError("Custom category not found")
            
            folder_name = cls.sanitize_windows_name(cat['folder_name'] or cat['name'])
            base = Path(target_dir).resolve() if target_dir else (database.DATA_DIR / "custom_folders")
            dest_dir = base / folder_name
            dest_dir.mkdir(parents=True, exist_ok=True)
            
            cursor.execute("""
                SELECT p.pk, p.owner_username, p.caption, m.file_path, m.media_index
                FROM post_custom_categories pcc
                JOIN posts p ON p.pk = pcc.post_pk
                JOIN media_files m ON m.post_pk = p.pk
                WHERE pcc.category_id = ?
                ORDER BY p.pk, m.media_index
            """, (category_id,))
            rows = cursor.fetchall()
            
            exported = 0
            for r in rows:
                src_path = database.resolve_media_path(r['file_path'])
                if src_path.is_file():
                    safe_user = cls.sanitize_windows_name(r['owner_username'] or 'instagram')
                    dest_file = dest_dir / f"{safe_user}_{r['pk']}_{r['media_index'] + 1}{src_path.suffix}"
                    try:
                        if not dest_file.exists():
                            try:
                                os.link(src_path, dest_file)
                            except OSError:
                                shutil.copy2(src_path, dest_file)
                            exported += 1
                    except Exception:
                        pass
            return {
                "exported": exported,
                "exported_count": exported,
                "folder": str(dest_dir),
                "folder_path": str(dest_dir),
                "category": cat['name']
            }
        finally:
            conn.close()
