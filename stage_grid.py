from __future__ import annotations

import time

from core import (
    BASE_DIR,
    PNG_DIR,
    MATCH_THRESHOLD_GRID,
    RETRY_INTERVAL_SEC,
    MAX_WAIT_SEC_STAGE2,
    img_to_b64,
    save_json,
    vision_json,
    ensure_tmp_dir,
    TMP_DIR,
    normalize_label,
    categories_from_label,
    get_prompt,
)
from chrome_utils import screenshot_full
from template_utils import match_template_multiscale


# Мягкий нижний порог: если основной порог не набрали, но лучший матч ≥ этого значения,
# используем его вместо падения по TimeoutError.
RELAXED_MATCH_THRESHOLD_GRID = 0.24


def capture_grid_objects_to_json_retry() -> None:
    """
    Режем сетку на 3×3, подписываем каждый тайл (label, conf),
    дополнительно сохраняем нормализованный лейбл и предполагаемые категории.

    Логика поиска:
      - основной порог совпадения: MATCH_THRESHOLD_GRID;
      - если за MAX_WAIT_SEC_STAGE2 так и не набрали MATCH_THRESHOLD_GRID,
        но был лучший матч с score >= RELAXED_MATCH_THRESHOLD_GRID — используем его;
      - если даже лучший матч ниже RELAXED_MATCH_THRESHOLD_GRID — кидаем TimeoutError.
    """
    template = PNG_DIR / "grid_template.png"
    t0 = time.time()
    ensure_tmp_dir()

    best_img = None
    best_score = -1.0

    selected_img = None
    selected_score = 0.0

    while time.time() - t0 < MAX_WAIT_SEC_STAGE2:
        img_full = screenshot_full()
        g_img, g_score = match_template_multiscale(img_full, template)

        # запоминаем лучший матч за всё время
        if g_img is not None and g_score > best_score:
            best_score = g_score
            best_img = g_img.copy()

        # основной порог
        if g_score >= MATCH_THRESHOLD_GRID:
            selected_img = g_img
            selected_score = g_score
            break

        time.sleep(RETRY_INTERVAL_SEC)

    # если основной порог не набрали — пробуем фоллбек по лучшему матчу
    if selected_img is None:
        if best_img is not None and best_score >= RELAXED_MATCH_THRESHOLD_GRID:
            print(
                f"[stage_grid] using relaxed grid match: "
                f"score={best_score:.3f}"
            )
            selected_img = best_img
            selected_score = best_score
        else:
            raise TimeoutError("[stage_grid] Grid panel not found in time")

    g_img = selected_img
    g_score = selected_score

    # дальше логика та же, что и раньше
    w, h = g_img.size
    cols, rows = 3, 3
    tile_w, tile_h = w // cols, h // rows

    objects = []
    idx = 0
    for r in range(rows):
        for c in range(cols):
            x1 = c * tile_w
            y1 = r * tile_h
            x2 = w if c == cols - 1 else (c + 1) * tile_w
            y2 = h if r == rows - 1 else (r + 1) * tile_h

            tile = g_img.crop((x1, y1, x2, y2))
            p = TMP_DIR / f"tile_{idx}.png"
            tile.save(p)

            # --- подпись тайла через Vision ---
            b64 = img_to_b64(tile)
            default_label_prompt = (
                "Назови, что изображено на картинке, ОЧЕНЬ кратко (1–2 слова, "
                "существительное в И.п.).\n"
                "Верни строго JSON: {\"label\":\"<слово>\", \"conf\": <0..1>}.\n"
                "Если не уверен — label:\"\", conf:0."
            )
            label_prompt = get_prompt("grid_tile_label", default_label_prompt)
            lbl = vision_json(label_prompt, [b64])

            # аккуратно достаём label / conf из dict
            label = (lbl.get("label") or "").strip().lower()
            try:
                conf = float(lbl.get("conf") or 0.0)
            except (TypeError, ValueError):
                conf = 0.0

            # нормализованный лейбл + категории
            norm = normalize_label(label)
            cats = sorted(list(categories_from_label(label)))

            objects.append(
                {
                    "index": idx,
                    "template_path": str(p),
                    "grid_rc": [r, c],
                    "center": [(x1 + x2) // 2, (y1 + y2) // 2],
                    "label": label,
                    "label_conf": conf,
                    "norm_label": norm,
                    "categories": cats,   # напр.: ["bird"]
                }
            )
            idx += 1

    out = {
        "template": "grid_template.png",
        "score": g_score,
        "objects": objects,
        "grid_shape": [rows, cols],
    }
    save_json(BASE_DIR / "grid_objects.json", out)
