from __future__ import annotations

import time

from donttouch import ensure as donttouch_ensure
from chrome_utils import ensure_chrome_and_open_url
from stage_checkbox_question import (
    click_checkbox_by_template,
    capture_question_to_json_retry,
)
from stage_grid import capture_grid_objects_to_json_retry
from stage_analyze import analyze_json_and_click_by_images
from stage_next_done import click_next_button, click_done_button


ROUNDS = 3


def main() -> None:
    try:
        donttouch_ensure()
    except Exception as e:
        print(f"[main] donttouch: {e}")

    ensure_chrome_and_open_url()
    print("[main] Ждём загрузку стартового экрана игры...")
    time.sleep(1.0)

    print("[main] Шаг 1: checkbox by template…")
    click_checkbox_by_template()

    for i in range(ROUNDS):
        print(f"[main] === Раунд {i + 1} / {ROUNDS} ===")

        print("[main] Шаг 2: detect question panel → question.json…")
        capture_question_to_json_retry()

        print("[main] Шаг 3a: detect grid panel → grid_objects.json…")
        capture_grid_objects_to_json_retry()

        print("[main] Шаг 3b: analyze JSON → click…")
        analyze_json_and_click_by_images()

        # переходы между раундами
        if i < ROUNDS - 1:
            print("[main] Шаг 4: жмём NEXT…")
            if not click_next_button():
                print("[main] NEXT не найден или слабый матч, продолжаем как есть.")
            time.sleep(0.5)
        else:
            print("[main] Шаг 4: финальный DONE…")
            if not click_done_button():
                print("[main] DONE не найден или слабый матч.")
            time.sleep(0.5)

    print("[main] Поток main.py завершён.")


if __name__ == "__main__":
    main()
