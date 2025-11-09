# context.md

Developer handbook for `abxod_Hcaptcha`: how the modules interact, what JSON contracts exist, and how the vision/verification pipeline behaves.

## 1. High-level pipeline

```
main.py
├─ donttouch.ensure()               # template integrity
├─ chrome_utils.ensure_chrome...    # window activation + URL
├─ stage_checkbox_question.click... # Stage 0: checkbox
├─ stage_checkbox_question.capture  # Stage 1: question → question.json
├─ stage_grid.capture...            # Stage 2: grid → grid_objects.json
└─ stage_analyze.analyze...         # Stage 3: analysis → grid_choice/grid_verify + clicks
```

Each stage uses utilities from `core.py` (constants, prompts, taxonomy) and `chrome_utils.py` (screenshots). JSON artifacts let you re-run later stages without repeating screen capture.

## 2. Modules & responsibilities

| Module | Role | Dependencies | Output |
| --- | --- | --- | --- |
| `core.py` | Paths, thresholds, OpenAI client, taxonomy, prompt overrides, helpers (`vision_json`, `get_prompt`, `save_json`). | `config`, `PIL`, `openai`. | JSON writes (`question.json`, `grid_objects.json`, `grid_choice.json`, `grid_verify.json`). |
| `chrome_utils.py` | Starts/activates Chrome, sends URL, full-screen screenshots. | `.env`, `pyautogui`, `pygetwindow`. | PIL images. |
| `stage_checkbox_question.py` | Stage 0/1: template-match checkbox, capture question panel, call Vision (`question_extraction`), enrich categories, write `question.json`. | `template_utils.match_best_template`, `core.get_prompt`. | `question.json`. |
| `stage_grid.py` | Stage 2: locate `grid_template.png`, slice 3×3, save `tmp_clicks/tile_i.png`, label each tile via Vision (`grid_tile_label`). | `template_utils.match_template_multiscale`, `core.img_to_b64`, taxonomy helpers. | `grid_objects.json`, `tmp_clicks/*.png`. |
| `stage_analyze.py` | Stage 3: ask Vision for indexes, click tiles, run super verification/auto-correction, store logs. | `core.get_prompt`, `chrome_utils.screenshot_full`, OpenCV, `pyautogui`. | `grid_choice.json`, `grid_verify.json`. |
| `stage_next_done.py` | Template clicker for `next.png` / `done.png`. | `chrome_utils.screenshot_full`, `core.MATCH_THRESHOLD_OBJECT`. | Used in `main.py`. |
| `template_utils.py` | Thin wrappers for OpenCV template matching. | `cv2`, `numpy`. | Shared by stage modules. |
| `donttouch.py` | Hash-based guard for PNG templates. | `hashlib`, `shutil`. | `png/donttouch.*`. |
| `prompts.json` | Optional overrides for stage prompts (selection, verification, etc.). | `core.get_prompt`. | — |

## 3. JSON contracts

### question.json
```json
{
  "task_text": "Select all computer accessories.",
  "selection_criteria": "...",
  "target_categories": ["computer_accessory"],
  "exclude_categories": [],
  "example_container": "...",
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
      "label": "mouse",
      "label_conf": 0.92,
      "norm_label": "mouse",
      "categories": ["computer_accessory"]
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
  "raw_from_model": [0, 2, 5],
  "chosen_indexes": [0, 2, 5],
  "reason": "Vision explanation"
}
```

### grid_verify.json
```json
{
  "chosen_indexes": [0,2,5],
  "attempts": [
    {
      "attempt": 0,
      "correct_indexes": [0,2,5],
      "selected_indexes": [0,2],
      "missed": [5],
      "extra": [],
      "ok": false,
      "verify_reason": "tile 5 not lit"
    },
    {
      "attempt": 1,
      "correct_indexes": [0,2,5],
      "selected_indexes": [0,2,5],
      "missed": [],
      "extra": [],
      "ok": true,
      "verify_reason": "all correct after fix"
    }
  ],
  "actions": [
    {"attempt": 0, "action": "add", "index": 5, "result": "clicked", "score": 0.83}
  ],
  "ok": true
}
```

## 4. Stage-by-stage logic

### Stage 0/1 — checkbox + question
1. `click_checkbox_by_template()` uses `template_utils.match_best_template` to find `checkbox.png`.
2. `capture_question_to_json_retry()` loops until `question_template.png` matches above `MATCH_THRESHOLD_QUESTION`, encodes the panel via `core.img_to_b64`, and calls Vision. Categories get enriched via `core.detect_categories_in_text` and `categories_from_creature_hint`.

