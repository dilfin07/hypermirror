"""Тексты монитора уходят с parse_mode=HTML — значит не должны ломать разметку.

Сводка ордеров печатала окно наблюдения как «<1 мин». Telegram видит в «<1» открывающий
тег, отвечает 400 «Unsupported start tag "1"» и НЕ доставляет сводку целиком. Метка счёта
задаётся пользователем («Копи & Ко») и ломает разметку тем же образом.

Проверяем результат настоящего форматтера: теги только из белого списка, а голых «<»/«&»
в динамических частях нет.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server._monitor import MonitorMixin  # noqa: E402

_ALLOWED = {"b", "/b", "code", "/code", "i", "/i"}


class _Stub(MonitorMixin):
    """Только то, что нужно форматтеру."""


def _bucket(name, win_sec=30.0):
    return {
        "m": {"address": "0xabcdef0123456789", "name": name},
        "side": "SHORT", "action": "REDUCE", "coin": "ETH", "count": 6,
        "otype": "Limit", "pnl_sum": -186.0,
        "pxsz_sum": 1747.5 * 54.647, "sz_sum": 54.647, "val_sum": 95500.0,
        "before": 484.201, "after": 429.554, "pos_value": 750000.0,
        "first_recv": 0.0, "last_recv": win_sec,
    }


def _tags(text):
    return set(re.findall(r"<\s*(/?[^>\s]*)", text))


def test_окно_меньше_минуты_не_ломает_разметку():
    txt = _Stub()._fmt_monitor_alert_agg(_bucket("сейчас копирую", win_sec=30.0))
    assert "<1" not in txt, 'Telegram примет "<1" за открывающий тег и вернёт 400'
    assert "less than 1 min" in txt
    assert _tags(txt) <= _ALLOWED, f"посторонние теги: {_tags(txt) - _ALLOWED}"


def test_длинное_окно_печатается_как_раньше():
    txt = _Stub()._fmt_monitor_alert_agg(_bucket("копи", win_sec=180.0))
    assert "~3 min" in txt


def test_метка_счёта_экранируется():
    """Пользователь вправе назвать счёт «Копи & Ко» или «<script>»."""
    txt = _Stub()._fmt_monitor_alert_agg(_bucket("Копи & Ко"))
    assert "&amp;" in txt
    assert "Копи & Ко" not in txt
    assert _tags(txt) <= _ALLOWED


def test_метка_с_угловой_скобкой_не_создаёт_тега():
    txt = _Stub()._fmt_monitor_alert_agg(_bucket("<script>"))
    assert "<script" not in txt
    assert "&lt;script&gt;" in txt
    assert _tags(txt) <= _ALLOWED
