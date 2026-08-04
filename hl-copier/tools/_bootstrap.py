"""Добавляет корень проекта в sys.path, чтобы `import copier...` работал
при запуске `python3 tools/<x>.py` из любого места."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
