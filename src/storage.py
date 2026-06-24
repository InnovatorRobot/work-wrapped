"""JSON file storage for non-relational app data (goals, settings, snapshots, etc.)."""

import json
import os

from config import DATA_DIR as _DATA_DIR


def _ensure_data_dir():
    os.makedirs(_DATA_DIR, exist_ok=True)


def _load_json(filename, default=None):
    path = os.path.join(_DATA_DIR, filename)
    if default is None:
        default = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _save_json(filename, data):
    _ensure_data_dir()
    path = os.path.join(_DATA_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
