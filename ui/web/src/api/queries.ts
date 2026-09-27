import { useDebouncedValue } from '@mantine/hooks';
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useClient, useSession } from '../auth/session';
import { ACTIVE, FINAL } from '../lib/stages';
import { ApiError } from './client';
import type { EventInput, Explanation, Graph, PortfolioDraft, RunStatus, ScenarioParameter } from './types';

/** 409 means «not ready yet» for the report and the trace: an empty answer, not an error. */
async function unlessNotReady<T>(load: () => Promise<T>): Promise<T | null> {
  try {
    return await load();
  } catch (error) {
    if (error instanceof ApiError && error.status === 409) return null;
    throw error;
  }
}

export function useRuns() {
  const client = useClient();
  return useQuery({
    queryKey: ['runs', client.mode],
    queryFn: () => client.runs(),
    refetchInterval: (query) =>
      (query.state.data ?? []).some((row) => !FINAL.includes(row.status)) ? 4000 : 30000,
  });
}

export function useRunStatus(runId: string) {
  const client = useClient();
  return useQuery({
    queryKey: ['status', client.mode, runId],
    queryFn: () => client.status(runId),
    retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
    refetchInterval: (query) => {
      const state = query.state.data?.status;
      if (!state || FINAL.includes(state)) return false;
      return ACTIVE.includes(state) ? 1500 : 10000;
    },
  });
}

/** Everything a run produced so far; re-read whenever the run moves on. */
export function useArtifacts(status: RunStatus | undefined) {
  const client = useClient();
  return useQuery({
    queryKey: ['artifacts', client.mode, status?.run_id, status?.status, status?.node],
    queryFn: () => client.artifacts(status!.run_id),
    enabled: !!status,
    placeholderData: keepPreviousData,
  });
}

export function useReport(status: RunStatus, enabled: boolean) {
  const client = useClient();
  return useQuery({
    queryKey: ['report', client.mode, status.run_id, status.status],
    queryFn: () => unlessNotReady(() => client.report(status.run_id)),
    enabled,
  });
}

export function useTrace(status: RunStatus, enabled: boolean) {
  const client = useClient();
  return useQuery({
    queryKey: ['trace', client.mode, status.run_id, status.status],
    queryFn: () => unlessNotReady(() => client.trace(status.run_id)),
    enabled,
    staleTime: Infinity,
  });
}

/** LLM answers and MCP tool calls of the run; re-read while the run moves on. */
export function useActivity(status: RunStatus) {
  const client = useClient();
  return useQuery({
    queryKey: ['activity', client.mode, status.run_id, status.status, status.node, status.llm_waiting?.started_at],
    queryFn: () => client.activity(status.run_id),
    placeholderData: keepPreviousData,
  });
}

export interface ScenarioCheckInput {
  graph: Graph;
  parameters: Record<string, ScenarioParameter>;
  required: boolean;
  runId?: string;
}

/** The graph stop's verdict on a draft and the scenario's effect on sectors, while editing. */
export function useScenarioCheck(input: ScenarioCheckInput | null) {
  const client = useClient();
  const [text] = useDebouncedValue(input ? JSON.stringify(input) : '', 400);
  return useQuery({
    queryKey: ['scenario-check', client.mode, text],
    queryFn: () => {
      const { graph, parameters, required, runId } = JSON.parse(text) as ScenarioCheckInput;
      return client.scenarioCheck(graph, parameters, required, runId);
    },
    enabled: !!text,
    staleTime: Infinity,
    placeholderData: keepPreviousData,
  });
}

/** Questions about the run and their answers; re-read while one is being answered. */
export function useExplanations(runId: string) {
  const client = useClient();
  return useQuery({
    queryKey: ['explanations', client.mode, runId],
    queryFn: () => client.explanations(runId),
    refetchInterval: (query) =>
      (query.state.data ?? []).some((e) => e.status === 'queued' || e.status === 'running') ? 1500 : false,
  });
}

export function useExplain(runId: string) {
  const client = useClient();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (question: string) => client.explain(runId, question),
    onSuccess: (created) => {
      queryClient.setQueryData<Explanation[]>(['explanations', client.mode, runId], (items = []) => [...items, created]);
      queryClient.invalidateQueries({ queryKey: ['explanations', client.mode, runId] });
      queryClient.invalidateQueries({ queryKey: ['activity', client.mode, runId] });
    },
  });
}

export function useWorkflows() {
  const client = useClient();
  return useQuery({ queryKey: ['workflows'], queryFn: () => client.workflows(), staleTime: Infinity });
}

export function usePortfolios(enabled: boolean) {
  const client = useClient();
  return useQuery({ queryKey: ['portfolios', client.mode], queryFn: () => client.portfolios(), enabled });
}

export function usePortfolio(portfolioId: string | null, enabled: boolean) {
  const client = useClient();
  return useQuery({
    queryKey: ['portfolio', client.mode, portfolioId],
    queryFn: () => client.portfolio(portfolioId!),
    enabled: enabled && !!portfolioId,
  });
}

export function useCreatePortfolio() {
  const client = useClient();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (draft: PortfolioDraft) => client.createPortfolio(draft),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['portfolios'] }),
  });
}

export function useDeletePortfolio() {
  const client = useClient();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (portfolioId: string) => client.deletePortfolio(portfolioId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['portfolios'] }),
  });
}

export function useLibraryEvents(enabled: boolean) {
  const client = useClient();
  return useQuery({ queryKey: ['events'], queryFn: () => client.events(), enabled });
}

function useRefreshRun() {
  const queryClient = useQueryClient();
  const { mode } = useSession();
  return (runId: string) => {
    for (const key of ['status', 'artifacts', 'report', 'trace', 'activity']) {
      queryClient.invalidateQueries({ queryKey: [key, mode, runId] });
    }
    queryClient.invalidateQueries({ queryKey: ['runs', mode] });
  };
}

export interface StartInput {
  portfolioId: string;
  event: EventInput | { kind: 'file'; file: File };
  scenario: string | null;
  review: boolean;
  /** Agent plugins, off by default, that join this run. */
  agents?: string[];
  /** The provider's stronger model answers every call of this run. */
  strongModel?: boolean;
}

export function useStartRun() {
  const client = useClient();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ portfolioId, event, scenario, review, agents = [], strongModel = false }: StartInput) => {
      let input: EventInput;
      if (event.kind === 'file') {
        const document = await client.ingestFile(event.file);
        if (document.status === 'unparsed') {
          throw new ApiError(
            422,
            'Unparsed',
            'Из файла не удалось извлечь текст. Загрузите текстовую версию документа.',
          );
        }
        input = { kind: 'doc_id', doc_id: document.doc_id };
      } else {
        input = event;
      }
      return client.start(portfolioId, input, scenario, review, agents, strongModel);
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['runs'] }),
  });
}

export function useResumeGraph(runId: string) {
  const client = useClient();
  const refresh = useRefreshRun();
  return useMutation({
    mutationFn: ({ graph, parameters }: { graph: Graph; parameters?: Record<string, ScenarioParameter> }) =>
      client.resumeGraph(runId, graph, parameters),
    onSuccess: () => refresh(runId),
  });
}

export type ApprovalDecision = 'approve' | 'return' | 'reject';

export function useResumeApproval(runId: string) {
  const client = useClient();
  const refresh = useRefreshRun();
  return useMutation({
    mutationFn: ({ decision, reason }: { decision: ApprovalDecision; reason?: string }) =>
      client.resumeApproval(runId, decision === 'approve', decision === 'return', reason),
    onSuccess: () => refresh(runId),
  });
}
