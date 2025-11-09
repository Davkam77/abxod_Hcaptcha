from __future__ import annotations

import subprocess
import time

import pyautogui
from pygetwindow import getWindowsWithTitle
from PIL import Image

from config import (
    TARGET_URL,
    CHROME_PATH,
    CHROME_REMOTE_DEBUG_PORT,
    CHROME_USER_DATA_DIR,
    CHROME_PROXY,
)
from core import PNG_DIR


def ensure_png_dir() -> None:
    PNG_DIR.mkdir(parents=True, exist_ok=True)


def start_chrome() -> None:
    args = [
        CHROME_PATH,
        f"--remote-debugging-port={CHROME_REMOTE_DEBUG_PORT}",
        f"--user-data-dir={CHROME_USER_DATA_DIR}",
        "--no-first-run",
        "--disable-infobars",
        "--start-maximized",
    ]
    if TARGET_URL:
        args.append(TARGET_URL)
    if CHROME_PROXY:
        args.append(f"--proxy-server={CHROME_PROXY}")

    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"[chrome_utils] Chrome запущен с URL: {TARGET_URL}")


def ensure_chrome_and_open_url() -> None:
    try:
        wins = getWindowsWithTitle("Chrome") + getWindowsWithTitle("Google Chrome")
    except Exception as e:
        print(f"[chrome_utils] Не удалось получить окна Chrome: {e}")
        wins = []

    if wins:
        try:
            wins[0].activate()
            print("[chrome_utils] Найден уже открытый Chrome, активируем окно.")
            time.sleep(1)
        except Exception as e:
            print(f"[chrome_utils] Не смог активировать окно Chrome: {e}")
    else:
        print("[chrome_utils] Открытого Chrome нет, запускаем новый экземпляр.")
        start_chrome()
        time.sleep(3)

    if TARGET_URL:
        try:
            pyautogui.hotkey("ctrl", "l")
            time.sleep(0.2)
            pyautogui.typewrite(TARGET_URL)
            pyautogui.press("enter")
            print(f"[chrome_utils] Перешёл на URL: {TARGET_URL}")
        except Exception as e:
            print(f"[chrome_utils] Не удалось отправить URL в Chrome: {e}")


def screenshot_full() -> Image.Image:
    return pyautogui.screenshot()
