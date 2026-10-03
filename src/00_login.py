import sys
from getpass import getpass
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from instagrapi import Client
from instagrapi.exceptions import ChallengeRequired
from session_store import save_session

SESSION_FILE = Path(__file__).resolve().parents[1] / "archive" / "session.enc"

def challenge_code_handler(username, choice):
    """
    Called by instagrapi when a challenge (SMS/Email) is required.
    Allows the user to input the code directly via terminal.
    """
    if choice == 1:
        print("کد تایید به SMS ارسال شد.")
    elif choice == 2:
        print("کد تایید به ایمیل ارسال شد.")
    else:
        print("درخواست کد تایید ارسال شد.")
        
    code = getpass(f"لطفاً کد تایید دریافت شده برای اکانت {username} را وارد کنید: ")
    return code

def main():
    username = input("نام کاربری اینستاگرام: ").strip()
    password = getpass("رمز عبور (نمایش داده نمی‌شود): ")
    if not username or not password:
        raise ValueError("نام کاربری و رمز عبور لازم است.")
        
    print(f"در حال لاگین به حساب کاربری: {username} ...")
    
    cl = Client()
    cl.challenge_code_handler = challenge_code_handler
    
    try:
        result = cl.login(username, password)
        del password
        if result:
            save_session(cl.get_settings(), SESSION_FILE)
            print("لاگین موفقیت‌آمیز بود!")
            print(f"نشست شما در {SESSION_FILE} ذخیره شد.")
            print("حالا می‌توانید اسکریپت‌های دیگر را اجرا کنید.")
        else:
            print("لاگین شکست خورد. (خطای ناشناخته)")
    except ChallengeRequired:
        print("خطای Challenge حل نشد! اینستاگرام درخواست را رد کرد.")
    except Exception as e:
        print(f"خطا هنگام لاگین: {type(e).__name__}")
        
if __name__ == "__main__":
    main()
