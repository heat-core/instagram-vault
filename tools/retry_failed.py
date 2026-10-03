import sys
from pathlib import Path

# Add src/ to Python path so we can import database
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
import database

def main():
    print("در حال بازنشانی آیتم‌های DOWNLOAD_FAILED...")
    database.init_db()
    count = database.reset_failed_posts()
    print(f"تعداد {count} آیتم با موفقیت به صف دانلود (DISCOVERED) بازگردانده شدند.")
    print("شمارنده خطای آنها نیز صفر شد. می‌توانید 02_downloader.py را مجدداً اجرا کنید.")

if __name__ == "__main__":
    main()
