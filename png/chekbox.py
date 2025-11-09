# png/chekbox.py
from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
from typing import List, Tuple, Dict, Any

from PIL import Image
from openai import OpenAI

from config import OPENAI_API_KEY
from pyauto_ui import move_and_click

client = OpenAI(api_key=OPENAI_API_KEY)

PNG_DIR = Path(__file__).resolve().parent


def _load_image_b64(filename: str) -> str:
    """
    Загружаем PNG из папки png/ и конвертим в base64 для OpenAI Vision.
    """
    path = PNG_DIR / filename
    if not path.is_file():
        raise FileNotFoundError(f"PNG not found: {path}")

    img = Image.open(path).convert("RGB")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _extract_json_object(text: str) -> dict:
    """
    Вытягивает первый валидный JSON-объект {...} из произвольного текста.
    Без regex. Балансируем скобки посимвольно.
    """
    import json

    start = text.find("{")
    if start == -1:
        raise ValueError("JSON start '{' not found in output")

    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start : i + 1]
                return json.loads(candidate)

    raise ValueError("Balanced JSON object not found in output")


def _call_openai_vision(prompt: str, image_b64_list: List[str]) -> Dict[str, Any]:
    """
    Вызов OpenAI Responses API с картинками.
    1) Пробуем response_format=json_object → сразу dict.
    2) Фолбэк: без response_format, берём текст и достаём JSON вручную.
    """
    content: List[Dict[str, Any]] = [{"type": "input_text", "text": prompt}]
    for b64 in image_b64_list:
        content.append({"type": "input_image",
                        "image_url": f"data:image/png;base64,{b64}"})

    # Путь 1: идеальный
    try:
        resp = client.responses.create(
            model="gpt-4.1-mini",
            input=[{"role": "user", "content": content}],
            response_format={"type": "json_object"},
        )
        data = resp.output_parsed
        if isinstance(data, dict):
            print("[chekbox][_call_openai_vision] parsed(JSON):", data)
            return data
    except TypeError as e:
        print("[chekbox][_call_openai_vision] fallback (no response_format):", e)
    except Exception as e:
        print("[chekbox][_call_openai_vision] primary path failed:", e)

    # Путь 2: фолбэк — без response_format
    resp = client.responses.create(
        model="gpt-4.1-mini",
        input=[{"role": "user", "content": content}],
    )

    # Стащим текст (в 2.x чаще всего есть output_text)
    try:
        text = resp.output_text
    except Exception:
        # Универсальная сборка текста
        parts = []
        for item in getattr(resp, "output", []) or []:
            for c in getattr(item, "content", []) or []:
                t = getattr(c, "text", None) or getattr(c, "value", None)
                if isinstance(t, str):
                    parts.append(t)
        text = "\n".join(parts)

    data = _extract_json_object(text)
    print("[chekbox][_call_openai_vision] parsed(fallback):", data)
    return data


# ----------------- Шаг 1: клик по чекбоксу ----------------- #

def find_checkbox_center() -> Tuple[int, int]:
    """
    checkbox.png — скрин с элементом, по которому надо нажать первым.
    OpenAI Vision возвращает центр этого элемента (x, y).
    """
    b64 = _load_image_b64("checkbox.png")

    prompt = (
        "Это скриншот моей игры.\n"
        "Найди основной элемент (кнопку / чекбокс), на который "
        "нужно нажать первым.\n"
        "Верни строго JSON вида: {\"x\": <int>, \"y\": <int>} — "
        "координаты ЦЕНТРА этого элемента в пикселях относительно "
        "исходного изображения.\n"
        "Если не уверен, всё равно выбери наиболее вероятный элемент."
    )

    data = _call_openai_vision(prompt, [b64])

    x = int(data.get("x", -1))
    y = int(data.get("y", -1))
    return x, y


def click_checkbox() -> None:
    """
    Находит координату из checkbox.png и жмёт туда на реальном экране.
    Предполагаем, что checkbox.png — фуллскрин скрин с тем же разрешением.
    """
    x, y = find_checkbox_center()
    if x < 0 or y < 0:
        print("[chekbox] Checkbox not found, skip click.")
        return

    print(f"[chekbox] Click checkbox at ({x}, {y})")
    move_and_click(x, y, delay=0.5)


# ----------------- Шаг 2: текст задания + сетка объектов ----------------- #

def find_answer_clicks() -> List[Tuple[int, int]]:
    """
    question.png — картинка с текстом задания (например: 'Найдите то, что связано с человеком').
    grid.png — картинка с объектами (дерево, обувь, сумка, брюки, ...).

    Логика:
    1) Модель читает текст задания с question.png.
    2) Смотрит на grid.png и определяет, какие объекты подходят по смыслу.
       (например, одежда и аксессуары связаны с человеком, дерево — нет).
    3) Возвращает JSON: { "clicks": [ {"x": int, "y": int}, ... ] }
       — центры нужных объектов на grid.png.
    """
    q_b64 = _load_image_b64("question.png")
    g_b64 = _load_image_b64("grid.png")

    prompt = (
        "У тебя две картинки.\n"
        "Первая картинка — текст задания в игре (инструкция для игрока).\n"
        "Вторая картинка — сетка с несколькими объектами.\n\n"
        "Сначала прочитай текст задания на ПЕРВОЙ картинке и пойми, что нужно найти.\n"
        "Например: 'найдите то, что связано с человеком' и т.п.\n\n"
        "Потом посмотри на ВТОРУЮ картинку (сетка с объектами) и определи, "
        "какие объекты подходят под это задание по смыслу.\n"
        "Например: дерево НЕ связано с человеком напрямую, а обувь, сумка, брюки — связаны.\n\n"
        "Верни строго JSON вида:\n"
        "{\n"
        "  \"clicks\": [\n"
        "    {\"x\": <int>, \"y\": <int>},\n"
        "    {\"x\": <int>, \"y\": <int>},\n"
        "    ...\n"
        "  ]\n"
        "}\n"
        "где (x, y) — координаты ЦЕНТРА каждого подходящего объекта на ВТОРОЙ картинке "
        "(grid.png), в пикселях относительно этой картинки.\n"
        "Если подходит несколько объектов (например, обувь, сумка, брюки) — верни все.\n"
        "Если ничего не подходит, верни пустой массив clicks: []."
    )

    data = _call_openai_vision(prompt, [q_b64, g_b64])

    clicks: List[Tuple[int, int]] = []
    for item in data.get("clicks", []):
        try:
            x = int(item.get("x"))
            y = int(item.get("y"))
        except (TypeError, ValueError):
            continue
        clicks.append((x, y))

    return clicks


def click_answers() -> None:
    """
    Берём question.png + grid.png, получаем список координат от модели
    и нажимаем по ним через pyauto_ui.
    """
    coords = find_answer_clicks()
    if not coords:
        print("[chekbox] No answer coordinates returned.")
        return

    for (x, y) in coords:
        print(f"[chekbox] Click answer at ({x}, {y})")
        move_and_click(x, y, delay=0.4)


# ----------------- Оркестратор для этого шага ----------------- #

def run_flow() -> None:
    """
    Full flow для твоей мини-игры:
    1) Жмём на первый элемент (checkbox) из checkbox.png.
    2) Анализируем question.png + grid.png и кликаем по всем подходящим объектам.
    """
    print("[chekbox] Step 1: click checkbox")
    click_checkbox()

    print("[chekbox] Step 2: analyze question + grid and click answers")
    click_answers()


if __name__ == "__main__":
    run_flow()
