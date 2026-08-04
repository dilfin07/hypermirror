"""Юнит-тесты мультисчётной логики: цель копирования НЕ наследуется между счетами."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from copier.core.accounts import resolve_targets

MAIN_T = [{"address": "0xmain", "weight": 1.0, "label": "pension"}]
ACCT_T = [{"address": "0xacct", "weight": 1.0, "label": "в наблюдение"}]


def test_main_uses_top_level():
    assert resolve_targets(True, MAIN_T, None) == MAIN_T
    assert resolve_targets(True, MAIN_T, ACCT_T) == MAIN_T          # override не при чём для main


def test_non_main_without_override_is_empty_not_inherited():
    """Ключевой регресс: не-main без своей цели → ПУСТО, а не цель main."""
    assert resolve_targets(False, MAIN_T, None) == []
    assert resolve_targets(False, MAIN_T, []) == []


def test_non_main_uses_own_override():
    assert resolve_targets(False, MAIN_T, ACCT_T) == ACCT_T         # своя цель, не main


def test_returns_copy_not_reference():
    """Возвращаем новый список (правки эффективного не портят сырой конфиг)."""
    out = resolve_targets(True, MAIN_T, None)
    assert out == MAIN_T and out is not MAIN_T


def test_none_inputs():
    assert resolve_targets(True, None, None) == []
    assert resolve_targets(False, None, None) == []


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn(); print(f"  ok  {fn.__name__}")
        except AssertionError as e:
            failed += 1; print(f"FAIL  {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
