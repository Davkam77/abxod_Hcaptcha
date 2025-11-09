# context.md

Технический конспект для разработчиков: описывает взаимосвязи модулей, порядок стадий и ключевые решения в проекте `abxod_Hcaptcha`.

## 1. Общий конвейер

```
main.py
├─ donttouch.ensure()               # контроль шаблонов
├─ chrome_utils.ensure_chrome...    # окно Chrome + URL
├─ stage_checkbox_question.click... # stage 1: чекбокс
├─ stage_checkbox_question.capture  # stage 2: вопрос → question.json
├─ stage_grid.capture...            # stage 3a: сетка → grid_objects.json
└─ stage_analyze.analyze...         # stage 3b: анализ → grid_choice.json + клики
```

Каждая стадия использует общий набор helper’ов из `core.py` (константы, промпты, Vision) и `chrome_utils` (скриншоты). JSON-артефакты служат контрактами между стадиями: вопрос и тайлы можно переиспользовать без повторного скриншота.

## 2. Модули и связи

| Модуль | Роль | Зависимости | Выход |
| --- | --- | --- | --- |
| `core.py` | Центральный «сервис» с путями, порогами, клиентом OpenAI и текстовой таксономией. Реализует `vision_json`, нормализацию label’ов, определение категорий и работу с промптами. | `config.OPENAI_API_KEY`, `PIL`, `openai`, `json`, `re`. | Строковые константы, функции utility, объект `client`. |
| `chrome_utils.py` | Управляет Chrome через pyautogui: гарантирует активное окно, вводит URL, делает скриншоты. | `.env` из `config`, `pyautogui`, `pygetwindow`, `subprocess`. | Функции `ensure_chrome_and_open_url`, `screenshot_full`. |
| `stage_checkbox_question.py` | Этапы 1 и 2. Сначала находит чекбокс по `png/checkbox.png`, затем ловит панель вопроса, отправляет в Vision и сохраняет JSON. | `template_utils.match_best_template`, `chrome_utils.screenshot_full`, `core.vision_json`. | `question.json`. |
| `stage_grid.py` | Находит сетку (`png/grid_template.png`), режет на 3×3, вызывает Vision для label/conf каждого тайла. | `template_utils.match_template_multiscale`, `core.img_to_b64`, `core.normalize_label`, `core.categories_from_label`. | `grid_objects.json`. |
| `stage_analyze.py` | Собирает question/grid, формирует общий prompt Vision и кликает по выбранным тайлам. | `core.vision_json`, `core.extract_json_object`, `chrome_utils.screenshot_full`, OpenCV/pyautogui. | `grid_choice.json` + реальные клики. |
| `donttouch.py` | Контроль целостности `png/donttouch.png`: baseline, hash, read-only. | `hashlib`, `shutil`, `stat`. | Восстановленный PNG, предотвращение случайной правки. |
| `template_utils.py` | Обёртки над OpenCV Template Matching (обычный и multiscale). | `cv2`, `numpy`, `PIL`. | Кропы нужных панелей + score. |
| `png/chekbox.py`, `vision_agent.py` | Экспериментальные скрипты: прямой Vision для чекбокса/координат. | OpenAI, PIL, pyautogui. | Не участвуют в основном пайплайне, но могут вдохновить на новые функции. |

## 3. Детали стадий

### 3.1 Stage 1 — клик по чекбоксу
- В `stage_checkbox_question.click_checkbox_by_template()` производится полный скриншот (`chrome_utils.screenshot_full`), затем `cv2.matchTemplate` сравнивает его с `png/checkbox.png`.
- Найденный прямоугольник переводится в координаты центра и передаётся `pyautogui` для клика.
- Ошибки шаблона (не найден, плохой score) поднимаются исключением: лучше заменить PNG.

### 3.2 Stage 2 — извлечение вопроса
- `match_best_template` ищет `png/question_template.png`. Пока `score < MATCH_THRESHOLD_QUESTION`, делаются повторные попытки с задержкой `RETRY_INTERVAL_SEC`, но не дольше `MAX_WAIT_SEC_STAGE2`.
- Картинка панели кодируется через `core.img_to_b64` и отправляется в Vision с prompt `question_extraction` (может переопределяться в `prompts.json`).
- Результат дополняется псевдо-NLP обработкой: `detect_categories_in_text`, `categories_from_creature_hint`.
- Итог сохраняется в `question.json` и включает сам скрин (base64) для повторных тестов.

### 3.3 Stage 3a — сетка тайлов
- `match_template_multiscale` подбирает масштаб шаблона `png/grid_template.png`, чтобы выдерживать разные разрешения.
- После нарезки на 9 прямоугольников каждый tile сохраняется в `tmp_clicks/tile_{i}.png` (позже используется повторно).
- Для каждого тайла формируется Vision prompt `grid_tile_label` → ожидаем JSON вида `{ "label": "...", "conf": 0..1 }`.
- `core.normalize_label` чистит строку, `categories_from_label` сопоставляет с таксономией (`bird`, `mammal`, `vehicle`, ...). Эти категории помогут на стадии анализа.

