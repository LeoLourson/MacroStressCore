import { useCallback, useEffect, useMemo, useState } from 'react';
import type { Graph, ScenarioParameter } from '../../../api/types';

export interface DraftValue {
  graph: Graph;
  parameters: Record<string, ScenarioParameter>;
}

function load(key: string): DraftValue | null {
  try {
    const text = window.localStorage.getItem(key);
    return text ? (JSON.parse(text) as DraftValue) : null;
  } catch {
    return null;
  }
}

function save(key: string, value: DraftValue | null) {
  try {
    if (value) window.localStorage.setItem(key, JSON.stringify(value));
    else window.localStorage.removeItem(key);
  } catch {
    // Without storage the draft lives until the page is closed.
  }
}

const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value)) as T;

/**
 * The analyst's unsent edits at one stop of one run. Kept in the browser, so a reload or a
 * look at another tab does not lose them; a new stop starts a new draft.
 */
export function useDraft(runId: string, interruptId: string, initial: DraftValue) {
  const key = `msa.draft.${runId}.${interruptId}`;
  const original = useMemo(() => JSON.stringify(initial), [initial]);
  const [value, setValue] = useState<DraftValue>(() => load(key) ?? clone(initial));

  const changed = useMemo(() => JSON.stringify(value) !== original, [value, original]);
  useEffect(() => save(key, changed ? value : null), [key, value, changed]);

  const setGraph = useCallback((graph: Graph) => setValue((v) => ({ ...v, graph })), []);
  const setParameters = useCallback(
    (parameters: Record<string, ScenarioParameter>) => setValue((v) => ({ ...v, parameters })),
    [],
  );
  const reset = useCallback(() => setValue(JSON.parse(original) as DraftValue), [original]);
  const discard = useCallback(() => save(key, null), [key]);

  return { ...value, changed, setGraph, setParameters, reset, discard };
}

export type Draft = ReturnType<typeof useDraft>;
