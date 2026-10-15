import { useEffect, useMemo, useState } from 'react';
import type { AppState, Source, TreeNode, Trees } from '../api';
import { api, fmt } from '../api';
import { Tree, leafIds } from '../Tree';
import { Button, Icon, Section } from '../ui';

function allLeafIds(nodes: TreeNode[]): string[] {
  return nodes.flatMap(leafIds);
}

export function SelectPanel({
  state, trees, source, selected, onChange, onKick
}: {
  state: AppState;
  trees: Trees;
  source: Source;
  selected: Set<string>;
  onChange: (next: Set<string>) => void;
  onKick: () => void;
}) {
  const [filter, setFilter] = useState('');
  const [loadingKey, setLoadingKey] = useState<string | null>(null);
  const nodes = source === 'api' ? trees.api : trees.package;
  const total = useMemo(() => allLeafIds(nodes).length, [nodes]);
  const connected = source === 'api' ? !!state.api : !!state.package;

  // Wenn ein Server nachgeladen wurde, den Ladezeiger wieder freigeben.
  useEffect(() => {
    if (!state.busy) setLoadingKey(null);
  }, [state.busy, trees.rev]);

  const loadGuild = async (node: TreeNode) => {
    if (!node.id || loadingKey) return;
    setLoadingKey(node.key);
    try {
      await api.loadGuild(node.id);
      onKick();
    } catch {
      setLoadingKey(null);
    }
  };

  const setAll = (on: boolean) => onChange(on ? new Set(allLeafIds(nodes)) : new Set());

  return (
    <Section
      step="2"
      title="Auswählen"
      className="flex-1"
      aside={
        selected.size > 0 && (
          <span className="rounded-full bg-blurple/15 px-2.5 py-1 font-mono text-[11px] text-blurple-hi">
            {fmt(selected.size)} gewählt
          </span>
        )
      }
    >
      {!connected ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 p-10 text-center">
          <span className="grid size-12 place-items-center rounded-full border border-line text-faint">
            <Icon name="archive" className="size-6" />
          </span>
          <p className="max-w-xs text-muted">Erst oben eine Quelle verbinden. Danach erscheinen hier die Kanäle und Unterhaltungen.</p>
        </div>
      ) : (
        <>
          <div className="flex items-center gap-2 border-b border-line px-4 py-3">
            <div className="relative flex-1">
              <Icon name="search" className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-faint" />
              <input
                className="field py-1.5 pl-9 text-[13px]"
                placeholder="Filtern nach Name …"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
              />
            </div>
            <Button size="sm" variant="ghost" onClick={() => setAll(true)} disabled={!total}>Alle</Button>
            <Button size="sm" variant="ghost" onClick={() => setAll(false)} disabled={!selected.size}>Keine</Button>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto scroll-thin">
            <Tree
              nodes={nodes}
              selected={selected}
              onChange={onChange}
              filter={filter}
              loadingKey={loadingKey}
              onExpandUnloaded={loadGuild}
              onSelectUnloaded={loadGuild}
            />
          </div>
        </>
      )}
    </Section>
  );
}
