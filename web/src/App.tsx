import { useEffect, useMemo, useState } from 'react';
import DarkVeil from './bits/DarkVeil';
import ShinyText from './bits/ShinyText';
import ClickSpark from './bits/ClickSpark';
import { api, hasKey, type Source } from './api';
import { useBackend } from './useBackend';
import { Button, Icon, Notice } from './ui';
import { SourcePanel, type Method } from './components/SourcePanel';
import { SelectPanel } from './components/SelectPanel';
import { ExportPanel } from './components/ExportPanel';
import { LogConsole } from './components/LogConsole';

function Header({ version, onQuit }: { version: string; onQuit: () => void }) {
  return (
    <header className="flex items-center gap-3 px-1 py-1">
      <span className="grid size-10 place-items-center rounded-xl bg-blurple shadow-[0_8px_24px_-10px_rgb(88_101_242/0.9)]">
        <Icon name="shield" className="size-6 text-white" strokeWidth={1.8} />
      </span>
      <div className="min-w-0">
        <ShinyText text="Discord-Export" speed={5} className="text-[22px] font-bold tracking-[-0.02em]"
          color="#e9ebf8" shineColor="#8b93ff" />
        <p className="text-[12px] text-faint">Lokale Beweissicherung · Version {version}</p>
      </div>
      <div className="ml-auto flex items-center gap-2">
        <span className="hidden items-center gap-1.5 rounded-full border border-line px-2.5 py-1 text-[11px] text-muted sm:flex">
          <span className="size-1.5 rounded-full bg-evidence" /> läuft lokal auf diesem PC
        </span>
        <Button size="sm" variant="ghost" icon="power" onClick={onQuit}>Beenden</Button>
      </div>
    </header>
  );
}

export default function App() {
  const { state, trees, logs, fatal, setFatal, kick } = useBackend();
  const [selApi, setSelApi] = useState<Set<string>>(new Set());
  const [selPkg, setSelPkg] = useState<Set<string>>(new Set());

  // Quelle: Datenpaket nur, wenn geladen und keine API-Verbindung besteht.
  const source: Source = useMemo(() => {
    if (state?.api) return 'api';
    if (state?.package) return 'package';
    return 'api';
  }, [state?.api, state?.package]);

  const selected = source === 'api' ? selApi : selPkg;
  const setSelected = source === 'api' ? setSelApi : setSelPkg;

  // Auswahl verwerfen, die nicht mehr im Baum steht (nach Abmelden o. Ä.).
  useEffect(() => {
    const live = new Set((source === 'api' ? trees.api : trees.package).flatMap(function ids(n): string[] {
      return n.kind === 'channel' && n.id ? [n.id] : (n.children ?? []).flatMap(ids);
    }));
    setSelected((prev) => {
      const next = new Set([...prev].filter((id) => live.has(id)));
      return next.size === prev.size ? prev : next;
    });
  }, [trees, source, setSelected]);

  if (!hasKey()) {
    return (
      <Shell>
        <div className="mx-auto max-w-md pt-24">
          <Notice tone="error">Diese Seite wurde ohne gültigen Sitzungsschlüssel geöffnet. Bitte das Programm über das Konsolenfenster neu starten und den dort angezeigten Link verwenden.</Notice>
        </div>
      </Shell>
    );
  }

  if (!state) {
    return <Shell><div className="grid flex-1 place-items-center text-faint">Lade …</div></Shell>;
  }

  const onConnected: (m?: Method) => void = () => {
    setSelected(new Set());
    kick();
  };

  return (
    <Shell>
      <div className="mx-auto flex min-h-full w-full max-w-6xl flex-col gap-4 px-4 py-5 sm:px-6">
        <Header version={state.version} onQuit={async () => { try { await api.quit(); } catch { /* egal */ } setFatal('Das Programm wurde beendet. Du kannst dieses Fenster schließen.'); }} />

        {fatal && <Notice tone="error">{fatal}</Notice>}

        <div className="grid flex-1 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)]">
          <div className="flex min-h-0 flex-col gap-4">
            <SourcePanel state={state} onConnected={onConnected} />
            <SelectPanel state={state} trees={trees} source={source} selected={selected}
              onChange={setSelected} onKick={kick} />
          </div>
          <div className="flex min-h-0 flex-col gap-4">
            <ExportPanel state={state} source={source} selected={selected} busyExport={state.busy === 'export'} />
            <LogConsole logs={logs} busy={!!state.busy} />
          </div>
        </div>

        <footer className="flex flex-wrap items-center justify-between gap-2 px-1 pb-1 text-[11px] text-faint">
          <span>Kein Upload, keine Cloud. Tokens bleiben nur im Speicher dieses Fensters.</span>
          <span className="font-mono">127.0.0.1 · nur du</span>
        </footer>
      </div>
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <ClickSpark sparkColor="#8b93ff" sparkCount={8} sparkRadius={16} duration={520} className="min-h-full">
      <div className="relative min-h-dvh">
        <div className="pointer-events-none fixed inset-0 -z-10 opacity-70">
          <DarkVeil color="#5865f2" speed={0.35} glow={0.3} warp={0.2} brightness={0.9} grain={0.04} fade={0.3} />
        </div>
        <div className="relative flex min-h-dvh flex-col">{children}</div>
      </div>
    </ClickSpark>
  );
}
