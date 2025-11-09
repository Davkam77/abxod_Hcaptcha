# context.md

Техконспект по проекту `abxod_Hcaptcha`: описывает связи модулей, форматы артефактов и алгоритмы трёх стадий.

## 1. Общий конвейер

```
main.py
├─ donttouch.ensure()               # контроль PNG
├─ chrome_utils.ensure_chrome...    # активируем/запускаем Chrome
├─ stage_checkbox_question.click... # Stage 0: клик по checkbox.png
├─ stage_checkbox_question.capture  # Stage 1: вопрос → question.json
├─ stage_grid.capture...            # Stage 2: сетка → grid_objects.json
└─ stage_analyze.analyze...         # Stage 3: анализ → grid_choice/verify + клики
```

Каждый этап использует `core.py` (пути, промпты, Vision helper’ы) и `chrome_utils` (скриншоты). JSON‑файлы — протокол между стадиями; их можно править вручную для повторного анализа.

## 2. Файлы и зависимости

| Модуль | Роль | Зависимости | Артефакты |
| --- | --- | --- | --- |
| `core.py` | Центр: пути (`BASE_DIR`, `TMP_DIR`), пороги (`MATCH_*`), OpenAI client, таксономия, `vision_json`, `get_prompt`, `save_json`. | `config`, `PIL`, `openai`, `json`. | `question.json`, `grid_objects.json`, `grid_choice.json`, `grid_verify.json` (через `save_json`). |
| `chrome_utils.py` | Работа с Chrome: активное окно, ввод URL, `screenshot_full`. | `.env`, `pyautogui`, `pygetwindow`. | Скриншоты (PIL). |
| `stage_checkbox_question.py` | Stage 0/1: кликает checkbox, затем ловит панель вопроса по `question_template.png`, отправляет в Vision (`question_extraction`), сохраняет `question.json`. | `template_utils.match_best_template`, `core.get_prompt`. | `question.json`. |
| `stage_grid.py` | Stage 2: ищет `grid_template.png` (multiscale), режет 3×3, сохраняет `tmp_clicks/tile_i.png`, подписывает тайлы через Vision (`grid_tile_label`). | `template_utils.match_template_multiscale`, `core.img_to_b64`, `core.categories_from_label`. | `grid_objects.json`, `tmp_clicks/*.png`. |
| `stage_analyze.py` | Stage 3: объединяет вопрос+тайлы, вызывает Vision (`grid_selection`), кликает, запускает суперверификацию (до 2 автокоррекций) и пишет логи. | `core.get_prompt`, `chrome_utils.screenshot_full`, OpenCV, `pyautogui`. | `grid_choice.json`, `grid_verify.json`. |
| `template_utils.py` | Обёртки над `cv2.matchTemplate`. | `cv2`, `numpy`. | Используется в stage-модулях (клик checkbox, поиск панелей). |
| `stage_next_done.py` | Универсальный клик по `next.png` / `done.png`. | `chrome_utils.screenshot_full`, `core.MATCH_THRESHOLD_OBJECT`. | Используется в `main.py`. |
| `donttouch.py` | Hash-защита PNG: baseline, verify, safe_update. | `hashlib`, `shutil`. | `png/donttouch.*`. |
| `prompts.json` | Переопределение промптов (`grid_selection`, `verify_selection`, `question_extraction`, `grid_tile_label`). | `core.get_prompt`. | --- |

## 3. Детали стадий

### Stage 0/1 — чекбокс и вопрос
- `click_checkbox_by_template()` делает screenshot и ищет `checkbox.png`. Центр прямоугольника передаётся в `pyautogui`.
- `capture_question_to_json_retry()`:
  1. Находит `question_template.png`.
  2. Отправляет вырез в Vision (prompt можно переопределить).
  3. Дополняет категории с помощью `core.detect_categories_in_text` / `categories_from_creature_hint`.
  4. Сохраняет `question.json` (включая `image_b64` панели для отладки).

