"""HL → Binance copier.

Слои:
  copier.hl      — источник данных Hyperliquid (REST polling + WebSocket push)
  copier.core    — биржа-агностик логика (позиции, события, сайзинг, план копирования)
  copier.execution — исполнение на Binance (Фаза 3)
Точки входа — в каталоге ../tools/. Конфиги — ../config/. Состояние/логи — ../runtime/.
"""
__version__ = "0.2.0"
