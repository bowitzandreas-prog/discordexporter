// Verbindung zum lokalen Python-Server. Der Sitzungsschlüssel kommt aus der Start-URL (#k=…).

export type Mode = 'bot' | 'user';
export type Source = 'api' | 'package';

export interface TreeNode {
  key: string;
  id?: string;
  kind: 'dms' | 'guild' | 'category' | 'group' | 'channel';
  name: string;
  icon?: string | null;
  loaded?: boolean;
  type_label?: string;
  dm?: boolean;
  forum?: boolean;
  voice?: boolean;
  count?: number;
  children?: TreeNode[];
}

export interface Settings {
  out_dir: string;
  formats: string[];
  download_media: boolean;
  include_threads: boolean;
  csv_delimiter: string;
  package_path: string;
}

export interface ExportResult {
  text: string;
  channels: number;
  messages: number;
  files: number;
  media_ok: number;
  media_total: number;
  media_failed: number;
  skipped: string[];
  errors: string[];
  cancelled: boolean;
  out_dir: string;
  protocol: string[];
  html: string[];
  sums_hash: string | null;
}

export interface AppState {
  app: string;
  version: string;
  busy: null | 'connect' | 'load_guild' | 'package' | 'export';
  progress: { index?: number; total?: number; fraction?: number; label?: string; overall?: number };
  logs: { seq: number; text: string }[];
  log_seq: number;
  tree_rev: number;
  api: null | { mode: Mode; name: string; username: string; id: string };
  package: null | { name: string; path: string; conversations: number; messages: number };
  result: ExportResult | null;
  error: null | { kind: string; message: string };
  settings: Settings;
  formats: { key: string; label: string; ext: string }[];
}

export interface Trees {
  rev: number;
  api: TreeNode[];
  package: TreeNode[];
}

const KEY_STORE = 'dce-key';
let memoryKey = '';

function sessionKey(): string {
  const match = window.location.hash.match(/k=([A-Za-z0-9_-]+)/);
  if (match) {
    try {
      sessionStorage.setItem(KEY_STORE, match[1]);
    } catch {
      /* privater Modus: Schlüssel bleibt nur im Speicher */
    }
    history.replaceState(null, '', window.location.pathname);
    memoryKey = match[1];
    return match[1];
  }
  if (memoryKey) return memoryKey;
  try {
    return sessionStorage.getItem(KEY_STORE) ?? '';
  } catch {
    return '';
  }
}

export const hasKey = () => sessionKey() !== '';

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function call<T>(method: 'GET' | 'POST', path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: {
      'X-DCE-Key': sessionKey(),
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {})
    },
    body: body !== undefined ? JSON.stringify(body) : undefined
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(data.error ?? `Fehler ${res.status}`, res.status);
  return data as T;
}

export const api = {
  state: (logSince: number) => call<AppState>('GET', `/api/state?log_since=${logSince}`),
  tree: () => call<Trees>('GET', '/api/tree'),
  connect: (mode: Mode, token: string, acceptedRisk: boolean) =>
    call('POST', '/api/connect', { mode, token, accepted_risk: acceptedRisk }),
  disconnect: () => call('POST', '/api/disconnect', {}),
  loadGuild: (guildId: string) => call('POST', '/api/load-guild', { guild_id: guildId }),
  loadPackage: (path: string) => call('POST', '/api/package', { path }),
  exportRun: (source: Source, ids: string[], options: Record<string, unknown>) =>
    call('POST', '/api/export', { source, ids, options }),
  cancel: () => call('POST', '/api/cancel', {}),
  dialog: (kind: 'zip' | 'package_dir' | 'out_dir', initial = '') =>
    call<{ path: string | null }>('POST', '/api/dialog', { kind, initial }),
  open: (path: string) => call('POST', '/api/open', { path }),
  quit: () => call('POST', '/api/quit', {})
};

export const fmt = (n: number) => n.toLocaleString('de-DE');
