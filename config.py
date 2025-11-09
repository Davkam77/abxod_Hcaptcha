# config.py
import os
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

TARGET_URL = os.getenv("TARGET_URL")

CHROME_PATH = os.getenv("CHROME_PATH")
CHROME_REMOTE_DEBUG_PORT = int(os.getenv("CHROME_REMOTE_DEBUG_PORT", "9222"))
CHROME_USER_DATA_DIR = os.getenv("CHROME_USER_DATA_DIR", "./chrome-profile")
CHROME_PROXY = os.getenv("CHROME_PROXY")

HTTP_PROXY = os.getenv("HTTP_PROXY")
HTTPS_PROXY = os.getenv("HTTPS_PROXY")

# если нужны, экспортируем в окружение для любых библиотек
if HTTP_PROXY:
    os.environ["HTTP_PROXY"] = HTTP_PROXY
if HTTPS_PROXY:
    os.environ["HTTPS_PROXY"] = HTTPS_PROXY
