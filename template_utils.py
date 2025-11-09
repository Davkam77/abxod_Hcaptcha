from __future__ import annotations

from pathlib import Path
from typing import Tuple, Optional, List

import cv2
import numpy as np
from PIL import Image


def match_best_template(full_img: Image.Image, template_path: Path) -> Tuple[Image.Image, float]:
    if not template_path.is_file():
        raise FileNotFoundError(f"Template not found: {template_path}")

    src_rgb = np.array(full_img)
    src = cv2.cvtColor(src_rgb, cv2.COLOR_RGB2BGR)

    templ_bgr = cv2.imread(str(template_path))
    if templ_bgr is None:
        raise RuntimeError(f"Failed to read template image: {template_path}")
    h, w, _ = templ_bgr.shape

    res = cv2.matchTemplate(src, templ_bgr, cv2.TM_CCOEFF_NORMED)
    _min_val, max_val, _min_loc, max_loc = cv2.minMaxLoc(res)

    x1, y1 = max_loc
    cropped = full_img.crop((x1, y1, x1 + w, y1 + h))
    print(f"[template_utils] matchTemplate {template_path.name}: score={max_val:.3f}, rect=({x1},{y1})-({x1+w},{y1+h})")

    return cropped, max_val


def match_template_multiscale(
    full_img: Image.Image,
    template_path: Path,
    scales: Optional[List[float]] = None,
) -> Tuple[Image.Image, float]:
    """
    Ищем лучший матч шаблона при разных масштабах.
    Возвращает (cropped_img, best_score).
    """
    if scales is None:
        scales = [0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.15]

    if not template_path.is_file():
        raise FileNotFoundError(f"Template not found: {template_path}")

    src_rgb = np.array(full_img)
    src = cv2.cvtColor(src_rgb, cv2.COLOR_RGB2BGR)

    templ0 = cv2.imread(str(template_path))
    if templ0 is None:
        raise RuntimeError(f"Failed to read template image: {template_path}")

    best = (-1.0, None, None)  # (score, (x1,y1,x2,y2), templ_scaled)
    for s in scales:
        tw = max(1, int(templ0.shape[1] * s))
        th = max(1, int(templ0.shape[0] * s))
        templ = cv2.resize(templ0, (tw, th), interpolation=cv2.INTER_AREA)
        res = cv2.matchTemplate(src, templ, cv2.TM_CCOEFF_NORMED)
        _min_val, max_val, _min_loc, max_loc = cv2.minMaxLoc(res)
        x1, y1 = max_loc
        rect = (x1, y1, x1 + tw, y1 + th)
        if max_val > best[0]:
            best = (max_val, rect, templ)

    score, (x1, y1, x2, y2), _ = best
    cropped = full_img.crop((x1, y1, x2, y2))
    print(f"[template_utils] multiscale match {template_path.name}: score={score:.3f}, rect=({x1},{y1})-({x2},{y2})")
    return cropped, score
