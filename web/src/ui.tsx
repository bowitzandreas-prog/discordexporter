import type { ButtonHTMLAttributes, ReactNode } from 'react';

// Kleine, einheitliche Bausteine. Icons als Inline-SVG (1.6px Strich), keine Icon-Bibliothek.

const PATHS: Record<string, string> = {
  bot: 'M12 8V4H8 M4 12a8 8 0 0 1 8-4h0a8 8 0 0 1 8 4v4a4 4 0 0 1-4 4H8a4 4 0 0 1-4-4z M9 13v1 M15 13v1',
  user: 'M20 21a8 8 0 0 0-16 0 M12 13a5 5 0 1 0 0-10 5 5 0 0 0 0 10z',
  archive: 'M3 4h18v4H3z M5 8v12h14V8 M10 12h4',
  folder: 'M3 6a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z',
  shield: 'M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z M8.5 12l2.5 2.5 4.5-5',
  alert: 'M12 4l9 16H3z M12 10v4 M12 17h.01',
  x: 'M6 6l12 12 M18 6L6 18',
  check: 'M5 12.5l4.5 4.5L19 7.5',
  chevron: 'M9 6l6 6-6 6',
  search: 'M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14z M20 20l-4-4',
  sparkles: 'M12 3l1.8 4.7L18.5 9.5l-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8z M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z',
  power: 'M12 3v9 M6.3 7.3a8 8 0 1 0 11.4 0',
  file: 'M6 3h8l4 4v14H6z M14 3v4h4',
  external: 'M14 4h6v6 M20 4l-9 9 M18 14v6H4V6h6',
  hash: 'M5 9h14 M5 15h14 M10 4L8 20 M16 4l-2 16',
  voice: 'M4 10v4 M8 7v10 M12 4v16 M16 8v8 M20 11v2',
  forum: 'M4 5h16v10H9l-5 4z',
  dm: 'M4 5h16v11H8l-4 4z M8 10h8',
  eye: 'M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z',
  eyeOff: 'M3 3l18 18 M10.6 5.1A10.6 10.6 0 0 1 12 5c6.4 0 10 7 10 7a17 17 0 0 1-3 3.8 M6.6 6.6A17 17 0 0 0 2 12s3.6 7 10 7a9.7 9.7 0 0 0 4.4-1',
  help: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z M9.5 9a2.5 2.5 0 0 1 4.9.7c0 1.7-2.4 2.2-2.4 3.8 M12 17h.01',
  logout: 'M15 4h4v16h-4 M10 8l-4 4 4 4 M6 12h10',
  download: 'M12 4v11 M7 10l5 5 5-5 M5 20h14',
  terminal: 'M4 5h16v14H4z M7 9l3 3-3 3 M12 15h5',
  plug: 'M9 3v5 M15 3v5 M6 8h12v3a6 6 0 0 1-12 0z M12 17v4'
};

export type IconName = keyof typeof PATHS;

export function Icon({ name, className = 'size-4', strokeWidth = 1.6 }: { name: IconName; className?: string; strokeWidth?: number }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round"
      strokeLinejoin="round" className={className} aria-hidden="true">
      <path d={PATHS[name]} />
    </svg>
  );
}

