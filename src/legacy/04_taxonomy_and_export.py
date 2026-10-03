import os
import re
import sqlite3
import shutil
import html
from pathlib import Path
import urllib.parse
from openai import OpenAI
import numpy as np
from sklearn.cluster import HDBSCAN
from dotenv import load_dotenv
import database

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

EXPORT_DIR = Path("archive/categories")
INDEX_HTML_PATH = Path("archive/index.html")

def get_embeddings(texts):
    embeddings = []
    batch_size = 100
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i+batch_size]
        response = client.embeddings.create(input=batch, model="text-embedding-3-small")
        embeddings.extend([item.embedding for item in response.data])
    return embeddings

def sanitize_windows_name(name):
    """
    Removes characters that are illegal in Windows file/folder names,
    strips trailing dots or spaces, and prevents reserved names.
    """
    safe_name = re.sub(r'[<>:"/\\|?*]', '-', name)
    safe_name = safe_name.rstrip('. ')
    
    if not safe_name:
        safe_name = "Unnamed"
        
    reserved = ["CON", "PRN", "AUX", "NUL"] + [f"COM{i}" for i in range(1, 10)] + [f"LPT{i}" for i in range(1, 10)]
    if safe_name.upper() in reserved:
        safe_name = f"{safe_name}_Category"
        
    return safe_name

def generate_category_name(cluster_texts, existing_categories):
    sample_text = "\n".join(cluster_texts[:10])
    
    sys_prompt = "You are a taxonomy expert naming a cluster of Instagram posts. "
    sys_prompt += "Output exactly in this format: Category / Subcategory (e.g. Design / Interior Design). No extra text. "
    
    if existing_categories:
        cats_str = ", ".join(existing_categories)
        sys_prompt += f"IMPORTANT: If the cluster fits perfectly into one of these existing categories, YOU MUST USE IT EXACTLY: [{cats_str}]. Only create a new category if it represents a genuinely new topic."
        
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": f"Samples:\n{sample_text}"}
            ],
            max_tokens=30,
            temperature=0.2
        )
        cat = response.choices[0].message.content.strip()
        if "/" not in cat:
            cat = f"General / {cat}"
        return cat
    except Exception:
        return "Uncategorized / Miscellaneous"

