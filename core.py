from __future__ import annotations

import base64
import json
import difflib
import re
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Set

from PIL import Image
from openai import OpenAI

from config import OPENAI_API_KEY

# === базовые пути и константы ===
BASE_DIR = Path(__file__).resolve().parent
PNG_DIR = BASE_DIR / "png"
TMP_DIR = BASE_DIR / "tmp_clicks"

PROMPTS_PATH = BASE_DIR / "prompts.json"


def _load_prompts() -> dict:
    try:
        return json.loads(PROMPTS_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print("[core] prompts.json not found, using default prompts")
        return {}
    except Exception as e:
        print(f"[core] cannot read prompts.json: {e}")
        return {}


PROMPTS = _load_prompts()


def get_prompt(key: str, default: str) -> str:
    """
    Берём текст промпта из prompts.json, либо дефолт из кода.
    """
    return PROMPTS.get(key, default)


# --- thresholds / тайминги ---
MATCH_THRESHOLD_QUESTION = 0.30
MATCH_THRESHOLD_GRID = 0.22
RETRY_INTERVAL_SEC = 1.0
MAX_WAIT_SEC_STAGE2 = 35
MAX_ATTEMPTS_VISION = 5
SLEEP_BETWEEN_VISION = 1.5


# --- selection thresholds ---
MATCH_THRESHOLD_OBJECT = 0.68      # порог совпадения при клике по картинке
CONF_TILE_LABEL_OK     = 0.50
DEDUP_RADIUS_PX        = 16        # радиус дедупликации точек клика
VISUAL_SIM_THRESHOLD   = 0.60     # схожесть тайлов по картинке (0..1)

client = OpenAI(api_key=OPENAI_API_KEY)

# Простая таксономия + синонимы
TAXONOMY: Dict[str, List[str]] = {
    "bird": [
        "птица", "птицы", "воробей", "воробьи", "синица", "дрозд", "скворец",
        "голубь", "чайка", "ласточка", "птенец", "ворона", "сова",
        "robin", "sparrow", "tit", "blackbird", "starling",
        "pigeon", "seagull", "swallow",
    ],
    "mammal": [
        "животное", "животные",
        "собака", "собаки", "щенок", "щенки",
        "кот", "коты", "котёнок", "котята", "кошка", "кошки",
        "медведь", "лиса", "волк", "олень", "кролик", "заяц",
        "мышь", "мышка", "мыши", "крыса",
        "человек", "люди", "ребёнок", "ребенок", "дети", "мальчик", "девочка",
        "dog", "dogs", "cat", "cats",
        "man", "woman", "boy", "girl", "person", "people",
    ],
    "insect": ["жук", "пчела", "оса", "комар", "стрекоза", "бабочка", "муравей"],
    "fish": ["рыба", "рыбы", "карп", "щука", "лосось", "форель"],
    "reptile": ["змея", "ящерица", "черепаха"],
    "vehicle": ["машина", "автомобиль", "грузовик", "велосипед", "мотоцикл"],
    "clothing": [
        "обувь", "ботинки", "сапоги", "куртка", "брюки", "штаны", "шапка",
        "перчатки", "пальто", "платье", "кофта", "свитер", "шорты", "носки",
        "юбка", "кроссовки",
    ],
    "container": [
        "ящик", "коробка", "скворечник", "домик", "будка", "гнездо",
        "нора", "дупло", "берлога", "улей", "улья", "клетка",
        "birdhouse",
    ],
    "computer_accessory": [
        "клавиатура", "мышь", "мышка", "монитор", "наушники", "гарнитура",
        "джойстик", "геймпад", "трекпад", "mouse", "keyboard", "headphones",
    ],
}


def img_to_b64(pil_img: Image.Image) -> str:
    buf = BytesIO()
    pil_img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def save_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[core] JSON saved -> {path}")


def extract_json_object(text: str) -> dict:
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
    raise ValueError("Balanced JSON not found")


def normalize_label(label: str) -> str:
    """
    Нормализуем подпись тайла:
      - lower;
      - берём первое «слово»;
      - оставляем только буквы/цифры.
    """
    s = (label or "").strip().lower()
    if not s:
        return ""
    s = s.split(",")[0]
    s = s.split(";")[0]
    s = s.split("/")[0]
    parts = s.split()
    if parts:
        s = parts[0]
    cleaned = "".join(ch for ch in s if ch.isalnum())
    return cleaned


def labels_similar(a: str, b: str) -> bool:
    """
    Считаем лейблы одинаковыми, если они совпадают / один входит в другой /
    либо похожи по SequenceMatcher.
    """
    if not a or not b:
        return False
    if a == b:
        return True
    if len(a) >= 3 and len(b) >= 3 and (a in b or b in a):
        return True
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    return ratio >= 0.8


def detect_categories_in_text(text: str) -> Set[str]:
    """
    Извлекаем категории из текста задания по словарю TAXONOMY.
    """
    t = (text or "").lower()
    found: Set[str] = set()
    for cat, words in TAXONOMY.items():
        for w in words:
            if re.search(rf"\b{re.escape(w)}\b", t):
                found.add(cat)
                break
    return found


def categories_from_label(label: str) -> Set[str]:
    """
    Классифицируем тайл по его подписи (label) в категории из TAXONOMY.
    """
    s = (label or "").lower()
    out: Set[str] = set()
    for cat, words in TAXONOMY.items():
        for w in words:
            if w in s:
                out.add(cat)
                break
    return out


def categories_from_creature_hint(hint: str) -> Set[str]:
    """
    Классификация по подсказке вида:
    «для птиц», «домик для собаки», «жилище для птицы» и т.п.
    """
    s = (hint or "").lower()
    if not s:
        return set()

    out: Set[str] = set()
    # сначала по TAXONOMY
    for cat, words in TAXONOMY.items():
        for w in words:
            if w in s:
                out.add(cat)
                break

    # плюс грубое отображение отдельных слов -> категорий
    mapping = {
        "bird": "bird",
        "birds": "bird",
        "птица": "bird",
        "птицы": "bird",
        "воробей": "bird",
        "воробьи": "bird",
        "dog": "mammal",
        "dogs": "mammal",
        "собака": "mammal",
        "собаки": "mammal",
        "cat": "mammal",
        "cats": "mammal",
        "кот": "mammal",
        "коты": "mammal",
        "кошка": "mammal",
        "кошки": "mammal",
        "pet": "mammal",
        "pets": "mammal",
    }
    for token in re.split(r"[^a-zа-яё]+", s):
        token = token.strip()
        if not token:
            continue
        mapped = mapping.get(token)
        if mapped:
            out.add(mapped)

    return out


def vision_json(prompt: str, image_b64_list: List[str]) -> dict:
    """
    Унифицированный вызов OpenAI Vision → dict.
    """
    content: List[Dict[str, Any]] = [{"type": "input_text", "text": prompt}]
    for b64 in image_b64_list:
        content.append(
            {
                "type": "input_image",
                "image_url": f"data:image/png;base64,{b64}",
            }
        )

    try:
        resp = client.responses.create(
            model="gpt-4.1-mini",
            input=[{"role": "user", "content": content}],
            response_format={"type": "json_object"},
        )
        data = resp.output_parsed
        if isinstance(data, dict):
            return data
    except TypeError:
        # старый клиент без response_format
        pass
    except Exception as e:
        print(f"[core] vision primary failed: {e}")

    resp = client.responses.create(
        model="gpt-4.1-mini",
        input=[{"role": "user", "content": content}],
    )

    try:
        text = resp.output_text
    except Exception:
        parts: List[str] = []
        for item in getattr(resp, "output", []) or []:
            for c in getattr(item, "content", []) or []:
                t = getattr(c, "text", None) or getattr(c, "value", None)
                if isinstance(t, str):
                    parts.append(t)
        text = "\n".join(parts)

    return extract_json_object(text)


def ensure_tmp_dir() -> None:
    TMP_DIR.mkdir(parents=True, exist_ok=True)


def cleanup_tmp_dir() -> None:
    if TMP_DIR.exists():
        for p in TMP_DIR.glob("*"):
            try:
                p.unlink()
            except Exception:
                pass
        try:
            TMP_DIR.rmdir()
        except Exception:
            pass
