import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Icon } from '../ui';

export function LogConsole({ logs, busy }: { logs: { seq: number; text: string }[]; busy: boolean }) {
  const [open, setOpen] = useState(false);
  const bodyRef = useRef<HTMLDivElement>(null);

  // Bei neuer Aktivität automatisch aufklappen, damit Fehler nicht übersehen werden.
  useEffect(() => {
    if (busy) setOpen(true);
  }, [busy]);

  useLayoutEffect(() => {
    if (open && bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
  }, [logs, open]);

  const last = logs[logs.length - 1]?.text ?? 'Bereit.';

  return (
    <div className="panel overflow-hidden">
      <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open}
        className="flex w-full items-center gap-2.5 px-4 py-2.5 text-left">
        <Icon name="terminal" className="size-4 text-faint" />
        <span className="eyebrow">Protokoll</span>
        {!open && <span className="min-w-0 flex-1 truncate font-mono text-[12px] text-muted">{last}</span>}
        {busy && <span className="size-1.5 animate-pulse rounded-full bg-evidence" aria-hidden="true" />}
        <Icon name="chevron" className={`ml-auto size-4 text-faint transition-transform duration-200 ${open ? '-rotate-90' : 'rotate-90'}`} />
      </button>
      {open && (
        <div ref={bodyRef} className="max-h-48 overflow-y-auto scroll-thin border-t border-line bg-ink-950/60 px-4 py-3 font-mono text-[12px] leading-relaxed text-muted">
          {logs.length === 0 ? (
            <p className="text-faint">Noch keine Meldungen.</p>
          ) : (
            logs.map((l) => <div key={l.seq} className="whitespace-pre-wrap break-words">{l.text}</div>)
          )}
        </div>
      )}
    </div>
  );
}
