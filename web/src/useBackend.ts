import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError, type AppState, type Trees } from './api';

/** Fragt den lokalen Server regelmäßig ab: schnell, solange etwas läuft, sonst gemächlich. */
export function useBackend() {
  const [state, setState] = useState<AppState | null>(null);
  const [trees, setTrees] = useState<Trees>({ rev: -1, api: [], package: [] });
  const [logs, setLogs] = useState<{ seq: number; text: string }[]>([]);
  const [fatal, setFatal] = useState<string | null>(null);
  const logSeq = useRef(0);
  const treeRev = useRef(-1);
  const busy = useRef(false);
  const timer = useRef<number | undefined>(undefined);
  const failures = useRef(0);

  const refresh = useCallback(async () => {
    try {
      const s = await api.state(logSeq.current);
      failures.current = 0;
      if (s.logs.length) setLogs((prev) => [...prev, ...s.logs].slice(-1500));
      logSeq.current = s.log_seq;
      if (s.tree_rev !== treeRev.current) {
        const t = await api.tree();
        treeRev.current = t.rev;
        setTrees(t);
      }
      busy.current = !!s.busy;
      setState(s);
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setFatal(err.message);
      } else if (++failures.current >= 3) {
        setFatal('Keine Verbindung zum Programm. Wurde das Konsolenfenster geschlossen? Dann neu starten.');
      }
    }
  }, []);

  useEffect(() => {
    let alive = true;
    const loop = async () => {
      await refresh();
      if (alive) timer.current = window.setTimeout(loop, busy.current ? 500 : 2000);
    };
    loop();
    return () => {
      alive = false;
      window.clearTimeout(timer.current);
    };
  }, [refresh]);

  /** Nach einer Aktion sofort nachfragen, nicht erst beim nächsten Takt. */
  const kick = useCallback(() => {
    busy.current = true;
    window.setTimeout(refresh, 120);
  }, [refresh]);

  return { state, trees, logs, fatal, setFatal, refresh, kick };
}
