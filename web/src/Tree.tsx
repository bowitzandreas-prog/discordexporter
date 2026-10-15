import { useMemo, useState } from 'react';
import type { TreeNode } from './api';
import { fmt } from './api';
import { CheckBox, Icon, Spinner, type IconName } from './ui';

// ---------------------------------------------------------------- Logik

export function leafIds(node: TreeNode): string[] {
  if (node.kind === 'channel') return node.id ? [node.id] : [];
  return (node.children ?? []).flatMap(leafIds);
}

export function checkState(node: TreeNode, selected: Set<string>): 0 | 1 | 2 {
  const ids = leafIds(node);
  if (!ids.length) return 0;
  const hit = ids.filter((id) => selected.has(id)).length;
  return hit === 0 ? 0 : hit === ids.length ? 1 : 2;
}

export function toggled(node: TreeNode, selected: Set<string>): Set<string> {
  const next = new Set(selected);
  const ids = leafIds(node);
  const on = checkState(node, selected) !== 1;
  for (const id of ids) on ? next.add(id) : next.delete(id);
  return next;
}

/** Filter: Kanäle, deren Name passt, samt Eltern. Passt ein Server/Gruppe selbst, bleibt er ganz. */
function filterNodes(nodes: TreeNode[], term: string): TreeNode[] {
  if (!term) return nodes;
  const out: TreeNode[] = [];
  for (const n of nodes) {
    if (n.name.toLowerCase().includes(term)) {
      out.push(n);
      continue;
    }
    if (n.children?.length) {
      const kids = filterNodes(n.children, term);
      if (kids.length) out.push({ ...n, children: kids });
    }
  }
  return out;
}

// ----------------------------------------------------------- Darstellung

function glyph(n: TreeNode): IconName {
  if (n.kind === 'dms') return 'dm';
  if (n.kind === 'group') return n.name.startsWith('Server') ? 'hash' : 'dm';
  if (n.dm) return 'user';
  if (n.voice) return 'voice';
  if (n.forum) return 'forum';
  return 'hash';
}

function Avatar({ node }: { node: TreeNode }) {
  const [broken, setBroken] = useState(false);
  const round = node.kind === 'guild' ? 'rounded-[9px]' : 'rounded-full';
  if (node.icon && !broken) {
    return <img src={node.icon} alt="" loading="lazy" onError={() => setBroken(true)}
      className={`size-6 shrink-0 object-cover ${round} bg-ink-700`} />;
  }
  if (node.kind === 'guild') {
    const letters = node.name.split(/\s+/).map((w) => w[0]).join('').slice(0, 2).toUpperCase();
    return <span className={`grid size-6 shrink-0 place-items-center ${round} bg-ink-600 font-mono text-[10px] text-muted`}>{letters}</span>;
  }
  return <span className="grid size-6 shrink-0 place-items-center text-faint"><Icon name={glyph(node)} /></span>;
}

interface TreeProps {
  nodes: TreeNode[];
  selected: Set<string>;
  onChange: (next: Set<string>) => void;
  filter: string;
  loadingKey: string | null;
  onExpandUnloaded: (node: TreeNode) => void;
  onSelectUnloaded: (node: TreeNode) => void;
}

export function Tree({ nodes, selected, onChange, filter, loadingKey, onExpandUnloaded, onSelectUnloaded }: TreeProps) {
  const [open, setOpen] = useState<Set<string>>(() => new Set(['dm']));
  const term = filter.trim().toLowerCase();
  const visible = useMemo(() => filterNodes(nodes, term), [nodes, term]);

  const toggleOpen = (n: TreeNode) => {
    if (n.kind === 'guild' && n.loaded === false && !open.has(n.key)) onExpandUnloaded(n);
    setOpen((prev) => {
      const next = new Set(prev);
      next.has(n.key) ? next.delete(n.key) : next.add(n.key);
      return next;
    });
  };

  const render = (n: TreeNode, depth: number) => {
    const isLeaf = n.kind === 'channel';
    const unloaded = n.kind === 'guild' && n.loaded === false;
    const expanded = term ? true : open.has(n.key) || n.kind === 'category';
    const state = unloaded ? 0 : checkState(n, selected);
    const count = isLeaf ? null : leafIds(n).length;
    const loading = loadingKey === n.key;
    return (
      <li key={n.key} role="treeitem" aria-expanded={isLeaf ? undefined : expanded} aria-selected={state === 1}>
        <div
          className={`group flex h-9 items-center gap-2 rounded-lg pr-2 transition-colors duration-100 hover:bg-white/[0.045] ${state === 1 && isLeaf ? 'bg-blurple/[0.08]' : ''}`}
          style={{ paddingLeft: 6 + depth * 18 }}
        >
          {isLeaf || n.kind === 'category' ? (
            <span className="w-5 shrink-0" />
          ) : (
            <button type="button" onClick={() => toggleOpen(n)} aria-label={expanded ? 'Zuklappen' : 'Aufklappen'}
              className="grid size-5 shrink-0 place-items-center rounded text-faint hover:text-fg">
              {loading ? <Spinner className="size-3.5" /> :
                <Icon name="chevron" className={`size-3.5 transition-transform duration-200 ${expanded ? 'rotate-90' : ''}`} />}
            </button>
          )}
          <CheckBox
            state={state}
            label={`${n.name} auswählen`}
            onToggle={() => (unloaded ? onSelectUnloaded(n) : onChange(toggled(n, selected)))}
          />
          {n.kind === 'category' ? (
            <span className="eyebrow truncate">{n.name}</span>
          ) : (
            <>
              <Avatar node={n} />
              <button type="button" className="min-w-0 flex-1 truncate text-left"
                onClick={() => (isLeaf ? onChange(toggled(n, selected)) : toggleOpen(n))}>
                <span className={isLeaf ? 'text-fg/90' : 'font-medium text-fg'}>{n.name}</span>
              </button>
            </>
          )}
          <span className="ml-auto shrink-0 font-mono text-[11px] text-faint">
            {n.count !== undefined ? `${fmt(n.count)} Nachr.` :
              unloaded ? (loading ? 'lädt …' : 'aufklappen') :
                isLeaf ? n.type_label : count ? fmt(count) : ''}
          </span>
        </div>
        {!isLeaf && expanded && n.children && n.children.length > 0 && (
          <ul role="group">{n.children.map((c) => render(c, depth + (n.kind === 'category' ? 0 : 1)))}</ul>
        )}
      </li>
    );
  };

  if (!visible.length) {
    return <p className="px-4 py-10 text-center text-faint">{term ? `Nichts gefunden für „${filter}“.` : 'Keine Einträge.'}</p>;
  }
  return <ul role="tree" aria-multiselectable="true" className="px-2 py-2">{visible.map((n) => render(n, 0))}</ul>;
}