### Stage 2 — сетка
- `stage_grid.capture_grid_objects_to_json_retry()`:
  1. Находит `grid_template.png` multiscale.
  2. Делит картинку на 9 тайлов, сохраняет `tmp_clicks/tile_i.png`.
  3. Для каждого тайла вызывает Vision (`grid_tile_label`) → `label`, `conf`.
  4. Считает `norm_label = core.normalize_label(label)`, категории по таксономии.
  5. Пишет `grid_objects.json` (порядок `index_order` = 0..8).

### Stage 3 — анализ, клики, суперпроверка

**Входы:** `question.json`, `grid_objects.json`.  
**Основные шаги:**

1. **Vision выбор.** `grid_selection` получает `[question_b64] + tiles` и возвращает `{indexes, reason}`. Результат нормализуется `_sanitize_indexes`.
2. **Постфильтры (`_apply_post_filters`):**
   - `target_categories` / `exclude_categories`;
   - задачи «выберите всех …» → добираем все тайлы с тем же `norm_label`/категорией;
   - birdhouse/скворечник/дупло → оставляем только тайлы с птицами.
3. **Клики.** `screenshot_full()` + `_locate_tiles()` → координаты совпадений с `tmp_clicks/tile_i.png`. `_click_tiles()` кликает все выбранные индексы (пропуская матчи ниже `MATCH_THRESHOLD_OBJECT`).
4. **Суперпроверка (`_verification_loop`):**
   - Константы: `VERIFY_PAUSE`, `MAX_FIX_ROUNDS = 2`.
   - На каждой итерации:
     - ждём паузу, снимаем скрин;
     - `_verify_with_vision()` получает:
       * текст задания (`task_text`, `selection_criteria`);
       * индексацию 0..8;
       * `expected_from_stage1` — список из первого этапа;
       * подсказки: «клавиатура → мышь/монитор», «скворечник → только птицы», и др.;
       * просит вернуть JSON `{correct_indexes, selected_indexes, ok, reason}`.
     - Индексы прогоняются через `_sanitize_indexes`. Если Vision не указал correct, используется список первого этапа.
     - `missed = correct - selected`, `extra = selected - correct`.
     - Логируем попытку в `attempts`.
     - Если `ok` и нет расхождений → выходим с успехом.
     - Если попыток осталось и сетка не сменилась (достаточно match’ей):
       * кликаем `missed` (`action="add"`);
       * кликаем `extra` (`action="remove"`);
       * результаты пишем в `actions` (attempt, action, index, result, score).
     - Если `len(detections) <= len(index_order)//2`, считаем, что сетка изменилась (`note: "grid_changed"`) и прекращаем цикл.
5. **Логи.**
   - `grid_choice.json` содержит `index_order`, `raw_from_model`, `chosen_indexes`, `reason`.
   - `grid_verify.json` содержит `chosen_indexes`, `attempts`, `actions`, `ok`.
6. **Возврат.** Функция возвращает `True`, если финальный `ok`, иначе `False`. `main.py` решает, кликать ли NEXT/DONE.

## 4. Артефакты JSON

### question.json
```json
{
  "task_text": "...",
  "selection_criteria": "...",
  "positive_keywords": [],
  "negative_keywords": [],
  "example_container": "...",
  "target_categories": ["bird"],
  "exclude_categories": [],
  "image_b64": "..."
}
```

### grid_objects.json
```json
{
  "objects": [
    {
      "index": 0,
      "template_path": "tmp_clicks/tile_0.png",
      "label": "кошка",
      "label_conf": 0.91,
      "norm_label": "кошка",
      "categories": ["mammal"]
    },
    ...
  ]
}
```

### grid_choice.json
```json
{
  "task_text": "...",
  "selection_criteria": "...",
  "index_order": [0,1,2,3,4,5,6,7,8],
  "raw_from_model": [0,2,5],
  "chosen_indexes": [2,5],
  "reason": "Vision explanation"
}
```

