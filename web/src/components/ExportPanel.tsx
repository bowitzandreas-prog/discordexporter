import { useEffect, useState } from 'react';
import type { AppState, ExportResult, Source } from '../api';
import { api, fmt } from '../api';
import { Button, Icon, Notice, Section, Switch } from '../ui';
import { ResultCard } from './ResultCard';

const DELIMS = [
  { key: ';', label: '; (Excel DE)' },
  { key: ',', label: ', (Komma)' },
  { key: 'tab', label: 'Tab' }
];

export function ExportPanel({
  state, source, selected, busyExport
}: {
  state: AppState;
  source: Source;
  selected: Set<string>;
  busyExport: boolean;
}) {
  const s = state.settings;
  const [formats, setFormats] = useState<string[]>(s.formats);
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [media, setMedia] = useState(s.download_media);
  const [threads, setThreads] = useState(s.include_threads);
  const [delim, setDelim] = useState(s.csv_delimiter);
  const [outDir, setOutDir] = useState(s.out_dir);
  const [error, setError] = useState<string | null>(null);

  // Gespeicherte Einstellungen übernehmen, sobald sie vom Server kommen.
  useEffect(() => { setOutDir(s.out_dir); }, [s.out_dir]);

  const toggleFormat = (key: string) =>
    setFormats((prev) => (prev.includes(key) ? prev.filter((f) => f !== key) : [...prev, key]));

  const chooseOut = async () => {
    try {
      const res = await api.dialog('out_dir', outDir);
      if (res.path) setOutDir(res.path);
    } catch { /* kein Dialog: Pfad von Hand */ }
  };

  const start = async () => {
    setError(null);
    if (!selected.size) return setError('Bitte oben mindestens einen Kanal anhaken.');
    if (!formats.length) return setError('Bitte mindestens ein Format wählen.');
    if (!outDir.trim()) return setError('Bitte einen Zielordner wählen.');
    try {
      await api.exportRun(source, [...selected], {
        formats, from, to, out_dir: outDir.trim(),
        download_media: media, include_threads: threads, csv_delimiter: delim
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const progress = state.progress;
  const result = state.result as ExportResult | null;
  const pct = Math.round((progress.overall ?? 0) * 100);

  return (
    <Section step="3" title="Exportieren">
      <div className="flex flex-col gap-5 p-5">
        <div>
          <label className="eyebrow mb-2 block">Formate</label>
          <div className="flex flex-wrap gap-2">
            {state.formats.map((f) => {
              const on = formats.includes(f.key);
              return (
                <button key={f.key} type="button" onClick={() => toggleFormat(f.key)} aria-pressed={on}
                  className={`flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-[13px] transition-colors duration-150 ${
                    on ? 'border-blurple bg-blurple/15 text-fg' : 'border-line text-muted hover:border-line-strong hover:text-fg'}`}>
                  <span className={`grid size-4 place-items-center rounded-[4px] ${on ? 'bg-blurple text-white' : 'border border-line-strong'}`}>
                    {on && <Icon name="check" className="size-3" strokeWidth={3} />}
                  </span>
                  {f.label}
                </button>
              );
            })}
          </div>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="min-w-0">
            <label className="eyebrow mb-2 block">Zeitraum (leer = alles)</label>
            <div className="flex items-center gap-2">
              <input type="date" className="field min-w-0 flex-1 text-[13px]" value={from} max={to || undefined} onChange={(e) => setFrom(e.target.value)} aria-label="von" />
              <span className="shrink-0 text-faint">bis</span>
              <input type="date" className="field min-w-0 flex-1 text-[13px]" value={to} min={from || undefined} onChange={(e) => setTo(e.target.value)} aria-label="bis" />
            </div>
          </div>
          <div>
            <label className="eyebrow mb-2 block">CSV-Trennzeichen</label>
            <div className="relative">
              <select className="field appearance-none pr-9 text-[13px]" value={delim} onChange={(e) => setDelim(e.target.value)}>
                {DELIMS.map((d) => <option key={d.key} value={d.key} className="bg-ink-800">{d.label}</option>)}
              </select>
              <Icon name="chevron" className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 rotate-90 text-faint" />
            </div>
          </div>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <Switch checked={media} onChange={setMedia} label="Medien herunterladen"
            hint="Anhänge, Avatare, Emojis – nötig fürs Archiv (Links verfallen)." />
          <Switch checked={threads} onChange={setThreads} label="Threads mitexportieren"
            hint="Nur bei Server-Kanälen." disabled={source === 'package'} />
        </div>

        <div>
          <label className="eyebrow mb-2 block">Zielordner</label>
          <div className="flex gap-2">
            <input className="field font-mono text-[13px]" value={outDir} spellCheck={false}
              onChange={(e) => setOutDir(e.target.value)} placeholder="Ordner für den Export" />
            <Button icon="folder" onClick={chooseOut} aria-label="Ordner wählen">Wählen</Button>
          </div>
        </div>

        {error && <Notice tone="error">{error}</Notice>}

        {busyExport && (
          <div className="space-y-2" role="status" aria-live="polite">
            <div className="flex items-center justify-between text-[13px]">
              <span className="truncate text-muted">{progress.label || 'Export läuft …'}</span>
              <span className="font-mono text-blurple-hi">{pct}%</span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-ink-700">
              <div className="h-full rounded-full bg-gradient-to-r from-blurple to-blurple-hi transition-[width] duration-300 ease-out"
                style={{ width: `${pct}%` }} />
            </div>
            {progress.total ? (
              <p className="font-mono text-[11px] text-faint">Kanal {Math.min((progress.index ?? 0) + 1, progress.total)}/{progress.total}</p>
            ) : null}
          </div>
        )}

        {result && !busyExport && <ResultCard result={result} />}
      </div>

      <div className="mt-auto flex items-center gap-3 border-t border-line px-5 py-4">
        {busyExport ? (
          <Button variant="danger" icon="x" onClick={() => api.cancel()}>Abbrechen</Button>
        ) : (
          <Button variant="primary" icon="shield" onClick={start} disabled={!selected.size}>
            Export &amp; Beweissicherung starten
          </Button>
        )}
        <span className="text-[12.5px] text-faint">
          {selected.size ? `${fmt(selected.size)} Auswahl${selected.size === 1 ? '' : 'en'}` : 'nichts gewählt'}
        </span>
      </div>
    </Section>
  );
}