def generate_html_index(all_items):
    html_content = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Instagram Saved Posts Archive</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f8f9fa; margin: 0; padding: 20px; }
        .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 20px; }
        .card { background: white; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); overflow: hidden; padding: 15px; display: flex; flex-direction: column; }
        .thumb { width: 100%; height: 200px; object-fit: cover; border-radius: 4px; margin-bottom: 10px; background: #000; }
        .card h3 { margin: 0 0 10px 0; font-size: 16px; color: #333; }
        .tags { font-size: 12px; color: #0066cc; margin-bottom: 10px; }
        .cat { font-size: 11px; background: #eee; padding: 2px 6px; border-radius: 12px; display: inline-block; margin-bottom: 10px; }
        .media-link { display: block; margin-top: 10px; text-decoration: none; color: white; background: #000; text-align: center; padding: 8px; border-radius: 4px; }
        input[type="text"] { width: 100%; padding: 10px; margin-bottom: 20px; box-sizing: border-box; border: 1px solid #ddd; border-radius: 4px; }
    </style>
</head>
<body>
    <h1>Saved Posts Archive</h1>
    <input type="text" id="searchInput" placeholder="Search by category, tags, or caption..." onkeyup="search()">
    <div class="grid" id="grid">
"""
    for item in all_items:
        # URL-encode the path components safely
        cat_path = str(item['ai_category']).strip()
        encoded_cat_path = "/".join([urllib.parse.quote(p) for p in cat_path.split("/")])
        rel_path = f"categories/{encoded_cat_path}/{item['pk']}"
        
        safe_caption = html.escape(str(item.get('caption', '')))
        safe_tags = html.escape(str(item.get('ai_tags', '')))
        safe_cat = html.escape(cat_path.replace('/', ' / '))
        
        thumb_html = ""
        first_file = item.get('first_file')
        if first_file:
            filename = Path(first_file).name
            thumb_url = f"{rel_path}/{urllib.parse.quote(filename)}"
            if thumb_url.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                thumb_html = f'<img src="{thumb_url}" class="thumb" loading="lazy">'
            elif thumb_url.lower().endswith(('.mp4', '.mov')):
                thumb_html = f'<video src="{thumb_url}" class="thumb" muted loop onmouseover="this.play()" onmouseout="this.pause()"></video>'
        
        html_content += f"""
        <div class="card" data-search="{safe_caption.lower()} {safe_tags.lower()} {safe_cat.lower()}">
            {thumb_html}
            <span class="cat">{safe_cat}</span>
            <h3>{html.escape(str(item.get('owner_username', '')))}</h3>
            <div class="tags">{safe_tags}</div>
            <p style="font-size: 13px; color: #666; max-height: 60px; overflow: hidden;">{safe_caption[:100]}...</p>
            <a href="{rel_path}" class="media-link" target="_blank">Open Folder</a>
        </div>
        """
        
    html_content += """
    </div>
    <script>
        function search() {
            let input = document.getElementById('searchInput').value.toLowerCase();
            let cards = document.getElementsByClassName('card');
            for (let i = 0; i < cards.length; i++) {
                let searchable = cards[i].getAttribute('data-search');
                cards[i].style.display = searchable.includes(input) ? "" : "none";
            }
        }
    </script>
</body>
</html>
"""
    with open(INDEX_HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html_content)

def main():
    database.init_db()
    conn = database.get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM posts WHERE status = 'ANALYSIS_OK'")
    items = cursor.fetchall()
    
    existing_cats = database.get_existing_categories()
    
    if not items:
        print("هیچ پستی با وضعیت ANALYSIS_OK یافت نشد.")
    else:
        clusters = {}
        
        if len(items) < 3:
            print("تعداد آیتم‌ها برای HDBSCAN کمتر از ۳ است. خوشه‌بندی تکی انجام می‌شود...")
            for idx, item in enumerate(items):
                clusters[idx] = [item]
        else:
            print(f"در حال تولید Embedding برای {len(items)} آیتم جدید...")
            texts = [f"{row['caption']} {row['ai_summary']} {row['ai_tags']}" for row in items]
            embeddings = get_embeddings(texts)
            
            print("خوشه‌بندی (HDBSCAN)...")
            clusterer = HDBSCAN(min_cluster_size=max(3, len(items)//50), metric="euclidean")
            labels = clusterer.fit_predict(embeddings)
            
            for idx, label in enumerate(labels):
                clusters.setdefault(label, []).append(items[idx])
                
        print("نام‌گذاری خوشه‌ها و ساخت ساختار درختی (Hardlinks)...")
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        
        for label, group in clusters.items():
            if label == -1 and len(items) >= 3:
                cat_name = "Uncategorized / Miscellaneous"
            else:
                sample_texts = [row['ai_summary'] for row in group]
                cat_name = generate_category_name(sample_texts, existing_cats)
                
            parts = [p.strip() for p in cat_name.split("/")]
            if len(parts) == 1:
                parts.append("General")
                
            main_cat = sanitize_windows_name(parts[0])
            sub_cat = sanitize_windows_name(parts[1]) if len(parts) > 1 else "General"
            
            # Use forward slash for the internal path string so it maps to URLs cleanly
            category_path = f"{main_cat}/{sub_cat}"
            cat_dir = EXPORT_DIR / main_cat / sub_cat
            cat_dir.mkdir(parents=True, exist_ok=True)
            
            for row in group:
                pk = row['pk']
                post_dir = cat_dir / pk
                post_dir.mkdir(exist_ok=True)
                
                with open(post_dir / "info.md", "w", encoding="utf-8") as f:
                    f.write(f"# Post Information\n\n")
                    f.write(f"- **Creator:** @{row['owner_username']}\n")
                    f.write(f"- **Original URL:** https://www.instagram.com/p/{row['shortcode']}/\n")
                    f.write(f"- **Saved ID (PK):** {pk}\n")
                    f.write(f"- **Publication Date:** {row['taken_at']}\n")
                    f.write(f"- **Media Type:** {row['media_type']} (1=Photo, 2=Video, 8=Carousel)\n")
                    f.write(f"- **Category:** {main_cat} / {sub_cat}\n")
                    f.write(f"- **Tags:** {row['ai_tags']}\n\n")
                    f.write(f"## AI Summary\n{row['ai_summary']}\n\n")
                    f.write(f"## Original Caption\n{row['caption']}\n")
                    
                cursor.execute("SELECT file_path FROM media_files WHERE post_pk = ?", (pk,))
                files = cursor.fetchall()
                for f in files:
                    src_path = Path(f['file_path'])
                    dst_path = post_dir / src_path.name
                    if src_path.exists():
                        try:
                            if not dst_path.exists():
                                os.link(src_path, dst_path)
                        except OSError:
                            shutil.copy2(src_path, dst_path)
                        
                database.mark_as_organized(pk, category_path)
                
            # If we created a genuinely new category, append it to existing_cats for the next iteration in this run
            if category_path not in existing_cats:
                existing_cats.append(category_path)

    # Re-fetch ALL organized items for the HTML generation
    cursor.execute("""
        SELECT p.*, (SELECT file_path FROM media_files m WHERE m.post_pk = p.pk ORDER BY media_index LIMIT 1) as first_file
        FROM posts p
        WHERE p.status = 'ORGANIZED'
    """)
    organized = cursor.fetchall()
    
    if organized:
        print("تولید فایل index.html...")
        generate_html_index([dict(item) for item in organized])
        print("عملیات سازمان‌دهی و خروجی با موفقیت به پایان رسید.")
    else:
        print("موردی برای ساخت ایندکس وجود ندارد.")

if __name__ == "__main__":
    main()
