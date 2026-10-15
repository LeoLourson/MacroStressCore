import type {
  Activity,
  Artifacts,
  Documentation,
  EventInput,
  Explanation,
  Graph,
  LibraryEvent,
  Me,
  Mode,
  PortfolioBundle,
  PortfolioDraft,
  PortfolioRow,
  Report,
  RunRow,
  RunStatus,
  ScenarioCheck,
  ScenarioParameter,
  SourceDocument,
  Trace,
  Violation,
  WorkflowView,
} from './types';

const STATUS_TEXT: Record<number, string> = {
  0: 'Сервис MacroStress недоступен. Проверьте, что он запущен.',
  401: 'Ключ доступа не принят: он неверен или истёк.',
  403: 'Недостаточно прав для этого действия.',
  404: 'Не найдено. Возможно, стресс-тест относится к другому контуру.',
  409: 'Состояние стресс-теста уже изменилось. Обновите страницу.',
  413: 'Слишком большой объём данных.',
  422: 'Данные не прошли проверку.',
  429: 'Слишком много запросов. Повторите немного позже.',
};

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly title: string,
    readonly detail: string,
    readonly violations: Violation[] = [],
  ) {
    super(`${status} ${title}: ${detail}`);
  }

  /** What a person should read; the technical detail is shown folded below it. */
  get userMessage(): string {
    if (this.status >= 500) return 'Ошибка на стороне сервиса. Повторите позже или сообщите администратору.';
    return STATUS_TEXT[this.status] ?? 'Сервис ответил неожиданно. Повторите действие позже.';
  }
}

/** An API path under the app's base: '/' locally, '/p/<token>/' behind a reverse proxy. */
export const apiUrl = (path: string) => import.meta.env.BASE_URL.replace(/\/$/, '') + path;

export interface UiConfig {
  demo_keys?: Record<string, string>;
}

/** A stalled link must not leave the sign-in page waiting forever. */
const CONFIG_TIMEOUT_MS = 10_000;

/**
 * The role presets of the stand. An unreachable service throws, so the sign-in page can say
 * so and offer a retry instead of silently demanding a key it does not need; an answer
 * without presets is a production stand, and there the key is the only way in.
 */
export async function fetchUiConfig(): Promise<UiConfig> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), CONFIG_TIMEOUT_MS);
  try {
    const response = await fetch(apiUrl('/v1/ui/config'), { signal: controller.signal });
    // An older stand may not know the endpoint at all: those keep the key form.
    if (!response.ok) return {};
    return (await response.json()) as UiConfig;
  } finally {
    clearTimeout(timer);
  }
}

export class ApiClient {
  constructor(
    readonly apiKey: string,
    readonly mode: Mode,
  ) {}

  /** The namespace prefix: /v1/demo/... for the demo namespace, /v1/... for production. */
  private get base_(): string {
    return this.mode === 'demo' ? '/v1/demo' : '/v1';
  }

  private get runs_(): string {
    return `${this.base_}/runs`;
  }