### 3.4 Stage 3b — анализ и клики
- `stage_analyze.analyze_json_and_click_by_images()` читает `question.json` и `grid_objects.json`.
- `question_b64` + список тайлов собираются в `image_list`. Vision получает большой prompt с описанием задания, критериев и индексов.
- Ответ ожидается в JSON `{ "indexes": [...], "reason": "..." }`. Если модель вернула число как позицию в массиве, код пытается отобразить его обратно к фактическому индексу (`index_order`).
- **Постобработка:**  
  - `match_categories` проверяет попадание в `target_categories` и отсутствие пересечения с `exclude_categories`.  
  - Спецкейс «birdhouse»: если пример содержит «скворечник»/`birdhouse`, берутся только тайлы, где label или categories указывают на птиц.  
  - Конечный список сортируется и пишется в `grid_choice.json` вместе с исходным ответом Vision.
- После фиксации индексов берётся свежий скриншот всей страницы, и для каждого тайла повторно выполняется `cv2.matchTemplate`, чтобы найти координаты клика в живом интерфейсе. Это защищает от смещений между моментом съёмки и настоящим кликом.

## 4. Работа с OpenAI Vision

Функция `core.vision_json(prompt, image_b64_list)` реализует двухступенчатую схему:
1. Пытается вызвать `client.responses.create(..., response_format={"type": "json_object"})` и парсит `resp.output_parsed`.
2. Если API вернул текст, запускается fallback со сборкой `resp.output_text` и `core.extract_json_object` для извлечения первого валидного JSON-блока.

Таким образом, stage-модули всегда получают dict, даже если модель не выполнила строгий JSON output. Настройки модели (`model="gpt-4.1-mini"`) собраны в одном месте и легко меняются.

## 5. Таксономия и фильтрация

- `core.TAXONOMY` — словарь категорий → список ключевых слов (латиница + кириллица). Его используют:  
  - `detect_categories_in_text` (поиск в задании).  
  - `categories_from_label` (по vision label тайла).  
  - `categories_from_creature_hint` (разбор текстовых подсказок).
- Пороговые значения: `MATCH_THRESHOLD_OBJECT`, `CONF_TILE_LABEL_OK`, `VISUAL_SIM_THRESHOLD`, `DEDUP_RADIUS_PX`. Они участвуют в фильтрации чекбоксов/тайлов и защите от дрожания координат.
- Спецкейс `birdhouse` в `stage_analyze` опирается на `target_categories` и на содержимое `example_container`: если указано строение для птиц, алгоритм принудительно выбирает тайлы с меткой «bird».

## 6. Управление шаблонами

- Все эталонные PNG лежат в `png/`. Важные файлы:  
  - `checkbox.png` — маска для первого клика.  
  - `question_template.png` — bounding box панели вопроса.  
  - `grid_template.png` — bounding box сетки 3×3.  
  - `donttouch.png` — образец для контроля целостности.  
  - `next.png` — заготовка для будущей кнопки «Next challenge».
- `donttouch.py` предоставляет API: `init_baseline`, `verify_or_restore`, `safe_update`, `ensure`. Он хранит sha256 в `png/donttouch.sha256` и backup в `png/donttouch.backup.png`. Все операции снимают/возвращают read-only атрибуты, чтобы любая ручная правка была заметна.

## 7. Временные файлы

- `core.TMP_DIR` (`tmp_clicks/`) создаётся `core.ensure_tmp_dir()` и очищается `cleanup_tmp_dir()`. В нём лежат `tile_*.png`, которые используются как шаблоны при финальных кликах (template matching на живом экране).
- Эти файлы можно использовать для отладки (например, смотреть, что именно отправилось в Vision). Важен порядок (`index_order`), который сохраняется в `grid_choice.json` для восстановления соответствия.

## 8. Дополнительные утилиты

- `png/chekbox.py` — альтернативный способ найти чекбокс: вместо template matching отправляет Vision prompt с референсными PNG из `png/`.
- `vision_agent.py` — упрощённый клиент, который принимает произвольный `query` и возвращает координаты `(x, y)` для переданной картинки; полезно для тестирования отдельных элементов.

## 9. Известные ограничения

1. **Жёсткая привязка к Windows** — используются `pyautogui` и `pygetwindow` с Windows hotkey. Для Linux/macOS нужна адаптация.
2. **Масштабирование дисплея** — если в Windows стоит масштаб ≠ 100 %, шаблоны могут не совпадать.
3. **Зависимость от OpenAI** — любой сетевой сбой или превышение квоты остановит пайплайн. Нет локального fallback-а.
4. **Недетерминированность Vision** — иногда модель возвращает индексы как строки/дроби; код пытается привести их к int, но это может давать неожиданные результаты.
5. **Повторные сетки** — автоматический клик по кнопке «Next» пока не реализован, поэтому скрипт рассчитан на одну сетку.

## 10. Возможные расширения

- Добавить стадию для обработки «ещё одно испытание» (`png/next.png` + отдельный Vision prompt).
- Интегрировать DevTools Protocol, чтобы получать DOM-координаты без template matching.
- Кэшировать Vision-ответы для одинаковых тайлов (хеш изображения + файл истории).
- Расширить `prompts.json` вариантами под разные языки/темы hCaptcha.

Документ поддерживает README.md: там описаны инструкции по установке и запуску. Здесь собраны технические детали и взаимосвязи между файлами.
