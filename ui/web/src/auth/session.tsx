import { useQuery, useQueryClient } from '@tanstack/react-query';
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';
import { ApiClient, ApiError, fetchUiConfig, type UiConfig } from '../api/client';
import type { Me, Mode } from '../api/types';

const KEY_STORAGE = 'msa.key';
const MODE_STORAGE = 'msa.mode';

function read(name: string): string {
  try {
    return window.localStorage.getItem(name) ?? '';
  } catch {
    return '';
  }
}

function write(name: string, value: string | null) {
  try {
    if (value === null) window.localStorage.removeItem(name);
    else window.localStorage.setItem(name, value);
  } catch {
    // Storage may be blocked; the session then lives until the tab is closed.
  }
}

/** The external LLM model when one answers, else null: it limits work to demo data. */
export function externalLlm(me: Me | null | undefined): string | null {
  return me?.llm?.external ? (me.llm.model ?? 'внешняя модель') : null;
}

/** Namespaces this key may work in: bank portfolios never reach an external model. */
export function availableModes(me: Me | null | undefined): Mode[] {
  if (!me) return [];
  const scopes = new Set(me.scopes);
  const modes: Mode[] = [];
  if (
    me.role !== 'demo' &&
    (scopes.has('production:*') || scopes.has('admin:*')) &&
    !externalLlm(me)
  ) {
    modes.push('production');
  }
  if (scopes.has('demo:*') || scopes.has('admin:*') || me.role === 'demo') modes.push('demo');
  return modes;
}

export const canRun = (me: Me | null | undefined) =>
  !!me && ['analyst', 'admin', 'demo'].includes(me.role);
export const canFixGraph = canRun;
export const canApprove = (me: Me | null | undefined) =>
  !!me && ['risk_manager', 'admin', 'demo'].includes(me.role);

interface SessionValue {
  apiKey: string;
  me: Me | null;
  meLoading: boolean;
  meError: ApiError | null;
  mode: Mode;
  modes: Mode[];
  client: ApiClient | null;
  config: UiConfig;
  signIn: (key: string) => void;
  signOut: () => void;
  setMode: (mode: Mode) => void;
}

const SessionContext = createContext<SessionValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [apiKey, setApiKey] = useState(() => read(KEY_STORAGE));
  const [savedMode, setSavedMode] = useState(() => read(MODE_STORAGE));

  const config = useQuery({ queryKey: ['ui-config'], queryFn: fetchUiConfig, staleTime: Infinity });
  const meQuery = useQuery({
    queryKey: ['me', apiKey],
    queryFn: () => new ApiClient(apiKey, 'demo').me(),
    enabled: !!apiKey,
    retry: false,
    staleTime: 5 * 60_000,
  });

  const me = apiKey ? (meQuery.data ?? null) : null;
  const modes = availableModes(me);
  const mode: Mode = modes.includes(savedMode as Mode) ? (savedMode as Mode) : (modes[0] ?? 'demo');
  const client = useMemo(() => (apiKey && me ? new ApiClient(apiKey, mode) : null), [apiKey, me, mode]);

  const signIn = useCallback(
    (key: string) => {
      write(KEY_STORAGE, key);
      setApiKey(key);
      // Everything read with the previous key belongs to another person.
      queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== 'ui-config' });
    },
    [queryClient],
  );

  const signOut = useCallback(() => {
    write(KEY_STORAGE, null);
    setApiKey('');
    queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== 'ui-config' });
  }, [queryClient]);

  const setMode = useCallback((next: Mode) => {
    write(MODE_STORAGE, next);
    setSavedMode(next);
  }, []);

  const value: SessionValue = {
    apiKey,
    me,
    meLoading: !!apiKey && meQuery.isPending,
    meError: meQuery.error instanceof ApiError ? meQuery.error : null,
    mode,
    modes,
    client,
    config: config.data ?? {},
    signIn,
    signOut,
    setMode,
  };
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error('useSession outside SessionProvider');
  return value;
}

/** The API client of a signed-in page; pages behind RequireSession always have one. */
export function useClient(): ApiClient {
  const { client } = useSession();
  if (!client) throw new Error('useClient without a session');
  return client;
}
