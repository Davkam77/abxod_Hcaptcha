from __future__ import annotations

import cv2
import numpy as np
import pyautogui

from core import MATCH_THRESHOLD_OBJECT, PNG_DIR
from chrome_utils import screenshot_full


def _click_by_template(png_name: str, min_score: float = 0.45) -> bool:
    """
    Универсальный клик по PNG-шаблону (next.png / done.png).
    Возвращает True, если клик был выполнен.
    """
    templ_path = PNG_DIR / png_name
    if not templ_path.is_file():
        print(f"[stage_next_done] template not found: {templ_path}")
        return False

    full = screenshot_full()
    src = cv2.cvtColor(np.array(full), cv2.COLOR_RGB2BGR)

    templ = cv2.imread(str(templ_path), cv2.IMREAD_COLOR)
    if templ is None:
        print(f"[stage_next_done] cannot read template: {templ_path}")
        return False

    res = cv2.matchTemplate(src, templ, cv2.TM_CCOEFF_NORMED)
    _minv, maxv, _minl, maxl = cv2.minMaxLoc(res)

    print(f"[stage_next_done] match {png_name}: score={maxv:.3f}")
    if maxv < max(min_score, MATCH_THRESHOLD_OBJECT * 0.7):
        print(f"[stage_next_done] score too low for {png_name}, skip")
        return False

    h, w = templ.shape[:2]
    x, y = maxl
    cx = x + w // 2
    cy = y + h // 2

    pyautogui.moveTo(cx, cy, duration=0.15)
    pyautogui.click()
    return True


def click_next_button() -> bool:
    return _click_by_template("next.png")


def click_done_button() -> bool:
    return _click_by_template("done.png")
