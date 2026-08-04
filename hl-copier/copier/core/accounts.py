"""Чистая логика мультисчётной модели (defaults ⊕ overrides). Без сети/IO."""


def resolve_targets(is_main, top_level_targets, override_targets):
    """Эффективная цель копирования активного счёта.

    Цель копирования НЕ наследуется между счетами:
      • main      → берёт top-level targets (его собственная цель);
      • не-main    → ТОЛЬКО свой override (нет override → пустая цель).

    Иначе не-main счёт молча копировал бы цель main — опасно: «думаешь
    копируешь одного, а стоит другой». У каждого счёта своя независимая цель.
    """
    if is_main:
        return list(top_level_targets or [])
    return list(override_targets or [])