### grid_verify.json
```json
{
  "chosen_indexes": [2,5],
  "attempts": [
    {
      "attempt": 0,
      "correct_indexes": [2,5],
      "selected_indexes": [2],
      "missed": [5],
      "extra": [],
      "ok": false,
      "verify_reason": "tile 5 not highlighted"
    },
    {
      "attempt": 1,
      "correct_indexes": [2,5],
      "selected_indexes": [2,5],
      "missed": [],
      "extra": [],
      "ok": true,
      "verify_reason": "all good after correction"
    }
  ],
  "actions": [
    {"attempt": 0, "action": "add", "index": 5, "result": "clicked", "score": 0.82}
  ],
  "ok": true
}
```

## 5. Семантика и эвристики
- `core.TAXONOMY` содержит после слов возможные категории (`bird`, `vehicle`, `computer_accessory` и т.д.). Используется:
  - при фильтрации Vision-ответов;
  - в birdhouse-спецкейсе (ключевые слова: «birdhouse», «скворечн», «домик для птиц», «дупло»).
- В `_apply_post_filters`:
  - `target_categories` / `exclude_categories` из `question.json`;
  - задания «выберите всех …» ищут одинаковые `norm_label` или категории;
  - fallback при пустом списке — если `target_categories` заполнены или текст содержит `creature`.
- В `_verify_with_vision` подсказки помогают Vision понять контекст (например, «клавиатура → ищем компьютерные аксессуары»).

## 6. Промпты
- `grid_selection` — основной выбор индексов.
- `verify_selection` — суперпроверка; принимает в prompt текст задания и список индексов, которые уже выбраны.
- `question_extraction`, `grid_tile_label` — извлечение текста и подписей тайлов.
Все промпты можно переопределить в `prompts.json`. Если ключ отсутствует, используется встроенный текст.

## 7. Тайминги и пороги
- `MATCH_THRESHOLD_QUESTION`, `MATCH_THRESHOLD_GRID`, `MATCH_THRESHOLD_OBJECT` — минимальные коэффициенты `cv2.matchTemplate`.
- `RETRY_INTERVAL_SEC`, `MAX_WAIT_SEC_STAGE2` — таймауты при поиске шаблонов.
- `CLICK_PAUSE` (0.18 c) — задержка между кликами.
- `VERIFY_PAUSE` (0.4 c) — пауза перед каждым скрином суперпроверки.
- `MAX_FIX_ROUNDS = 2` — максимум дополнительных попыток автокоррекции.

## 8. Переходы NEXT / DONE
`main.py` выполняет три раунда:
1. После первых двух `analyze...()` возвращает bool; если стадия прошла, `stage_next_done.click_next_button()` ищет `next.png`. Если шаблон не найден — просто логируем.
2. После третьего раунда вызывается `click_done_button()` (`done.png`).
Шаблон `next.png`/`done.png` должен подходить под тему задачи; при необходимости замените PNG и обновите baseline через `donttouch.py`.

## 9. Отладка
- `tmp_clicks/grid_before.png`, `grid_after_*.png` — снимки перед и после кликов.
- `grid_choice.json` + `grid_verify.json` — полный trace Vision-решений.
- Для повторного теста можно заменить `grid_objects.json`/`question.json` и запустить только `stage_analyze.analyze_json_and_click_by_images()`.

## 10. Риски и TODO
- Vision может вернуть индексы вне 0..8 — `_sanitize_indexes` фильтрует, но лучше расширить подсказки.
- Если сетка сменится во время суперпроверки, цикл остановится с `grid_changed`. Нужна стратегия перезапуска (TODO).
- Стоимость API: минимум 12 запросов на одну сетку (9 тайлов + панель + анализ + одна или две проверки). Рассмотрите кэширование Vision-ответов.

Дополнительные подробности по пользовательской инструкции — в `README.md`.
