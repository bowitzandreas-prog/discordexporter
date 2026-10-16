import SpotlightCard from '../bits/SpotlightCard';
import CountUp from '../bits/CountUp';
import type { ExportResult } from '../api';
import { api } from '../api';
import { Button, Icon, Notice } from '../ui';

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-xl border border-line bg-ink-950/40 px-3 py-2.5">
      <div className="font-mono text-[22px] leading-none text-fg tabular-nums">
        <CountUp to={value} duration={1} separator="." />
      </div>
      <div className="mt-1 text-[11px] text-faint">{label}</div>
    </div>
  );
}

export function ResultCard({ result }: { result: ExportResult }) {
  if (result.cancelled && !result.files) {
    return <Notice tone="warn" icon="alert">Abgebrochen. Es wurden keine vollständigen Dateien geschrieben.</Notice>;
  }
  const hasErrors = result.errors.length > 0;
  const tone = hasErrors ? 'border-danger/40' : 'border-evidence/40';
  const proto = result.protocol[0];

  return (
    <SpotlightCard
      theme="dark"
      spotlightColor={hasErrors ? '#ff6b7d' : '#3dd6a0'}
      className={`rounded-2xl border ${tone} p-5`}
      style={{ ['--spotlight-card-surface' as string]: 'rgba(10,14,26,0.6)' }}
    >
      <div className="flex items-center gap-2.5">
        <span className={`grid size-9 place-items-center rounded-full ${hasErrors ? 'bg-danger/20 text-danger' : 'bg-evidence/20 text-evidence'}`}>
          <Icon name={hasErrors ? 'alert' : 'shield'} className="size-5" strokeWidth={2} />
        </span>
        <div>
          <h3 className="font-semibold">{hasErrors ? 'Export mit Fehlern' : 'Beweise gesichert'}</h3>
          <p className="text-[12.5px] text-muted">{result.cancelled ? 'Teilweise – abgebrochen.' : result.text}</p>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Stat label="Kanäle" value={result.channels} />
        <Stat label="Nachrichten" value={result.messages} />
        <Stat label="Dateien" value={result.files} />
        <Stat label="Medien" value={result.media_total} />
      </div>

      {result.sums_hash && (
        <div className="mt-4 rounded-xl border border-line bg-ink-950/50 p-3">
          <div className="flex items-center gap-1.5 text-[12px] text-evidence">
            <Icon name="check" className="size-3.5" strokeWidth={2.4} /> SHA-256 der Prüfsummendatei
          </div>
          <code className="mt-1 block break-all font-mono text-[11px] text-muted">{result.sums_hash}</code>
        </div>
      )}

      {result.media_failed > 0 && (
        <p className="mt-3 text-[12px] text-amber">{result.media_failed} Medien konnten nicht geladen werden (meist abgelaufene Links).</p>
      )}
      {result.skipped.length > 0 && (
        <details className="mt-3 text-[12.5px] text-muted">
          <summary className="cursor-pointer text-faint hover:text-fg">{result.skipped.length} übersprungen</summary>
          <ul className="mt-1.5 space-y-1 pl-1">{result.skipped.map((x, i) => <li key={i} className="text-[12px]">{x}</li>)}</ul>
        </details>
      )}
      {hasErrors && (
        <ul className="mt-3 space-y-1 text-[12.5px] text-danger">{result.errors.slice(0, 5).map((x, i) => <li key={i}>{x}</li>)}</ul>
      )}

      <div className="mt-4 flex flex-wrap gap-2">
        <Button size="sm" variant="primary" icon="folder" onClick={() => api.open(result.out_dir)}>Zielordner öffnen</Button>
        {result.html[0] && <Button size="sm" icon="external" onClick={() => api.open(result.html[0])}>HTML ansehen</Button>}
        {proto && <Button size="sm" variant="ghost" icon="file" onClick={() => api.open(proto)}>Protokoll</Button>}
      </div>
    </SpotlightCard>
  );
}
