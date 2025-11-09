# donttouch.py
from __future__ import annotations

import hashlib
import os
import shutil
import stat
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent
PNG_DIR = BASE_DIR / "png"
FILE_PATH = PNG_DIR / "donttouch.png"
HASH_PATH = PNG_DIR / "donttouch.sha256"
BACKUP_PATH = PNG_DIR / "donttouch.backup.png"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _chmod_readonly(path: Path) -> None:
    # Сделать файл только для чтения на всех платформах
    try:
        mode = path.stat().st_mode
        path.chmod(
            (mode & ~stat.S_IWUSR & ~stat.S_IWGRP & ~stat.S_IWOTH)
            | stat.S_IRUSR
            | stat.S_IRGRP
            | stat.S_IROTH
        )
        # Для Windows добавим атрибут R (не критично, но полезно)
        if os.name == "nt":
            os.system(f'attrib +R "{path}" >nul 2>&1')
    except Exception as e:
        print(f"[donttouch] WARNING: cannot set read-only for {path}: {e}")


def _chmod_writable(path: Path) -> None:
    try:
        mode = path.stat().st_mode
        path.chmod(mode | stat.S_IWUSR)
        if os.name == "nt":
            os.system(f'attrib -R "{path}" >nul 2>&1')
    except Exception as e:
        print(f"[donttouch] WARNING: cannot make writable {path}: {e}")


def init_baseline(force: bool = False) -> None:
    """
    Создаёт baseline:
      - проверяет, что png/donttouch.png существует
      - пишет sha256 в png/donttouch.sha256
      - создаёт бэкап png/donttouch.backup.png (если нет или force=True)
      - ставит read-only
    """
    PNG_DIR.mkdir(parents=True, exist_ok=True)
    if not FILE_PATH.is_file():
        raise FileNotFoundError(f"[donttouch] not found: {FILE_PATH}")

    digest = _sha256(FILE_PATH)
    HASH_PATH.write_text(digest, encoding="utf-8")

    if force or not BACKUP_PATH.exists():
        _chmod_writable(FILE_PATH)
        shutil.copy2(FILE_PATH, BACKUP_PATH)

    _chmod_readonly(FILE_PATH)
    print("[donttouch] baseline created:", digest)


def verify_or_restore(restore: bool = True) -> None:
    """
    Проверяет целостность. Если hash не совпадает:
      - при restore=True: откатывает из backup и повторно ставит read-only;
      - иначе бросает исключение.
    """
    if not FILE_PATH.exists() or not HASH_PATH.exists():
        raise RuntimeError("[donttouch] baseline not initialized. Run init_baseline().")

    want = HASH_PATH.read_text(encoding="utf-8").strip()
    have = _sha256(FILE_PATH)

    if have == want:
        # убедимся, что файл остаётся read-only
        _chmod_readonly(FILE_PATH)
        print("[donttouch] integrity OK")
        return

    msg = "[donttouch] integrity FAIL — file modified"
    if restore:
        print(msg + " — restoring from backup…")
        if not BACKUP_PATH.exists():
            raise RuntimeError("[donttouch] no backup to restore")
        _chmod_writable(FILE_PATH)
        shutil.copy2(BACKUP_PATH, FILE_PATH)
        _chmod_readonly(FILE_PATH)
        # перехэшируем на всякий случай и сверим
        have2 = _sha256(FILE_PATH)
        if have2 != want:
            raise RuntimeError("[donttouch] restore failed: hash mismatch after restore")
        print("[donttouch] restored successfully")
    else:
        raise RuntimeError(msg)


def safe_update(new_image_path: Path, make_backup: bool = True) -> None:
    """
    Безопасно обновляет donttouch.png:
      - снимает read-only
      - (опц.) делает новый backup
      - копирует новый файл
      - пересчитывает baseline hash
      - снова ставит read-only
    """
    new_image_path = Path(new_image_path)
    if not new_image_path.is_file():
        raise FileNotFoundError(f"[donttouch] new image not found: {new_image_path}")

    if not FILE_PATH.exists():
        PNG_DIR.mkdir(parents=True, exist_ok=True)

    _chmod_writable(FILE_PATH) if FILE_PATH.exists() else None

    if make_backup and FILE_PATH.exists():
        shutil.copy2(FILE_PATH, BACKUP_PATH)

    shutil.copy2(new_image_path, FILE_PATH)

    digest = _sha256(FILE_PATH)
    HASH_PATH.write_text(digest, encoding="utf-8")
    _chmod_readonly(FILE_PATH)
    print("[donttouch] updated. new sha256:", digest)


def ensure() -> None:
    """
    Быстрый «ежесуточный» хук:
      - если baseline не инициализирован — инициируем
      - иначе проверяем и при необходимости восстанавливаем
    """
    if not FILE_PATH.exists() or not HASH_PATH.exists():
        init_baseline(force=False)
    else:
        verify_or_restore(restore=True)
