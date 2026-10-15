import { useState } from 'react';
import type { AppState, Mode } from '../api';
import { api, fmt } from '../api';
import { Button, Icon, Notice, Section, type IconName } from '../ui';

export type Method = Mode | 'package';

interface MethodCard {
  key: Method;
  icon: IconName;
  title: string;
  text: string;
  badge: string;
  risk?: boolean;
}

const METHODS: MethodCard[] = [
  { key: 'bot', icon: 'bot', title: 'Bot-Token', text: 'Server-Kanäle, Threads, beide Seiten.', badge: 'regelkonform' },
  { key: 'user', icon: 'user', title: 'Eigenes Konto', text: 'Direktnachrichten mit beiden Seiten.', badge: 'Risiko', risk: true },
  { key: 'package', icon: 'archive', title: 'Datenpaket', text: 'Deine eigenen Nachrichten, offline.', badge: 'regelkonform' }
];

const RISK_TEXT =
  'Discord verbietet das Automatisieren von Benutzerkonten („Self-Bot“). Dein Konto kann dafür gesperrt werden, auch dauerhaft. Das Risiko trägst du. Der Token gibt vollen Zugriff auf dein Konto: nie weitergeben. Das Programm speichert ihn nicht.';

function badgeTone(card: MethodCard) {
  return card.risk ? 'border-amber/40 text-amber' : 'border-evidence/40 text-evidence';
}

export function SourcePanel({ state, onConnected }: { state: AppState; onConnected: () => void }) {
  const [method, setMethod] = useState<Method>('bot');
  const [token, setToken] = useState('');
  const [reveal, setReveal] = useState(false);
  const [riskOk, setRiskOk] = useState(false);
  const [pkgPath, setPkgPath] = useState(state.settings.package_path);
  const [error, setError] = useState<string | null>(null);
  const busy = state.busy === 'connect' || state.busy === 'package';

  const pick = (m: Method) => {
    setMethod(m);
    setError(null);
    if (m !== 'user') setRiskOk(false);
  };

  const connect = async () => {
    setError(null);
    try {
      if (method === 'package') {
        if (!pkgPath.trim()) return setError('Bitte package.zip oder den Ordner wählen.');
        await api.loadPackage(pkgPath.trim());
      } else {
        if (!token.trim()) return setError('Bitte den Token eintragen.');
        await api.connect(method, token.trim(), method === 'user' ? riskOk : true);
      }
      onConnected();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const chooseFile = async (kind: 'zip' | 'package_dir') => {
    try {
      const res = await api.dialog(kind, pkgPath);
      if (res.path) setPkgPath(res.path);
    } catch {
      /* Dialog auf diesem System nicht verfügbar – Pfad von Hand eintragen */
    }
  };

  return (
    <Section step="1" title="Quelle wählen">
      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto scroll-thin p-5">
        <div className="grid gap-2 sm:grid-cols-3">
          {METHODS.map((card) => {
            const active = method === card.key;
            return (
              <button
                key={card.key}
                type="button"
                onClick={() => pick(card.key)}
                aria-pressed={active}
                className={`group relative overflow-hidden rounded-xl border p-3.5 text-left transition-all duration-200 ${
                  active ? 'border-blurple bg-blurple/[0.09] shadow-[0_10px_30px_-18px_rgb(88_101_242/0.9)]' : 'border-line bg-white/[0.02] hover:border-line-strong hover:bg-white/[0.04]'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className={`grid size-9 place-items-center rounded-lg transition-colors ${active ? 'bg-blurple text-white' : 'bg-ink-700 text-muted group-hover:text-fg'}`}>
                    <Icon name={card.icon} className="size-5" />
                  </span>
                  <span className={`rounded-full border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wide ${badgeTone(card)}`}>{card.badge}</span>
                </div>
                <h3 className="mt-2.5 font-semibold">{card.title}</h3>
                <p className="text-[12.5px] leading-snug text-muted">{card.text}</p>
              </button>
            );
          })}
        </div>

        {method !== 'package' ? (
          <div className="space-y-3">
            <div>
              <label className="eyebrow mb-1.5 block">{method === 'user' ? 'Benutzer-Token' : 'Bot-Token'}</label>
              <div className="relative">
                <input
                  className="field pr-11 font-mono text-[13px]"
                  type={reveal ? 'text' : 'password'}
                  value={token}
                  autoComplete="off"
                  spellCheck={false}
                  placeholder={method === 'user' ? 'authorization-Wert aus dem Browser' : 'Token aus dem Developer Portal'}
                  onChange={(e) => setToken(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && connect()}
                />
                <button type="button" onClick={() => setReveal((v) => !v)} aria-label={reveal ? 'Token verbergen' : 'Token anzeigen'}
                  className="absolute top-1/2 right-2 -translate-y-1/2 rounded p-1.5 text-faint hover:text-fg">
                  <Icon name={reveal ? 'eyeOff' : 'eye'} />
                </button>
              </div>
            </div>

            {method === 'user' && (
              <Notice tone="warn">
                <p className="font-medium text-amber">Export mit deinem eigenen Konto</p>
                <p className="mt-1 text-[12.5px] text-[#f8d79a]/90">{RISK_TEXT}</p>
                <label className="mt-2 flex items-center gap-2 text-[13px]">
                  <input type="checkbox" checked={riskOk} onChange={(e) => setRiskOk(e.target.checked)}
                    className="size-4 accent-amber" />
                  Ich habe das Risiko verstanden und trage es selbst.
                </label>
              </Notice>
            )}
          </div>
        ) : (
          <div className="space-y-3">
            <div>
              <label className="eyebrow mb-1.5 block">Datenpaket (package.zip oder entpackter Ordner)</label>
              <input className="field font-mono text-[13px]" value={pkgPath} spellCheck={false}
                placeholder="C:\Users\…\package.zip" onChange={(e) => setPkgPath(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && connect()} />
            </div>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" icon="file" onClick={() => chooseFile('zip')}>ZIP wählen …</Button>
              <Button size="sm" icon="folder" onClick={() => chooseFile('package_dir')}>Ordner wählen …</Button>
            </div>
            <Notice tone="info">Das Datenpaket forderst du in Discord an: Einstellungen → Daten &amp; Privatsphäre → „Alle meine Daten anfordern“. Es enthält nur deine eigenen Nachrichten.</Notice>
          </div>
        )}

        {error && <Notice tone="error">{error}</Notice>}
      </div>

      <div className="flex items-center gap-3 border-t border-line px-5 py-4">
        <Button variant="primary" icon={method === 'package' ? 'archive' : 'plug'} busy={busy}
          disabled={busy || (method === 'user' && !riskOk)} onClick={connect}>
          {method === 'package' ? 'Datenpaket laden' : 'Verbinden'}
        </Button>
        {state.api && (
          <span className="flex items-center gap-1.5 text-[13px] text-evidence">
            <Icon name="check" className="size-4" strokeWidth={2.4} />
            {state.api.name} verbunden
          </span>
        )}
        {state.package && (
          <span className="flex items-center gap-1.5 text-[13px] text-evidence">
            <Icon name="check" className="size-4" strokeWidth={2.4} />
            {fmt(state.package.conversations)} Unterhaltungen
          </span>
        )}
      </div>
    </Section>
  );
}
