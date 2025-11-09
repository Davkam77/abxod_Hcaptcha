from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import cv2
import numpy as np
import pyautogui
from PIL import Image

from chrome_utils import screenshot_full
from template_utils import match_best_template
from core import (
    BASE_DIR,
    TMP_DIR,
    MATCH_THRESHOLD_OBJECT,
    CONF_TILE_LABEL_OK,
    save_json,
    img_to_b64,
    vision_json,
    normalize_label,
    labels_similar,
    ensure_tmp_dir,
    get_prompt,
)

LIVING_CATEGORIES = {"bird", "mammal", "insect", "fish", "reptile"}

CLICK_PAUSE = 0.18
VERIFY_PAUSE = 0.4
MAX_FIX_ROUNDS = 2


def _sanitize_indexes(values: List[Any], index_order: List[int]) -> List[int]:
    result: List[int] = []
    for v in values or []:
        try:
            idx = int(v)
        except Exception:
            continue
        if idx not in index_order:
            if 0 <= idx < len(index_order):
                idx = index_order[idx]
            else:
                continue
        if idx not in result:
            result.append(idx)
    return sorted(result)


def _locate_tiles(full_img: Image.Image, objects: List[dict]) -> Tuple[Dict[int, dict], np.ndarray]:
    src = cv2.cvtColor(np.array(full_img), cv2.COLOR_RGB2BGR)
    detections: Dict[int, dict] = {}
    for obj in objects:
        idx = int(obj["index"])
        tpath = Path(obj["template_path"])
        templ = cv2.imread(str(tpath), cv2.IMREAD_COLOR)
        if templ is None:
            continue
        th, tw = templ.shape[:2]
        res = cv2.matchTemplate(src, templ, cv2.TM_CCOEFF_NORMED)
        _minv, maxv, _minl, maxl = cv2.minMaxLoc(res)
        x1, y1 = maxl
        detections[idx] = {
            "score": float(maxv),
            "center": (int(x1 + tw // 2), int(y1 + th // 2)),
            "rect": (int(x1), int(y1), int(x1 + tw), int(y1 + th)),
        }
    return detections, src


def _click_tiles(indexes: List[int], detections: Dict[int, dict], action: str, log: List[dict] | None, attempt: int | None) -> None:
    for idx in indexes:
        det = detections.get(idx)
        if not det or det["score"] < MATCH_THRESHOLD_OBJECT:
            print(f"[stage_analyze] skip {action} idx={idx} (missing/low score)")
            if log is not None:
                log.append({"attempt": attempt, "action": action, "index": idx, "result": "skip", "score": det["score"] if det else None})
            continue
        cx, cy = det["center"]
        pyautogui.moveTo(cx, cy, duration=0.12)
        pyautogui.click()
        time.sleep(CLICK_PAUSE)
        if log is not None:
            log.append({"attempt": attempt, "action": action, "index": idx, "result": "clicked", "score": det["score"]})


def _verify_with_vision(full_img: Image.Image, index_order: List[int]) -> dict:
    prompt_default = (
        "На изображении сетка 3x3 после кликов.\n"
        "Верни строго JSON {"
        '  "correct_indexes": [<int>],'
        '  "selected_indexes": [<int>],'
        '  "ok": <bool>,'
        '  "reason": "<кратко>"'
        "}\n"
        "correct_indexes — какие тайлы должны быть выбраны по заданию,"
        "selected_indexes — какие визуально подсвечены."
    )
    prompt = get_prompt("verify_selection", prompt_default)
    resp = vision_json(prompt, [img_to_b64(full_img)])
    if not isinstance(resp, dict):
        resp = {}
    correct = _sanitize_indexes(resp.get("correct_indexes") or [], index_order)
    selected = _sanitize_indexes(resp.get("selected_indexes") or [], index_order)
    ok = bool(resp.get("ok"))
    reason = (resp.get("reason") or "").strip()
    return {"correct": correct, "selected": selected, "ok": ok, "reason": reason}


def _click_next_button(full_img: Image.Image | None) -> None:
    if full_img is None:
        return
    try:
        next_png = BASE_DIR / "png" / "next.png"
        if not next_png.is_file():
            return
        cropped, score = match_best_template(full_img, next_png)
        if score < MATCH_THRESHOLD_OBJECT:
            print("[stage_analyze] next template score too low, skip")
            return
        templ = cv2.imread(str(next_png), cv2.IMREAD_COLOR)
        src = cv2.cvtColor(np.array(full_img), cv2.COLOR_RGB2BGR)
        _minv, maxv, _minl, maxl = cv2.minMaxLoc(cv2.matchTemplate(src, templ, cv2.TM_CCOEFF_NORMED))
        x1, y1 = maxl
        th, tw = templ.shape[:2]
        cx, cy = int(x1 + tw // 2), int(y1 + th // 2)
        pyautogui.moveTo(cx, cy, duration=0.12)
        pyautogui.click()
        print("[stage_analyze] clicked NEXT")
    except Exception as e:
        print(f"[stage_analyze] NEXT click failed: {e}")


def _apply_post_filters(chosen: List[int], objects: List[dict], question: dict, index_order: List[int]) -> List[int]:
    index_to_obj = {int(o["index"]): o for o in objects}
    chosen_set = set(chosen)
    target_cats = set(question.get("target_categories") or [])
    exclude_cats = set(question.get("exclude_categories") or [])
    task_text = (question.get("task_text") or "") + " " + (question.get("selection_criteria") or "")
    is_all_task = any(word in task_text.lower() for word in (" все", "all", "кажд", "всех"))

    if not chosen_set and target_cats:
        for obj in objects:
            idx = int(obj["index"])
            cats = set(obj.get("categories") or [])
            if cats.intersection(target_cats):
                chosen_set.add(idx)

    if not chosen_set and "creature" in task_text.lower():
        for obj in objects:
            idx = int(obj["index"])
            cats = set(obj.get("categories") or [])
            conf = float(obj.get("label_conf") or 0.0)
            if cats.intersection(LIVING_CATEGORIES) and conf >= CONF_TILE_LABEL_OK:
                chosen_set.add(idx)

    def _match_cats(idx: int) -> bool:
        obj = index_to_obj.get(idx)
        if not obj:
            return False
        cats = set(obj.get("categories") or [])
        if target_cats and not cats.intersection(target_cats):
            return False
        if exclude_cats and cats.intersection(exclude_cats):
            return False
        return True

    filtered = [idx for idx in chosen_set if _match_cats(idx)]
    if filtered:
        chosen_set = set(filtered)

    if is_all_task and chosen_set:
        label_pool = set()
        cat_pool = set()
        for idx in chosen_set:
            obj = index_to_obj.get(idx, {})
            label_pool.add(obj.get("norm_label") or normalize_label(obj.get("label") or ""))
            cat_pool.update(obj.get("categories") or [])
        for obj in objects:
            idx = int(obj["index"])
            if idx in chosen_set:
                continue
            norm = obj.get("norm_label") or normalize_label(obj.get("label") or "")
            cats = set(obj.get("categories") or [])
            if any(labels_similar(norm, other) for other in label_pool if other) or cats.intersection(cat_pool):
                chosen_set.add(idx)

    example_lower = (question.get("example_container") or "").lower()
    if any(word in example_lower for word in ("birdhouse", "скворечн", "домик для птиц")):
        bird_only = []
        for obj in objects:
            idx = int(obj["index"])
            label = (obj.get("label") or "").lower()
            cats = obj.get("categories") or []
            if (
                "bird" in cats
                or "птиц" in label
                or "sparrow" in label
                or "вороб" in label
                or "голуб" in label
            ):
                bird_only.append(idx)
        chosen_set = set(bird_only)

    return sorted(idx for idx in chosen_set if idx in index_order)


def _verification_loop(chosen: List[int], index_order: List[int], objects: List[dict]) -> Tuple[bool, List[dict], List[dict], Image.Image | None]:
    attempts: List[dict] = []
    actions: List[dict] = []
    last_img: Image.Image | None = None
    for attempt in range(MAX_FIX_ROUNDS + 1):
        time.sleep(VERIFY_PAUSE)
        full = screenshot_full()
        last_img = full
        detections, _ = _locate_tiles(full, objects)
        verify = _verify_with_vision(full, index_order)
        correct_set = set(verify["correct"] or chosen)
        selected_set = set(verify["selected"])
        missed = sorted(correct_set - selected_set)
        extra = sorted(selected_set - correct_set)
        attempts.append(
            {
                "attempt": attempt,
                "correct_indexes": sorted(correct_set),
                "selected_indexes": sorted(selected_set),
                "missed": missed,
                "extra": extra,
                "ok": verify["ok"],
                "verify_reason": verify["reason"],
            }
        )
        if verify["ok"] and not missed and not extra:
            return True, attempts, actions, full
        if attempt >= MAX_FIX_ROUNDS:
            break
        if len(detections) <= len(index_order) // 2:
            attempts[-1]["note"] = "grid_changed"
            break
        if missed:
            print(f"[stage_analyze] missed indexes {missed}")
            _click_tiles(missed, detections, "add", actions, attempt)
        if extra:
            print(f"[stage_analyze] extra indexes {extra}")
            _click_tiles(extra, detections, "remove", actions, attempt)
    return False, attempts, actions, last_img


def analyze_json_and_click_by_images() -> bool:
    q_path = BASE_DIR / "question.json"
    g_path = BASE_DIR / "grid_objects.json"
    if not q_path.exists() or not g_path.exists():
        print("[stage_analyze] question.json / grid_objects.json not found.")
        return False

    try:
        question = json.loads(q_path.read_text(encoding="utf-8"))
        grid = json.loads(g_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[stage_analyze] cannot read inputs: {e}")
        return False

    objects = grid.get("objects", [])
    question_b64 = question.get("image_b64")
    if not question_b64 or not objects:
        print("[stage_analyze] missing question image or grid objects")
        return False

    tiles_b64: List[str] = []
    index_order: List[int] = []
    for obj in objects:
        idx = int(obj["index"])
        tpath = Path(obj["template_path"])
        if not tpath.is_file():
            print(f"[stage_analyze] template missing for {idx}: {tpath}")
            continue
        try:
            tiles_b64.append(img_to_b64(Image.open(tpath).convert("RGB")))
            index_order.append(idx)
        except Exception as e:
            print(f"[stage_analyze] cannot load tile {tpath}: {e}")

    if not tiles_b64:
        print("[stage_analyze] no tile images loaded")
        return False

    selection_prompt = (
        "Ты решаешь визуальную головоломку. Сначала идёт панель с текстом задания, затем 9 тайлов сетки.\n"
        "Выбери ВСЕ подходящие тайлы и верни JSON {\"indexes\": [<int>, ...], \"reason\": \"...\"}.\n"
        f"Задание: {question.get('task_text')}\nПравило: {question.get('selection_criteria')}\nПорядок индексов: {index_order}"
    )
    prompt = get_prompt("grid_selection", selection_prompt)
    try:
        parsed = vision_json(prompt, [question_b64] + tiles_b64)
    except Exception as e:
        print(f"[stage_analyze] vision selection failed: {e}")
        return False
    if not isinstance(parsed, dict):
        parsed = {}

    raw_idxs = parsed.get("indexes", [])
    chosen_indexes = _sanitize_indexes(raw_idxs if isinstance(raw_idxs, (list, tuple)) else [], index_order)
    chosen_indexes = _apply_post_filters(chosen_indexes, objects, question, index_order)
    reason = (parsed.get("reason") or "").strip()
    save_json(
        BASE_DIR / "grid_choice.json",
        {
            "task_text": question.get("task_text"),
            "selection_criteria": question.get("selection_criteria"),
            "index_order": index_order,
            "chosen_indexes": chosen_indexes,
            "raw_from_model": raw_idxs,
            "reason": reason,
        },
    )

    if not chosen_indexes:
        print("[stage_analyze] model returned nothing to click")
        save_json(BASE_DIR / "grid_verify.json", {"chosen_indexes": [], "attempts": [], "actions": [], "ok": False})
        return False

    ensure_tmp_dir()
    before = screenshot_full()
    try:
        before.save(str(TMP_DIR / "grid_before.png"))
    except Exception:
        pass

    detections, _ = _locate_tiles(before, objects)
    _click_tiles(chosen_indexes, detections, "initial", log=None, attempt=None)

    final_ok, attempts_log, actions_log, last_img = _verification_loop(chosen_indexes, index_order, objects)
    save_json(
        BASE_DIR / "grid_verify.json",
        {
            "chosen_indexes": chosen_indexes,
            "attempts": attempts_log,
            "actions": actions_log,
            "ok": final_ok,
        },
    )

    _click_next_button(last_img)
    return final_ok
