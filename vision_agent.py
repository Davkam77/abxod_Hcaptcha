# vision_agent.py
import base64
import json
from io import BytesIO
from typing import Tuple

from openai import OpenAI
from config import OPENAI_API_KEY

client = OpenAI(api_key=OPENAI_API_KEY)


def image_to_base64(pil_image) -> str:
    buf = BytesIO()
    pil_image.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def find_target_coordinates(pil_image, query: str) -> Tuple[int, int]:
    """
    pil_image: Pillow Image (скрин)
    query: текст, что искать, напр. "Найди иконку клавиатуры и верни центр bounding box"
    Возвращает (x, y) — координаты центра.
    """
    img_b64 = image_to_base64(pil_image)

    prompt = (
        "Ты помощник по визуальной автоматизации.\n"
        "На изображении — скриншот экрана.\n"
        "Найди объект по описанию пользователя.\n"
        "Верни строго JSON в виде: {\"x\": <int>, \"y\": <int>} — координаты центра этого объекта в пикселях.\n"
        "Если объект не найден, верни {\"x\": -1, \"y\": -1}.\n"
        f"Описание объекта: {query}"
    )

    resp = client.responses.create(
        model="gpt-4.1-mini",
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {
                        "type": "input_image",
                        "image_url": f"data:image/png;base64,{img_b64}",
                    },
                ],
            }
        ],
        response_format={"type": "json_object"},
    )

    raw = resp.output[0].content[0].text
    data = json.loads(raw)

    x = int(data.get("x", -1))
    y = int(data.get("y", -1))
    return x, y
