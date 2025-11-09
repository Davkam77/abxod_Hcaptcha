# abxod_Hcaptcha

Автоматизирует решение визуальных заданий hCaptcha: скрипт открывает Chrome, находит чекбокс и панель с вопросом, распознаёт текст задания через OpenAI Vision, извлекает 9 тайлов сетки, классифицирует их и кликает подходящие картинки. Код написан под Windows, использует `pyautogui`, OpenCV и OpenAI Responses API.

## Основные возможности
- Пошаговая автоматизация hCaptcha (checkbox → вопрос → сетка → выбор тайлов).
- Распознавание текста задания и примеров на скриншотах с помощью GPT‑4.1‑mini (JSON‑ответ Vision).
- Формирование структурированных артефактов: `question.json`, `grid_objects.json`, `grid_choice.json`.
- Постобработка выбора: фильтрация по таксономии (`core.TAXONOMY`) и спецкейс «birdhouse».
- Поддержка шаблонов PNG с контролем целостности (`donttouch.py`) и временного кэша тайлов.

## Структура репозитория

| Файл/директория | Назначение | Связи |
| --- | --- | --- |
| `main.py` | Точка входа; запускает стадии `donttouch`, Chrome и все step-модули. | Импортирует `donttouch.ensure`, `chrome_utils`, `stage_*`. |
| `config.py` + `.env` | Загружает переменные окружения: OpenAI, Chrome, URL, прокси. | Используется во всех модулях, где нужны ключи/пути. |
| `core.py` | Общие константы, работа с промптами, OpenAI client, таксономия, нормализация и Vision-helpers. | Вызывается из stage-модулей, `chrome_utils`, `template_utils`. |
| `stage_checkbox_question.py` | 1) клик по чекбоксу по шаблону; 2) поиск панели вопроса и генерация `question.json`. | Нуждается в `template_utils.match_best_template`, `chrome_utils.screenshot_full`, `core.vision_json`. |
| `stage_grid.py` | Вырезает сетку 3×3, делит на тайлы, подписывает каждый через Vision → `grid_objects.json`. | Использует `core.normalize_label`, `categories_from_label` и `template_utils.match_template_multiscale`. |
| `stage_analyze.py` | Собирает вопрос+тайлы, задаёт Vision-аналитику, фильтрует индексы, кликает в Chrome и сохраняет `grid_choice.json`. | Связан с `core.vision_json`, `chrome_utils.screenshot_full`, OpenCV. |
| `template_utils.py` | Обёртки над `cv2.matchTemplate` (обычный и multiscale). | Используется в stage-модулях. |
| `chrome_utils.py` | Управляет окном Chrome и вводом URL, даёт полноэкранные скриншоты. | Зависит от `.env`, `pyautogui`, `pygetwindow`. |
| `png/` | Шаблоны: `checkbox.png`, `question_template.png`, `grid_template.png`, `donttouch.png`, запас `next.png`. | Читаются `stage_*` и `donttouch`. |
| `tmp_clicks/` | Временные тайлы сетки (PNG) для Vision и дальнейшего template matching. | Создаётся/чистится в `core.ensure_tmp_dir`. |
| `prompts.json` | Кастомные prompt override для Vision. | Читается `core.get_prompt`. |
| `png/chekbox.py`, `vision_agent.py` | Экспериментальные утилиты (Vision-координаты, быстрые эксперименты). | Не вызываются из `main.py`, но полезны как reference. |

## Требования
- **ОС**: Windows 10/11 (из-за `pyautogui`, `pygetwindow`, путей и hotkey).
- **Python**: 3.10+ (проверено на 3.11).
- **Chrome**: установленный браузер с доступом к аргументам `--remote-debugging-port`, `--user-data-dir`.
- **OpenAI API**: ключ с доступом к `gpt-4.1-mini`.
- **Библиотеки**: список в `requirements.txt` (`opencv-python`, `numpy`, `pyautogui`, `Pillow`, `openai`, `python-dotenv`, `pygetwindow`).
- **Дисплей**: мониторы без виртуальных раскладок (для корректных координат `pyautogui`); масштабирование Windows 100% предпочтительно для стабильного template matching.

## Установка

1. Клонировать репозиторий и перейти в папку:
   ```powershell
   git clone <url> abxod_Hcaptcha
   cd abxod_Hcaptcha
   ```
2. Создать и активировать виртуальное окружение:
   ```powershell
   python -m venv venv
   .\venv\Scripts\activate
   ```
3. Установить зависимости:
   ```powershell
   pip install -r requirements.txt
   ```
4. Скопировать `.env` (или переименовать пример) и заполнить переменные:
   ```text
   OPENAI_API_KEY=sk-...
   TARGET_URL=https://пример-сайта-с-hcaptcha
   CHROME_PATH="C:\Program Files\Google\Chrome\Application\chrome.exe"
   CHROME_USER_DATA_DIR=C:\tmp\chrome-profile
   CHROME_REMOTE_DEBUG_PORT=9222
   CHROME_PROXY=
   HTTP_PROXY=
   HTTPS_PROXY=
   ```
5. Подготовить PNG-шаблоны (`png/checkbox.png`, `png/question_template.png`, `png/grid_template.png`). При первом запуске `donttouch.ensure()` создаст baseline и заблокирует `png/donttouch.png` от изменений.

## Конфигурация