  private async call<T>(method: string, path: string, body?: unknown): Promise<T> {
    let response: Response;
    try {
      response = await fetch(apiUrl(path), {
        method,
        headers: {
          'X-API-Key': this.apiKey,
          ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
        },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch (error) {
      throw new ApiError(0, 'API unavailable', String(error));
    }
    if (response.ok) return (await response.json()) as T;
    if ((response.headers.get('content-type') ?? '').includes('application/problem+json')) {
      const problem = await response.json();
      throw new ApiError(
        problem.status ?? response.status,
        problem.title ?? '',
        problem.detail ?? '',
        problem.violations ?? [],
      );
    }
    throw new ApiError(response.status, 'HTTP error', await response.text());
  }

  me() {
    return this.call<Me>('GET', '/v1/me');
  }

  runs() {
    return this.call<RunRow[]>('GET', this.runs_);
  }

  /** The portfolios of the namespace: the bank's in production, demo and analysts' in demo. */
  portfolios() {
    return this.call<PortfolioRow[]>('GET', `${this.base_}/portfolios`);
  }

  portfolio(portfolioId: string) {
    return this.call<PortfolioBundle>('GET', `${this.base_}/portfolios/${encodeURIComponent(portfolioId)}`);
  }

  /** A data snapshot with its items (prices, statements, rates), as of its date. */
  snapshot(snapshotId: string) {
    return this.call<{
      snapshot_id: string;
      as_of: string;
      items: { kind: string; subject: string; observed_on: string; values: Record<string, { value: number }> }[];
    }>('GET', `${this.base_}/snapshots/${encodeURIComponent(snapshotId)}`);
  }

  portfolioNames(portfolioId: string) {
    return this.call<Record<string, string>>('GET', `/v1/demo/portfolios/${encodeURIComponent(portfolioId)}/names`);
  }

  /** A portfolio typed in the editor; kept for seven days in the demo namespace. */
  createPortfolio(draft: PortfolioDraft) {
    return this.call<{ portfolio_id: string; expires_at: string }>('POST', '/v1/demo/portfolios/draft', draft);
  }

  /** A stopped demo run with its results; production runs are not deleted. */
  async deleteRun(runId: string) {
    const response = await fetch(apiUrl(`/v1/demo/runs/${encodeURIComponent(runId)}`), {
      method: 'DELETE',
      headers: { 'X-API-Key': this.apiKey },
    });
    if (!response.ok) throw new ApiError(response.status, 'HTTP error', await response.text());
  }

  async deletePortfolio(portfolioId: string) {
    const response = await fetch(apiUrl(`/v1/demo/portfolios/${encodeURIComponent(portfolioId)}`), {
      method: 'DELETE',
      headers: { 'X-API-Key': this.apiKey },
    });
    if (!response.ok) throw new ApiError(response.status, 'HTTP error', await response.text());
  }

  events() {
    return this.call<LibraryEvent[]>('GET', '/v1/demo/events');
  }

  /** The workflows and the agent plugins that may join them (GET /v1/workflows). */
  workflows() {
    return this.call<WorkflowView[]>('GET', '/v1/workflows');
  }

  docs() {
    return this.call<Documentation>('GET', '/v1/docs');
  }

  start(
    portfolioId: string,
    event: EventInput,
    scenario: string | null,
    requestGraphReview: boolean,
    agents: string[] = [],
    strongModel = false,
  ) {
    return this.call<RunStatus>('POST', this.runs_, {
      portfolio_id: portfolioId,
      event,
      request_graph_review: requestGraphReview,
      ...(strongModel ? { strong_model: true } : {}),
      ...(agents.length ? { agents } : {}),
      ...(scenario ? { scenario } : {}),
    });
  }

  /** The event document parsed on the server; a run then refers to it by doc_id. */
  async ingestFile(file: File): Promise<SourceDocument> {
    const bytes = new Uint8Array(await file.arrayBuffer());
    let binary = '';
    for (let i = 0; i < bytes.length; i += 0x8000) {
      binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
    }
    return this.call<SourceDocument>('POST', `${this.base_}/documents`, {
      content_base64: btoa(binary),
      filename: file.name,
    });
  }

  status(runId: string) {
    return this.call<RunStatus>('GET', `${this.runs_}/${runId}`);
  }

  artifacts(runId: string) {
    return this.call<Artifacts>('GET', `${this.runs_}/${runId}/artifacts`);
  }

  report(runId: string) {
    return this.call<Report>('GET', `${this.runs_}/${runId}/report`);
  }

  trace(runId: string) {
    return this.call<Trace>('GET', `${this.runs_}/${runId}/trace`);
  }

  activity(runId: string) {
    return this.call<Activity>('GET', `${this.runs_}/${runId}/activity`);
  }

  explanations(runId: string) {
    return this.call<Explanation[]>('GET', `${this.runs_}/${runId}/explanations`);
  }

  /** A question about the calculated run; answered in the background. */
  explain(runId: string, question: string) {
    return this.call<Explanation>('POST', `${this.runs_}/${runId}/explanations`, { question });
  }

  scenarioCheck(graph: Graph, parameters: Record<string, ScenarioParameter>, required: boolean, runId?: string) {
    return this.call<ScenarioCheck>('POST', `${this.base_}/scenario-check`, {
      graph,
      macro_parameters: parameters,
      required,
      run_id: runId,
    });
  }

  resumeGraph(runId: string, graph: Graph, parameters?: Record<string, ScenarioParameter>) {
    return this.call<RunStatus>('POST', `${this.runs_}/${runId}/resume`, {
      graph,
      ...(parameters ? { macro_parameters: parameters } : {}),
    });
  }

  resumeApproval(runId: string, approved: boolean, returned = false, reason?: string) {
    return this.call<RunStatus>('POST', `${this.runs_}/${runId}/resume`, {
      approved,
      returned,
      ...(reason ? { reason } : {}),
    });
  }
}
