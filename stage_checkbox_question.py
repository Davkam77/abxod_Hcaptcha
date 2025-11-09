from __future__ import annotations

import time

import cv2
import numpy as np
import pyautogui

from core import (
    BASE_DIR,
    PNG_DIR,
    MATCH_THRESHOLD_QUESTION,
    RETRY_INTERVAL_SEC,
    MAX_WAIT_SEC_STAGE2,
    img_to_b64,
    save_json,
    vision_json,
    detect_categories_in_text,
    categories_from_creature_hint,
    get_prompt,
)
from chrome_utils import screenshot_full
from template_utils import match_best_template


def click_checkbox_by_template() -> None:
    """
    Шаг 1: ищем checkbox по шаблону png/checkbox.png и кликаем.
    """
    template_path = PNG_DIR / "checkbox.png"
    if not template_path.is_file():
        raise FileNotFoundError(f"Template not found: {template_path}")

    img = screenshot_full()
    src_rgb = np.array(img)
    src = cv2.cvtColor(src_rgb, cv2.COLOR_RGB2BGR)
    templ = cv2.imread(str(template_path))
    if templ is None:
        raise RuntimeError(f"Failed to read template image: {template_path}")

    th, tw, _ = templ.shape
    res = cv2.matchTemplate(src, templ, cv2.TM_CCOEFF_NORMED)
    _min_val, max_val, _min_loc, max_loc = cv2.minMaxLoc(res)

    x1, y1 = max_loc
    x_center = x1 + tw // 2
    y_center = y1 + th // 2

    print(f"[stage_checkbox_question] checkbox match score={max_val:.3f}, click=({x_center},{y_center})")
    pyautogui.moveTo(x_center, y_center, duration=0.25)
    pyautogui.click()


def capture_question_to_json_retry() -> None:
    """
    Шаг 2: читаем панель с заданием.
    Вытаскиваем:
      - текст задания;
      - краткое правило отбора;
      - ключевые слова;
      - описание предмета-примера;
      - для каких существ этот предмет (птицы / собаки / и т.п.);
      - целевые категории target_categories / exclude_categories.
    Всё кладём в question.json.
    """
    template = PNG_DIR / "question_template.png"
    t0 = time.time()
    while time.time() - t0 < MAX_WAIT_SEC_STAGE2:
        img_full = screenshot_full()
        q_img, q_score = match_best_template(img_full, template)
        if q_score >= MATCH_THRESHOLD_QUESTION:
            q_b64 = img_to_b64(q_img)

            default_prompt = (
                "Это панель с текстом задания и примером в визуальной головоломке.\n"
                "Тебе нужно внимательно прочитать текст, посмотреть на пример (картинка справа) "
                "и понять, какие объекты или существа надо выбирать.\n\n"
                "Верни СТРОГО JSON вида:\n"
                "{\n"
                "  \"task_text\": \"<исходный текст задания одной строкой>\",\n"
                "  \"selection_criteria\": \"<кратко, кого/что нужно выбирать>\",\n"
                "  \"positive_keywords\": [\"...\"],\n"
                "  \"negative_keywords\": [\"...\"],\n"
                "  \"example_container\": \"<что за предмет показан в примере (1–3 слова)>\",\n"
                "  \"example_container_for_creature\": \"<для каких существ этот предмет служит домом/укрытием>\",\n"
                "  \"target_creature_category\": \"<bird / mammal / insect / fish / reptile / vehicle / clothing / container / any / unknown>\",\n"
                "  \"exclude_creature_category\": \"<если явно сказано, кого НЕ выбирать; иначе пусто>\"\n"
                "}\n"
                "Не выдумывай лишнее, опирайся только на текст и картинку."
            )
            prompt = get_prompt("question_extraction", default_prompt)

            data = vision_json(prompt, [q_b64])


            task_text = (data.get("task_text") or "").strip()
            selection_criteria = (data.get("selection_criteria") or "").strip()
            example_container = (data.get("example_container") or "").strip()
            example_for_creature = (data.get("example_container_for_creature") or "").strip()
            target_creature_category = (data.get("target_creature_category") or "").strip()
            exclude_creature_category = (data.get("exclude_creature_category") or "").strip()

            # локально добираем категории из текста и подсказок
            cats_from_text = detect_categories_in_text(task_text)
            cats_from_example = categories_from_creature_hint(example_for_creature)
            cats_from_target = categories_from_creature_hint(target_creature_category)

            target_categories = sorted(
                set(list(cats_from_text) + list(cats_from_example) + list(cats_from_target))
            )

            exclude_categories = sorted(list(categories_from_creature_hint(exclude_creature_category)))

            out = {
                "template": "question_template.png",
                "score": q_score,
                "image_b64": q_b64,
                "task_text": task_text,
                "selection_criteria": selection_criteria,
                "positive_keywords": data.get("positive_keywords") or [],
                "negative_keywords": data.get("negative_keywords") or [],
                "example_container": example_container,
                "example_container_for_creature": example_for_creature,
                "target_creature_category": target_creature_category,
                "exclude_creature_category": exclude_creature_category,
                "target_categories": target_categories,
                "exclude_categories": exclude_categories,
            }
            save_json(BASE_DIR / "question.json", out)
            return

        time.sleep(RETRY_INTERVAL_SEC)

    raise TimeoutError("[stage_checkbox_question] Question panel not found in time")
