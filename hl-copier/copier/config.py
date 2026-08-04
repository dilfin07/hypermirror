"""Загрузка конфига и пути проекта."""
import json
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# env-override для песочницы/тестов (по умолчанию — боевые пути проекта)
CONFIG_DIR = os.environ.get("HLC_CONFIG_DIR") or os.path.join(PROJECT_ROOT, "config")
RUNTIME_DIR = os.environ.get("HLC_RUNTIME_DIR") or os.path.join(PROJECT_ROOT, "runtime")


def load_config(path=None):
    """path: None -> config/config.json (или config.example.json);
    иначе абсолютный путь или имя файла внутри config/."""
    if path is None:
        path = os.path.join(CONFIG_DIR, "config.json")
        if not os.path.exists(path):
            path = os.path.join(CONFIG_DIR, "config.example.json")
    elif not os.path.isabs(path):
        cand = os.path.join(CONFIG_DIR, path)
        path = cand if os.path.exists(cand) else path
    with open(path) as fh:
        return json.load(fh)


def runtime_path(name):
    os.makedirs(RUNTIME_DIR, exist_ok=True)
    return os.path.join(RUNTIME_DIR, name)


def atomic_write(path, text):
    """Атомарная запись текста: tmp в той же папке → fsync → os.replace.
    Не бьём целевой файл при сбое/сбросе питания (важно на Pi)."""
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def atomic_write_json(path, obj, **kw):
    """Атомарно сериализовать JSON (kw → json.dumps: indent/ensure_ascii/…)."""
    atomic_write(path, json.dumps(obj, **kw))
