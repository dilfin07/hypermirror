// Знак Kielwater: K и V отдельными блоками, между ними воздух — сваренных форм нет.
// V здесь — сокращённая W (Kiel + water): вторая буква не дописывается, а подсказывается.
// Наклон всех косых один (dx/dy = 0,42), срезы только горизонтальные и вертикальные.
// Рисуется одним currentColor — наследует цвет текста и работает в обеих темах без второй версии.

// Широкий знак (82 × 48) — шапка, локап, документация.
export function BrandMark({ size = 22, title, ...rest }) {
  const a11y = title ? { role: 'img', 'aria-label': title } : { 'aria-hidden': 'true' }
  return (
    <svg viewBox="0 0 82 48" height={size} width={(size * 82) / 48}
         fill="currentColor" focusable="false" {...a11y} {...rest}>
      <rect x="4" y="8" width="10" height="32" />
      <path d="M17.5 22 L23.4 8 L33.4 8 L27.5 22 Z" />
      <path d="M17.5 26 L23.4 40 L33.4 40 L27.5 26 Z" />
      <path d="M40.4 8 L53.8 40 L63.8 40 L77.2 8 L67.2 8 L58.8 28 L50.4 8 Z" />
    </svg>
  )
}

// Квадратная версия (64 × 64) — фавикон, аватарка, любое место со стороной 1:1.
// W срезана до одной длинной косой: в мелком размере широкий знак вырождается в полоску.
export function BrandMarkSquare({ size = 32, title, ...rest }) {
  const a11y = title ? { role: 'img', 'aria-label': title } : { 'aria-hidden': 'true' }
  return (
    <svg viewBox="0 0 64 64" height={size} width={size}
         fill="currentColor" focusable="false" {...a11y} {...rest}>
      <rect x="6" y="12" width="12" height="40" />
      <path d="M22 28 L28.7 12 L40.7 12 L34 28 Z" />
      <path d="M26 52 L42.8 12 L54.8 12 L38 52 Z" />
    </svg>
  )
}
