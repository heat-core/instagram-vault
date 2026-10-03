import os
import base64
import cv2
import numpy as np
from PIL import Image
from dotenv import load_dotenv
import database
from openai import OpenAI

load_dotenv()
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def resize_with_padding(img, target_size=512):
    """
    Resizes the image to fit within target_size x target_size while keeping aspect ratio,
    padding the rest with black pixels.
    """
    h, w = img.shape[:2]
    scale = target_size / max(h, w)
    new_w, new_h = int(w * scale), int(h * scale)
    
    resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
    
    top = (target_size - new_h) // 2
    bottom = target_size - new_h - top
    left = (target_size - new_w) // 2
    right = target_size - new_w - left
    
    color = [0, 0, 0]
    new_img = cv2.copyMakeBorder(resized, top, bottom, left, right, cv2.BORDER_CONSTANT, value=color)
    return new_img

def extract_frames(video_path, num_frames=4):
    cap = cv2.VideoCapture(video_path)
    frames = []
    if not cap.isOpened():
        return frames
    
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    step = max(total_frames // (num_frames + 1), 1)
    
    for i in range(1, num_frames + 1):
        cap.set(cv2.CAP_PROP_POS_FRAMES, i * step)
        ret, frame = cap.read()
        if ret:
            padded = resize_with_padding(frame, target_size=512)
            _, buffer = cv2.imencode('.jpg', padded)
            frames.append(base64.b64encode(buffer).decode('utf-8'))
            
    cap.release()
    return frames

def analyze_with_gpt4o(caption, frames_b64):
    prompt = f"""
    Original Caption: {caption}
    
    You are an advanced AI vision analysis tool. I have provided frames/images from an Instagram post.
    Perform the following tasks:
    1. Read and transcribe any important text visible in the images (OCR).
    2. Analyze the visual content.
    3. Determine the core subject and provide a concise summary.
    4. Provide 3-5 comma-separated tags.
    
    Format your response EXACTLY like this:
    SUMMARY: [Your concise summary here]
    TAGS: tag1, tag2, tag3
    """
    
    content = [{"type": "text", "text": prompt}]
    
    for b64 in frames_b64:
        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/jpeg;base64,{b64}"
            }
        })
        
    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": content}],
        max_tokens=300
    )
    
    text = response.choices[0].message.content
    
    summary = ""
    tags = ""
    for line in text.splitlines():
        if line.startswith("SUMMARY:"):
            summary = line.replace("SUMMARY:", "").strip()
        elif line.startswith("TAGS:"):
            tags = line.replace("TAGS:", "").strip()
            
    if not summary:
        summary = text # Fallback
        
    return summary, tags

def main():
    database.init_db()
    conn = database.get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT pk, caption, media_type FROM posts WHERE status = 'DOWNLOAD_OK' LIMIT 20")
    todo = cursor.fetchall()
    
    if not todo:
        print("پستی برای تحلیل یافت نشد.")
        return
        
    for row in todo:
        pk = row['pk']
        caption = row['caption']
        media_type = row['media_type']
        
        database.update_post_status(pk, 'ANALYSIS_PENDING')
        
        cursor.execute("SELECT file_path FROM media_files WHERE post_pk = ? ORDER BY media_index", (pk,))
        files = cursor.fetchall()
        
        frames_to_send = []
        try:
            if media_type == 2 and files: # Video
                frames_to_send = extract_frames(files[0]['file_path'], num_frames=4)
            elif media_type in (1, 8) and files: # Image / Carousel
                total_files = len(files)
                num_samples = min(total_files, 4)
                indices = np.linspace(0, total_files - 1, num_samples, dtype=int)
                
                for idx in indices:
                    f = files[idx]
                    img = cv2.imread(f['file_path'])
                    if img is not None:
                        padded = resize_with_padding(img, target_size=512)
                        _, buffer = cv2.imencode('.jpg', padded)
                        frames_to_send.append(base64.b64encode(buffer).decode('utf-8'))
                        
            print(f"تحلیل AI برای پست {pk}...")
            
            summary, tags = analyze_with_gpt4o(caption, frames_to_send)
            database.update_ai_analysis(pk, summary, "Uncategorized", tags)
            
            print(f"موفقیت: {pk} -> {tags}")
            
        except Exception as e:
            print(f"خطا در تحلیل {pk}: {e}")
            database.update_post_status(pk, 'DOWNLOAD_OK')
            
    conn.close()

if __name__ == "__main__":
    main()