export function Spinner({ className = 'size-4' }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={`${className} animate-spin`} aria-hidden="true">
      <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeOpacity="0.2" strokeWidth="3" />
      <path d="M21 12a9 9 0 0 0-9-9" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'warning';

const VARIANTS: Record<Variant, string> = {
  primary: 'bg-blurple text-white hover:bg-blurple-hi shadow-[0_8px_24px_-10px_rgb(88_101_242/0.9)]',
  secondary: 'bg-white/[0.06] text-fg hover:bg-white/[0.11] border border-line-strong',
  ghost: 'text-muted hover:text-fg hover:bg-white/[0.06]',
  danger: 'bg-danger/15 text-danger hover:bg-danger/25 border border-danger/30',
  warning: 'bg-amber text-ink-950 hover:brightness-110'
};

export function Button({
  variant = 'secondary', size = 'md', icon, busy, children, className = '', ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: 'sm' | 'md'; icon?: IconName; busy?: boolean }) {
  const pad = size === 'sm' ? 'h-8 px-3 text-[13px] gap-1.5' : 'h-10 px-4 gap-2';
  return (
    <button
      type="button"
      className={`inline-flex items-center justify-center rounded-[10px] font-medium transition-[background,color,filter,transform] duration-150 active:scale-[0.98] disabled:pointer-events-none disabled:opacity-45 ${pad} ${VARIANTS[variant]} ${className}`}
      {...rest}
    >
      {busy ? <Spinner /> : icon ? <Icon name={icon} /> : null}
      {children}
    </button>
  );
}

export function Switch({ checked, onChange, label, hint, disabled }: {
  checked: boolean; onChange: (v: boolean) => void; label: string; hint?: string; disabled?: boolean;
}) {
  return (
    <label className={`flex cursor-pointer items-start gap-3 ${disabled ? 'pointer-events-none opacity-45' : ''}`}>
      <button
        type="button" role="switch" aria-checked={checked} disabled={disabled}
        onClick={() => onChange(!checked)}
        className={`relative mt-0.5 h-5 w-9 shrink-0 rounded-full transition-colors duration-200 ${checked ? 'bg-blurple' : 'bg-ink-600'}`}
      >
        <span className={`absolute top-0.5 left-0.5 size-4 rounded-full bg-white shadow transition-transform duration-200 ease-[var(--ease-out-quart)] ${checked ? 'translate-x-4' : ''}`} />
      </button>
      <span className="min-w-0">
        <span className="block text-fg">{label}</span>
        {hint && <span className="block text-[12.5px] text-faint">{hint}</span>}
      </span>
    </label>
  );
}

export function CheckBox({ state, onToggle, label, disabled }: {
  state: 0 | 1 | 2; onToggle: () => void; label: string; disabled?: boolean;
}) {
  return (
    <button
      type="button" role="checkbox" aria-checked={state === 2 ? 'mixed' : state === 1} aria-label={label}
      disabled={disabled} onClick={onToggle}
      className={`grid size-[18px] shrink-0 place-items-center rounded-[5px] border transition-colors duration-150 ${
        state ? 'border-blurple bg-blurple text-white' : 'border-line-strong bg-ink-950/60 hover:border-blurple-hi'}`}
    >
      {state === 1 && <Icon name="check" className="size-3.5" strokeWidth={2.6} />}
      {state === 2 && <span className="h-0.5 w-2 rounded bg-white" />}
    </button>
  );
}

export function Section({ step, title, aside, children, className = '' }: {
  step: string; title: string; aside?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <section className={`panel flex min-h-0 flex-col ${className}`} aria-labelledby={`sec-${step}`}>
      <header className="flex items-center gap-3 border-b border-line px-5 py-4">
        <span className="grid size-7 place-items-center rounded-full border border-line-strong font-mono text-[12px] text-blurple-hi">{step}</span>
        <h2 id={`sec-${step}`} className="text-[15px] font-semibold tracking-[-0.01em]">{title}</h2>
        <div className="ml-auto flex items-center gap-2">{aside}</div>
      </header>
      {children}
    </section>
  );
}

export function Notice({ tone = 'info', children, icon }: { tone?: 'info' | 'warn' | 'error' | 'ok'; children: ReactNode; icon?: IconName }) {
  const tones = {
    info: 'border-blurple/30 bg-blurple/10 text-[#c9cdfb]',
    warn: 'border-amber/35 bg-amber/10 text-[#f8d79a]',
    error: 'border-danger/35 bg-danger/10 text-[#ffc2ca]',
    ok: 'border-evidence/30 bg-evidence/10 text-[#a8f0d5]'
  } as const;
  const fallback = { info: 'help', warn: 'alert', error: 'alert', ok: 'shield' } as const;
  return (
    <div role={tone === 'error' ? 'alert' : undefined} className={`flex gap-2.5 rounded-xl border px-3.5 py-2.5 text-[13px] leading-snug ${tones[tone]}`}>
      <Icon name={icon ?? fallback[tone]} className="mt-0.5 size-4 shrink-0" />
      <div className="min-w-0">{children}</div>
    </div>
  );
}
