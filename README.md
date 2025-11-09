# abxod_Hcaptcha

Automation toolkit for solving hCaptcha image challenges on Windows. The script opens or attaches to Chrome, captures the instruction panel, classifies the 3×3 grid via OpenAI Vision, clicks the required tiles, and performs a “super verification” loop that auto-fixes missed or extra clicks before moving on.

## Features
- Full hCaptcha loop: checkbox → question capture → grid slicing → tile selection → verification → NEXT/DONE.
- Instruction parsing and tile labeling powered by GPT‑4.1‑mini through the Responses API (`core.vision_json`).
- Category-aware post-processing: taxonomy-based filtering, “select all …” heuristics, birdhouse/dorm special cases.
- Super verification in three passes:
  1. click tiles predicted by Vision;
  2. Vision re-checks the live screenshot (`correct` vs `selected`);
  3. automatic correction kicks in (adds `missed`, removes `extra`) and re-verifies (up to two rounds).
- Template integrity with `donttouch.py`, prompt overrides via `prompts.json`, detailed logs in `grid_choice.json` / `grid_verify.json`.

## Repository structure

| Path | Description |
| --- | --- |
| `main.py` | Entry point. Runs `donttouch.ensure`, makes sure Chrome is ready, coordinates stage modules, and clicks `next.png` / `done.png` depending on the round. |
| `config.py` / `.env` | OpenAI key, Chrome path, target URL, optional proxies. |
| `core.py` | Global constants, paths, OpenAI client, taxonomy, prompt helpers, JSON helpers. |
| `stage_checkbox_question.py` | Stage 0/1: template-match `png/checkbox.png`, then crop `png/question_template.png`, send to Vision, save `question.json`. |
| `stage_grid.py` | Stage 2: locate `png/grid_template.png`, slice into 9 tiles, store `tmp_clicks/tile_i.png`, label each tile via Vision → `grid_objects.json`. |
| `stage_analyze.py` | Stage 3: combine question + grid, ask Vision for indexes, click tiles, run super verification/auto-fix, write `grid_choice.json` & `grid_verify.json`. |
| `stage_next_done.py` | Generic template-clicker for `next.png` / `done.png`. |
| `template_utils.py` | Wrappers around OpenCV template matching. |
| `chrome_utils.py` | Window activation, URL navigation, fullscreen screenshots. |
| `png/` | Templates: checkbox, question panel, grid panel, next/done buttons, donttouch assets. |
| `tmp_clicks/` | Cached tile PNGs and before/after screenshots. |
| `prompts.json` | Optional overrides for Vision prompts (`grid_selection`, `verify_selection`, etc.). |

## Pipeline overview
1. **Checkbox.** `stage_checkbox_question.click_checkbox_by_template()` grabs a fullscreen screenshot and matches `checkbox.png`. Once clicked, it proceeds to stage 1.
2. **Question capture.** `capture_question_to_json_retry()` finds `question_template.png`, crops it, sends to Vision (`question_extraction`), enriches categories with taxonomy helpers, and saves `question.json`.
3. **Grid slicing.** `stage_grid.capture_grid_objects_to_json_retry()` locates `grid_template.png`, slices the 3×3 panel, saves each tile to `tmp_clicks/tile_i.png`, asks Vision (`grid_tile_label`) for labels/confidences/categories, and writes `grid_objects.json`.
4. **Analysis + clicks.**
   - `stage_analyze.analyze_json_and_click_by_images()` sends `[question_b64] + [tiles]` to Vision (`grid_selection`) and normalizes indexes.
   - `_apply_post_filters` enforces constraints:
     - `target_categories` / `exclude_categories` from `question.json`;
     - “select all …” tasks → add every tile with the same normalized label/category;
     - birdhouse/dugout hints → only bird-related tiles.
   - `_locate_tiles` + `_click_tiles` match each `tmp_clicks/tile_i.png` back onto the live screen and issue clicks (skip if score < `MATCH_THRESHOLD_OBJECT`).
5. **Super verification loop.**
   - Constants: `VERIFY_PAUSE` (default 0.4 s), `MAX_FIX_ROUNDS = 2`.
   - On each attempt:
     1. wait `VERIFY_PAUSE`, capture fullscreen via `screenshot_full()`;
     2. `_verify_with_vision` builds a rich prompt with:
        - task text and selection rule;
        - explicit index map (0–2 top row, etc.);
        - `expected_from_stage1` (what Vision selected initially);
        - semantic hints (“keyboard/computer accessories → mouse, monitor”, “birdhouse/ду́пло → only birds”);
        - requests JSON `{correct_indexes, selected_indexes, ok, reason}`.
     3. indices go through `_sanitize_indexes`; if `correct_indexes` is empty, we fall back to the initial selection.
     4. compute `missed = correct - selected` and `extra = selected - correct`.
     5. append attempt data to `attempts` log.
     6. exit early if `ok == True` and no differences.
     7. if attempts remain and the grid hasn’t changed (`len(detections)` still healthy):
        - `_click_tiles(missed, action="add")` to add missing ticks;
        - `_click_tiles(extra, action="remove")` to unselect extras.
        - Every corrective click is logged in `actions` with attempt, score, result.
     8. if template matches drop drastically, mark `note: "grid_changed"` and stop.
6. **Artifacts.**
   - `grid_choice.json`: task text, `index_order`, raw Vision indexes, filtered selection, reason string.
   - `grid_verify.json`: `[attempts]` (each with `correct_indexes`, `selected_indexes`, `missed`, `extra`, `ok`, `verify_reason`), `[actions]`, final `ok`.
7. **Next/DONE buttons.** `main.py` runs three rounds. After rounds 1–2 it calls `stage_next_done.click_next_button()` (template `next.png`); after round 3 it calls `click_done_button()`. Failures just log warnings and continue.

## Installation
```powershell
git clone <repo> abxod_Hcaptcha
cd abxod_Hcaptcha
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
```

Create `.env`:
```
OPENAI_API_KEY=sk-...
#TARGET_URL=https://hcaptcha.com/
CHROME_PATH="C:\Program Files\Google\Chrome\Application\chrome.exe"
CHROME_REMOTE_DEBUG_PORT=9222
CHROME_USER_DATA_DIR=C:\chrome-profile
CHROME_PROXY=
HTTP_PROXY=
HTTPS_PROXY=
Run:
```powershell
python main.py
# or
python -m main
```

## Customization tips
- **Prompts:** put overrides in `prompts.json` (keys: `grid_selection`, `verify_selection`, `question_extraction`, `grid_tile_label`).
- **Taxonomy:** extend `core.TAXONOMY` to improve automatic filters (e.g., add more vehicle synonyms).
- **Templates:** replace PNGs in `png/` and run `python donttouch.py` to refresh hashes/backups.
- **Debugging:** inspect `tmp_clicks/grid_before.png`, `grid_after_*.png`, `tile_i.png`, and `grid_verify.json` for Vision traces.

## Safety & limits
- Keep your `OPENAI_API_KEY` outside version control.
- `pyautogui` assumes Windows scaling = 100%.
- Vision usage is costly: each grid run hits the API at least 12 times (panel + 9 tiles + selection + 1–2 verifications).
- If the grid changes mid-verification, the loop aborts with `grid_changed` and the next round proceeds.

## Roadmap
1. Handle “extra rounds” when hCaptcha spawns another grid after DONE.
2. Add DevTools automation to reduce dependence on `pyautogui`.
3. Cache Vision results by image hash to save tokens.
4. Support headless Chrome capture or direct WebSocket clicking.

See `context.md` for deeper architectural details.