| Переменная | Что делает | Замечания |
| --- | --- | --- |
| `OPENAI_API_KEY` | Ключ OpenAI для Vision запросов. | Хранить вне Git; лимиты тарифа учитываются. |
| `TARGET_URL` | Страница с hCaptcha. | Можно оставить пустой, если вкладка уже открыта. |
| `CHROME_PATH` | Полный путь до chrome.exe. | Для Canary/Portable указать свой путь. |
| `CHROME_REMOTE_DEBUG_PORT` | Порт DevTools. | По умолчанию 9222; не должен быть занят. |
| `CHROME_USER_DATA_DIR` | Каталог профиля Chrome. | Позволяет хранить cookies/HCaptcha контекст. |
| `CHROME_PROXY` | `host:port` для Chrome. | Применяется в `start_chrome()`. |
| `HTTP_PROXY` / `HTTPS_PROXY` | Прокси для Python/OpenAI. | Проставляются в `os.environ`. |

Параметры vision и фильтрации задаются в `core.py` (порог `MATCH_THRESHOLD_*`, `MAX_ATTEMPTS_VISION`, `TAXONOMY`, радиус дедупликации и т.д.). Их можно менять без правки бизнес-логики.

## Как запускается сценарий

```powershell
.\venv\Scripts\activate
python main.py
```

Последовательность стадий (см. `main.py`):
1. **donttouch.ensure** — проверяет хеш `png/donttouch.png`, восстанавливает из backup при расхождении.
2. **ensure_chrome_and_open_url** — находит активное окно Chrome или запускает новое с указанным профилем, вводит `TARGET_URL`.
3. **Stage 1 (`click_checkbox_by_template`)** — скриншот + `cv2.matchTemplate` с `png/checkbox.png`, клик по центру найденного прямоугольника.
4. **Stage 2 (`capture_question_to_json_retry`)** — поиск панели вопроса по шаблону `png/question_template.png` (повтор до `MAX_WAIT_SEC_STAGE2`), отправка картинок в Vision для заполнения `question.json`.
5. **Stage 3a (`capture_grid_objects_to_json_retry`)** — поиск сетки по `png/grid_template.png`, нарезка 9 тайлов, подпись каждого через Vision → `grid_objects.json`.
6. **Stage 3b (`analyze_json_and_click_by_images`)** — собирает вопрос+тайлы, формирует массив `[question_b64] + tiles_b64`, получает от Vision список индексов + причину, фильтрует через таксономию, обрабатывает спецслучай «birdhouse», кликает по совпадениям и сохраняет `grid_choice.json`.

После завершения в корне будут три JSON-файла, которые можно использовать для отладки или обучения.

## Форматы данных

### `question.json`
- `task_text`, `selection_criteria` — OCR/LLM-описание задания.
- `positive_keywords`, `negative_keywords` — списки маркеров для Vision-подсказок.
- `example_container`, `example_container_for_creature` — текстовые примеры из панели.
- `target_categories`, `exclude_categories` — вывод `core.detect_categories_in_text` и `categories_from_creature_hint`.
- `image_b64`, `template`, `score` — служебная информация.

### `grid_objects.json`
- `objects` — массив из 9 элементов: индекс, путь к тайлу, координаты центра, label/conf от Vision, нормализованный label и категории.
- `grid_shape`, `template`, `score` — геометрия сетки и качество совпадения.

### `grid_choice.json`
- `index_order` — порядок тайлов, передававшийся в Vision.
- `raw_from_model` — индексы из Vision без фильтра.
- `chosen_indexes` — окончательное решение после постобработки.
- `reason` — строка/объяснение от модели (для логов).

## Работа с промптами
`core.get_prompt(key, default)` пытается прочитать текст из `prompts.json`. Если ключа нет, берётся дефолтный prompt из кода. Это позволяет экспериментировать с формулировками без изменения Python-файлов. Храните `prompts.json` в UTF‑8.

## Шаблоны и контроль целостности
- `png/checkbox.png`, `png/question_template.png`, `png/grid_template.png` должны соответствовать текущему UI hCaptcha (размеры, масштаб, тема). При изменении интерфейса обновите шаблоны и перезапустите `donttouch.safe_update`.
- `donttouch.py` хранит baseline-хеш, переводит файл в read-only и восстанавливает из `png/donttouch.backup.png`, если CRC изменился.

## Отладка и журналирование
- Все стадии выводят диагностические сообщения (`print`), включая score template matching и координаты кликов.
- Если Vision возвращает некорректный JSON, сработает fallback `extract_json_object`.
- Тайлы сохраняются в `tmp_clicks/`; можно проверить, что Vision получает корректные изображения.
- Для повторного анализа без повторного сканирования можно править `question.json` / `grid_objects.json` и запускать только `stage_analyze.analyze_json_and_click_by_images()`.

## Безопасность и лимиты
- Не коммитьте реальный `OPENAI_API_KEY`. Используйте переменные окружения или секретные менеджеры.
- Учитывайте стоимость OpenAI Vision на каждый запуск (минимум 11 запросов: 1 на вопрос + 9 для тайлов + 1 на анализ).
- Если вы используете прокси/VPN, настройте как Chrome (`CHROME_PROXY`), так и Python (`HTTP_PROXY`/`HTTPS_PROXY`).

## Дальнейшие шаги
1. Добавить полноценную обработку повторных сеток (кнопка «Дальше») — заготовка `png/next.png` уже в репозитории.
2. Расширить `core.TAXONOMY`, чтобы улучшить фильтрацию по категориям.
3. Вынести Vision-запросы в очередь/кэш для повторного использования ответов.
4. Добавить модуль интеграции с DevTools по WebSocket, чтобы уменьшить зависимость от `pyautogui`.

Документ `context.md` содержит больше технических деталей о связях модулей и алгоритмах.