### Stage 2 — grid slicing
1. `stage_grid.capture_grid_objects_to_json_retry()` searches for `grid_template.png` with multiscale matching.
2. Slices image into 9 (last row/col absorb rounding), saves each tile to `tmp_clicks/tile_i.png`.
3. Runs Vision (`grid_tile_label`) → expects `{ "label": "...", "conf": 0..1 }`.
4. Stores label, confidence, normalized label, categories for each tile in `grid_objects.json`.

### Stage 3 — analysis & auto-correction
1. **Selection prompt** (`grid_selection`): `[question] + [tiles]` → `indexes` + `reason`. `_sanitize_indexes` converts 0..8 style indexes into real ones.
2. **Post filters** (`_apply_post_filters`):
   - respect `target_categories` / `exclude_categories`;
   - “select all …” heuristics (same `norm_label` or category → include all such tiles);
   - `birdhouse / nest / duplo / домик для птиц` → only birds (`categories` or label substring).
3. **Initial clicks:** `_locate_tiles()` matches each `tmp_clicks/tile_i.png` on the live screenshot; `_click_tiles()` performs clicks with `MATCH_THRESHOLD_OBJECT` guard.
4. **Super verification loop** (`_verification_loop`):
   - Constants: `VERIFY_PAUSE`, `MAX_FIX_ROUNDS = 2`.
   - For each attempt:
     1. wait, capture fullscreen;
     2. `_verify_with_vision()` builds a rich prompt including task text, selection rule, index map, `expected_from_stage1`, and semantic hints (“keyboard/computer accessories → choose mouse, monitor”, “birdhouse/nest → only birds”);
     3. Vision returns `{correct_indexes, selected_indexes, ok, reason}`;
     4. `_sanitize_indexes` cleans up indices; fallback to chosen list if `correct_indexes` is empty;
     5. compute `missed`, `extra`, log attempt;
     6. exit if `ok` and no differences;
     7. otherwise click `missed` (`action="add"`) and `extra` (`action="remove"`) with logging;
     8. if template detections collapse (grid changed), break with `note = "grid_changed"`.
5. **Summary:** `grid_verify.json` stores every attempt/action, final bool goes back to `main.py`, which then triggers NEXT or DONE.

## 5. Prompts & overrides
- `prompts.json` keys:
  - `question_extraction`
  - `grid_selection`
  - `grid_tile_label`
  - `verify_selection`
- If a key is missing, `core.get_prompt` falls back to the built-in default (the English description in this file).

## 6. Taxonomy & semantics
- `core.TAXONOMY` maps keywords to categories. Used in:
  - stage 2 labels → informs Stage 3 filters;
  - `birdhouse` case: keywords `birdhouse`, `скворечн`, `домик для птиц`, `ду́пло`.
- `categories_from_creature_hint`, `detect_categories_in_text`, `normalize_label` support the heuristics for “select all”, keyboard vs clothing, etc.

## 7. Timing & thresholds
- `MATCH_THRESHOLD_QUESTION`, `MATCH_THRESHOLD_GRID`, `MATCH_THRESHOLD_OBJECT` — OpenCV score limits.
- `RETRY_INTERVAL_SEC`, `MAX_WAIT_SEC_STAGE2` — timeouts for question/grid capture.
- `CLICK_PAUSE` (0.18 s) — between clicks.
- `VERIFY_PAUSE` (0.4 s) — before each verification screenshot.
- `MAX_FIX_ROUNDS = 2` — maximum auto-fix loops (initial pass + two corrections).

## 8. NEXT / DONE policy
- `main.py` keeps the global round count (`ROUNDS = 3`):
  - rounds 1–2: after `stage_analyze` (regardless of its bool), call `click_next_button()` (template `next.png`).
  - round 3: call `click_done_button()` (`done.png`).
- These buttons are template-matched; low score just logs a warning so the script doesn’t hang.

## 9. Debug hints
- Inspect `tmp_clicks/grid_before.png`, `grid_after_*.png`, and `tile_i.png` to see exactly what Vision saw.
- `grid_choice.json` records the raw indexes from Vision and the post-filtered list.
- `grid_verify.json` shows every verification attempt and auto-fix action.
- To replay a grid, copy `question.json` and `grid_objects.json` from a previous run and execute only `stage_analyze.analyze_json_and_click_by_images()`.

## 10. Known caveats / TODO
- Vision may output indexes outside 0..8; `_sanitize_indexes` guards this, but better prompts reduce noise.
- If hCaptcha swaps to a new grid mid-verification, `_verification_loop` marks `grid_changed` and exits; consider an automatic restart flow.
- Token usage is high (≥12 requests per grid). Caching or batching repeated tiles would help.
- Integrating Chrome DevTools clicking would eliminate some of the brittleness from `pyautogui`.

Refer to `README.md` for installation, prerequisites, and user-facing instructions.
