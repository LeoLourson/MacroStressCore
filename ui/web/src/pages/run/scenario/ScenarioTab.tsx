import {
  ActionIcon,
  Alert,
  Anchor,
  Badge,
  Button,
  Group,
  List,
  Menu,
  Modal,
  Paper,
  Stack,
  Table,
  Text,
  Textarea,
  Title,
  Tooltip,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import {
  IconAlertTriangle,
  IconArrowBackUp,
  IconCheck,
  IconDots,
  IconInfoCircle,
  IconMessageReport,
  IconPencil,
  IconPlayerPlay,
  IconPlus,
} from '@tabler/icons-react';
import { useMemo, useState } from 'react';
import { ApiError } from '../../../api/client';
import { useResumeGraph, useScenarioCheck } from '../../../api/queries';
import type {
  Artifacts,
  FixGraphStop,
  Graph,
  RunStatus,
  ScenarioParameter,
  ScenarioPlan,
  SourceDocument,
  Violation,
} from '../../../api/types';
import { canFixGraph, useSession } from '../../../auth/session';
import { ErrorAlert } from '../../../components/ErrorAlert';
import { Term } from '../../../components/Term';
import { day, elasticityText, metricValue, nodeLabels, number, plural, scenarioValue } from '../../../lib/format';
import { factorLabel } from '../../../api/catalog';
import { PASSPORT } from '../../../lib/labels';
import { ACTIVE, stopOf } from '../../../lib/stages';
import type { RunTabProps } from '../RunPage';
import { EdgeDrawer, fragmentText } from './EdgeDrawer';
import { edgeCaption, GraphCanvas } from './GraphCanvas';
import { channelsOf, newParameter, ParameterModal } from './ParameterModal';
import { edgeFlagged, edgeIndex, failing, gateWords, parameterProblem, problemText, split } from './problems';
import { useDraft, type Draft } from './useDraft';

function quote(evidence: ScenarioParameter['evidence'] | undefined, document: SourceDocument | null | undefined) {
  const assumption = evidence?.find((e) => e.kind === 'expert_assumption');
  if (assumption) return `Допущение · ${assumption.author ?? 'автор не указан'}${assumption.as_of ? ` · ${day(assumption.as_of)}` : ''}`;
  // The words about strength are quoted once above the table; each row only points to them.
  if (evidence?.some((e) => e.locator === 'scenario')) return 'из описания силы события';
  for (const item of evidence ?? []) {
    const text = fragmentText(item, document);
    if (text) return text.length > 140 ? `«${text.slice(0, 140)}…»` : `«${text}»`;
  }
  return '—';
}

function Understanding({ plan, document }: { plan: ScenarioPlan; document: SourceDocument | null | undefined }) {
  const passport = plan.passport ?? {};
  const facts = Object.entries(PASSPORT)
    .filter(([key]) => passport[key as keyof typeof passport])
    .map(([key, name]) => {
      const value = passport[key as keyof typeof passport] as string;
      return `${name}: ${key === 'effective_date' ? day(value) : value}`;
    });
  const numbers = Object.values(plan.numbers ?? {});
  if (!facts.length && !numbers.length) return null;
  return (
    <Stack gap="xs">
      <Title order={4}>Что система поняла из текста</Title>
      {facts.length > 0 && <Text size="sm">{facts.join(' · ')}</Text>}
      {numbers.length > 0 && (
        <Table withTableBorder fz="sm">
          <Table.Thead>
            <Table.Tr>
              <Table.Th w={160}>Число</Table.Th>
              <Table.Th>Где сказано</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {numbers.map((item, i) => (
              <Table.Tr key={i}>
                <Table.Td className="num">{metricValue(item.value, item.unit)}</Table.Td>
                <Table.Td>{quote(item.evidence, document)}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
    </Stack>
  );
}

function Gate({
  stop,
  plan,
  changed,
  violations,
  graph,
  parameters,
  onEdge,
}: {
  stop: FixGraphStop;
  plan: ScenarioPlan;
  changed: boolean;
  violations: Violation[];
  graph: Graph | null;
  parameters: Record<string, ScenarioParameter>;
  onEdge: (index: number) => void;
}) {
  const { graph: graphProblems, scenario: scenarioProblems } = split(violations);
  const words = gateWords(stop, plan, changed, graphProblems, scenarioProblems);
  const color = words.tone === 'problem' ? 'orange' : words.tone === 'task' ? 'yellow' : 'steel';
  const icon =
    words.tone === 'problem' ? <IconAlertTriangle /> : words.tone === 'task' ? <IconMessageReport /> : <IconInfoCircle />;
  return (
    <Alert color={color} variant="light" icon={icon} title={words.title} styles={{ title: { fontSize: 'var(--mantine-font-size-md)' } }}>
      <Stack gap="xs">
        <Text size="sm">{words.text}</Text>
        {violations.length > 0 && (
          <List size="sm" spacing={4}>
            {graphProblems.map((v, i) => {
              const index = edgeIndex(v.path);
              const text = problemText(v, graph);
              return (
                <List.Item key={`g${i}`}>
                  {index != null && graph?.edges[index] ? (
                    <Anchor component="button" type="button" size="sm" onClick={() => onEdge(index)}>
                      {text}
                    </Anchor>
                  ) : (
                    text
                  )}
                </List.Item>
              );
            })}
            {scenarioProblems.map((v, i) => (
              <List.Item key={`s${i}`}>{parameterProblem(v, parameters)}</List.Item>
            ))}
          </List>
        )}
      </Stack>
    </Alert>
  );
}

function ScenarioTable({
  plan,
  parameters,
  graph,
  document,
  editing,
  pending,
  onEdit,
  onAdd,
}: {
  plan: ScenarioPlan;
  parameters: Record<string, ScenarioParameter>;
  graph: Graph | null;
  document: SourceDocument | null | undefined;
  editing: boolean;
  /** The model has not answered yet: there is nothing to judge. */
  pending: boolean;
  onEdit: (name: string) => void;
  onAdd: () => void;
}) {
  const channels = channelsOf(graph);
  const entries = Object.entries(parameters);
  return (
    <Stack gap="xs">
      <Group justify="space-between">
        <Stack gap={0}>
          <Title order={4}>Сценарий: насколько сильным может быть событие</Title>
          <Text size="sm" c="dimmed">
            По этим диапазонам строятся тысячи сценариев{' '}
            <Term name="Монте-Карло">Монте-Карло</Term>, одинаковых для всех позиций.
          </Text>
        </Stack>
        {editing && graph?.nodes.length ? (
          <Button variant="light" size="xs" leftSection={<IconPlus size={14} />} onClick={onAdd}>
            Добавить параметр
          </Button>
        ) : null}
      </Group>
      {plan.text && (
        <Text size="sm" c="dimmed">
          Как описали при запуске: «{plan.text.split(/\s+/).join(' ')}»
        </Text>
      )}
      {entries.length === 0 && pending ? (
        <Text size="sm" c="dimmed">
          Параметры появятся, когда модель разберёт событие.
        </Text>
      ) : entries.length === 0 ? (
        <Alert color="gray" variant="light">
          {plan.text
            ? 'Сценарий не задан: модель не извлекла параметры из описания силы события.'
            : 'Сценарий не задан: при запуске не описали силу события.'}
          {editing ? ' Добавьте параметры вручную.' : ''}
        </Alert>
      ) : (
        <Table.ScrollContainer minWidth={720}>
          <Table withTableBorder verticalSpacing="xs" fz="sm">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Параметр</Table.Th>
                <Table.Th>Значение</Table.Th>
                <Table.Th>Канал графа или ключ</Table.Th>
                <Table.Th>Фактор</Table.Th>
                <Table.Th>Из текста</Table.Th>
                {editing && <Table.Th w={48} />}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {entries.map(([name, p]) => (
                <Table.Tr key={name}>
                  <Table.Td fw={500}>{p.label}</Table.Td>
                  <Table.Td>{scenarioValue(p)}</Table.Td>
                  <Table.Td>
                    {p.channel
                      ? (channels[p.channel] ?? p.channel)
                      : p.key
                        ? `напрямую: ${p.key}`
                        : '— (заменяет входное значение модели)'}
                  </Table.Td>
                  <Table.Td>{p.factor ? factorLabel(p.factor) : '—'}</Table.Td>
                  <Table.Td c="dimmed">{quote(p.evidence, document)}</Table.Td>
                  {editing && (
                    <Table.Td>
                      <Tooltip label="Изменить">
                        <ActionIcon variant="subtle" onClick={() => onEdit(name)} aria-label={`Изменить ${p.label}`}>
                          <IconPencil size={16} />
                        </ActionIcon>
                      </Tooltip>
                    </Table.Td>
                  )}
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
    </Stack>
  );
}

function Effects({ effects }: { effects: { label: string; sector: string; okved: string; factor: string; shock: number; unit: string }[] }) {
  if (!effects.length) return null;
  return (
    <Stack gap="xs">
      <Title order={5}>Влияние на отрасли в центральном сценарии</Title>
      <Text size="sm" c="dimmed">
        Значение параметра, пересчитанное через связи графа. Расчёт по позициям разыгрывает весь диапазон.
      </Text>
      <Table withTableBorder fz="sm">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Параметр</Table.Th>
            <Table.Th>Отрасль</Table.Th>
            <Table.Th>Фактор</Table.Th>
            <Table.Th className="num-right">Изменение</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {effects.map((e, i) => (
            <Table.Tr key={i}>
              <Table.Td>{e.label}</Table.Td>
              <Table.Td>
                {e.sector} <Text span c="dimmed" size="xs">({e.okved})</Text>
              </Table.Td>
              <Table.Td>{factorLabel(e.factor)}</Table.Td>
              <Table.Td className="num-right">
                {e.shock >= 0 ? '+' : ''}
                {e.unit === 'fraction' ? `${number(e.shock * 100, 1)} %` : `${number(e.shock, 0)} дн.`}
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Stack>
  );
}

function EdgesTable({ graph, flagged, onSelect }: { graph: Graph; flagged: Set<number>; onSelect: (i: number) => void }) {
  const names = nodeLabels(graph);
  return (
    <Stack gap="xs">
      <Title order={5}>Связи и их источники</Title>
      <Table.ScrollContainer minWidth={720}>
        <Table withTableBorder highlightOnHover fz="sm">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Связь</Table.Th>
              <Table.Th>Знак, сила, задержка</Table.Th>
              <Table.Th className="num-right">Источников</Table.Th>
              <Table.Th w={130}>Проверка</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {graph.edges.map((edge, i) => (
              <Table.Tr key={i} className="clickable-row" onClick={() => onSelect(i)}>
                <Table.Td>
                  {names[edge.src] ?? edge.src} → {names[edge.dst] ?? edge.dst}
                </Table.Td>
                <Table.Td className="num">{edgeCaption(edge.sign, elasticityText(edge.elasticity), edge.lag_months)}</Table.Td>
                <Table.Td className="num-right">{edge.evidence.length}</Table.Td>
                <Table.Td>
                  {flagged.has(i) ? (
                    <Badge color="orange" c="orange.9" variant="light" tt="none" leftSection={<IconAlertTriangle size={12} />}>
                      есть проблема
                    </Badge>
                  ) : (
                    <Text size="sm" c="dimmed">
                      в порядке
                    </Text>
                  )}
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    </Stack>
  );
}

function JsonReplace({ opened, onClose, onLoad }: { opened: boolean; onClose: () => void; onLoad: (g: Graph) => void }) {
  const [text, setText] = useState('');
  const [error, setError] = useState<string | null>(null);
  const load = () => {
    try {
      const graph = JSON.parse(text);
      if (!graph || typeof graph !== 'object' || !Array.isArray(graph.nodes) || !Array.isArray(graph.edges)) {
        setError('Ожидается объект графа с полями nodes и edges.');
        return;
      }
      onLoad(graph as Graph);
      setText('');
      setError(null);
      onClose();
    } catch (e) {
      setError(`Это не JSON: ${(e as Error).message}`);
    }
  };
  return (
    <Modal opened={opened} onClose={onClose} title="Заменить граф целиком" size="xl">
      <Stack>
        <Text size="sm" c="dimmed">
          Для случаев, когда граф проще подготовить во внешнем редакторе. Граф попадёт в черновик и будет проверен.
        </Text>
        <Textarea autosize minRows={10} maxRows={24} ff="monospace" value={text} onChange={(e) => setText(e.currentTarget.value)} />
        {error && <Text c="orange.9" size="sm">{error}</Text>}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            Отмена
          </Button>
          <Button onClick={load} disabled={!text.trim()}>
            Загрузить в черновик
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

function Body({
  status,
  artifacts,
  stop,
  draft,
}: {
  status: RunStatus;
  artifacts: Artifacts;
  stop: FixGraphStop | null;
  draft: Draft | null;
}) {
  const { me } = useSession();
  const plan = artifacts.scenario ?? {};
  const document = artifacts.document;
  const graph = draft ? draft.graph : (artifacts.graph ?? stop?.graph ?? null);
  const parameters = draft ? draft.parameters : (plan.parameters ?? {});
  const hasGraph = !!graph?.nodes?.length;
  const check = useScenarioCheck(
    hasGraph && (draft || Object.keys(parameters).length)
      ? { graph: graph!, parameters, required: !!stop?.scenario_required, runId: status.run_id }
      : null,
  );
  const resume = useResumeGraph(status.run_id);
  const [refused, setRefused] = useState<Violation[] | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [editingName, setEditingName] = useState<string | null>(null);
  const [newOne, setNewOne] = useState<[string, ScenarioParameter] | null>(null);
  const [jsonOpen, setJsonOpen] = useState(false);

  const violations = useMemo(() => {
    if (refused) return refused;
    if (draft?.changed) return check.data?.violations ?? [];
    return failing(stop?.violations);
  }, [refused, draft?.changed, check.data, stop]);
  const { graph: graphProblems } = split(violations);
  const flagged = useMemo(
    () =>
      new Set(
        (graph?.edges ?? []).flatMap((edge, i) => (edgeFlagged(i, edge, graphProblems) ? [i] : [])),
      ),
    [graph, graphProblems],
  );
  const factors = check.data?.factors ?? {};

  const updateGraph = (next: Graph) => {
    setRefused(null);
    draft?.setGraph(next);
  };
  const updateParameters = (next: Record<string, ScenarioParameter>) => {
    setRefused(null);
    draft?.setParameters(next);
  };

  const confirm = () => {
    if (!draft) return;
    resume.mutate(
      { graph: draft.graph, parameters: draft.parameters },
      {
        onSuccess: () => {
          draft.discard();
          notifications.show({ message: 'Подтверждено: расчёт по позициям продолжен', color: 'teal' });
        },
        onError: (error) => {
          if (error instanceof ApiError && error.status === 422) setRefused(failing(error.violations.map((v) => ({ ...v, ok: false }))));
        },
      },
    );
  };

  const modalName = newOne ? newOne[0] : editingName;
  const modalParameter = newOne ? newOne[1] : editingName ? parameters[editingName] : null;
  const blocking = violations.length > 0;

  return (
    <Stack gap="xl" pb={draft ? 96 : 0}>
      {stop && (
        <Gate
          stop={stop}
          plan={plan}
          changed={!!draft?.changed}
          violations={violations}
          graph={graph}
          parameters={parameters}
          onEdge={setSelected}
        />
      )}

      <Understanding plan={plan} document={document} />

      <Paper p="lg">
        <Stack gap="lg">
          <ScenarioTable
            plan={plan}
            parameters={parameters}
            graph={graph}
            document={document}
            editing={!!draft}
            pending={!hasGraph && ACTIVE.includes(status.status)}
            onEdit={setEditingName}
            onAdd={() => graph && setNewOne(newParameter(parameters, graph, factors))}
          />
          <Effects effects={check.data?.effects ?? []} />
          {!draft && plan.confirmed && (
            <Text size="sm" c="dimmed">
              Сценарий подтверждён аналитиком.
            </Text>
          )}
        </Stack>
      </Paper>

      <Paper p="lg">
        <Stack gap="md">
          <Group justify="space-between">
            <Stack gap={0}>
              <Title order={4}>Граф влияния</Title>
              <Text size="sm" c="dimmed">
                Как событие передаётся на финансы компаний портфеля: через каналы влияния на отрасли и их
                показатели.
              </Text>
            </Stack>
            {draft && (
              <Menu position="bottom-end">
                <Menu.Target>
                  <ActionIcon variant="subtle" color="gray" aria-label="Дополнительно">
                    <IconDots size={18} />
                  </ActionIcon>
                </Menu.Target>
                <Menu.Dropdown>
                  <Menu.Item onClick={() => setJsonOpen(true)}>Заменить граф из JSON</Menu.Item>
                </Menu.Dropdown>
              </Menu>
            )}
          </Group>
          {hasGraph ? (
            <>
              <GraphCanvas graph={graph!} flagged={flagged} selected={selected} onSelect={setSelected} />
              <EdgesTable graph={graph!} flagged={flagged} onSelect={setSelected} />
            </>
          ) : draft ? (
            <Alert color="orange" variant="light" title="Модель не смогла построить граф">
              <Stack gap="xs">
                <Text size="sm">
                  Загрузите граф вручную или запустите стресс-тест заново с уточнённым текстом события.
                </Text>
                <Button variant="light" w="fit-content" onClick={() => setJsonOpen(true)}>
                  Загрузить граф из JSON
                </Button>
              </Stack>
            </Alert>
          ) : (
            <Text c="dimmed">
              {['queued', 'running'].includes(status.status) ? 'Граф строится…' : 'Граф не построен.'}
            </Text>
          )}
        </Stack>
      </Paper>

      {graph && (
        <EdgeDrawer
          graph={graph}
          index={selected}
          document={document}
          problems={selected == null ? [] : graphProblems.filter((v) => edgeIndex(v.path) === selected)}
          editing={!!draft}
          author={me?.actor ?? ''}
          onClose={() => setSelected(null)}
          onChange={(edge) => {
            if (selected == null) return;
            updateGraph({ ...graph, edges: graph.edges.map((e, i) => (i === selected ? edge : e)) });
          }}
          onRemove={() => {
            if (selected == null) return;
            updateGraph({ ...graph, edges: graph.edges.filter((_, i) => i !== selected) });
            setSelected(null);
          }}
        />
      )}
      {graph && (
        <ParameterModal
          name={modalName}
          parameter={modalParameter ?? null}
          graph={graph}
          factors={factors}
          onClose={() => {
            setEditingName(null);
            setNewOne(null);
          }}
          onSave={(p) => {
            if (modalName) updateParameters({ ...parameters, [modalName]: p });
            setEditingName(null);
            setNewOne(null);
          }}
          onDelete={() => {
            if (modalName) {
              const next = { ...parameters };
              delete next[modalName];
              updateParameters(next);
            }
            setEditingName(null);
            setNewOne(null);
          }}
        />
      )}
      <JsonReplace opened={jsonOpen} onClose={() => setJsonOpen(false)} onLoad={updateGraph} />

      {draft && (
        <Paper
          p="md"
          shadow="md"
          style={{ position: 'sticky', bottom: 16, zIndex: 20, borderColor: 'var(--mantine-color-gray-4)' }}
        >
          <Stack gap="xs">
            {resume.error && !(resume.error instanceof ApiError && resume.error.status === 422) && (
              <ErrorAlert error={resume.error} />
            )}
            <Group justify="space-between">
              <Text size="sm" c={blocking ? 'orange.9' : 'dimmed'}>
                {blocking
                  ? `${plural(violations.length, 'проблема мешает', 'проблемы мешают', 'проблем мешают')} продолжить`
                  : draft.changed
                    ? check.isFetching
                      ? 'Проверяем правки…'
                      : 'Правки проверены и ещё не отправлены'
                    : 'Правок нет: граф и сценарий будут приняты как есть'}
              </Text>
              <Group>
                {draft.changed && (
                  <Button variant="default" leftSection={<IconArrowBackUp size={16} />} onClick={() => { setRefused(null); draft.reset(); }}>
                    Сбросить правки
                  </Button>
                )}
                <Button
                  leftSection={draft.changed ? <IconPlayerPlay size={16} /> : <IconCheck size={16} />}
                  onClick={confirm}
                  loading={resume.isPending}
                  disabled={blocking}
                >
                  {draft.changed ? 'Подтвердить правки и продолжить' : 'Подтвердить как есть'}
                </Button>
              </Group>
            </Group>
          </Stack>
        </Paper>
      )}
    </Stack>
  );
}

function Editor({ status, artifacts, stop, interruptId }: RunTabProps & { stop: FixGraphStop; interruptId: string }) {
  const initial = useMemo(
    () => ({
      graph: (artifacts.graph ?? stop.graph ?? { event_id: 'event', nodes: [], edges: [], factor_elasticity: {} }) as Graph,
      parameters: (stop.macro_parameters ?? artifacts.scenario?.parameters ?? {}) as Record<string, ScenarioParameter>,
    }),
    [artifacts.graph, artifacts.scenario?.parameters, stop],
  );
  const draft = useDraft(status.run_id, interruptId, initial);
  return <Body status={status} artifacts={artifacts} stop={stop} draft={draft} />;
}

export function ScenarioTab({ status, artifacts }: RunTabProps) {
  const { me } = useSession();
  const stop = stopOf(status);
  const interrupt = status.pending_interrupt?.[0];
  if (status.status === 'human_fix_graph' && stop && interrupt && canFixGraph(me)) {
    return <Editor key={interrupt.id} status={status} artifacts={artifacts} stop={stop} interruptId={interrupt.id} />;
  }
  return <Body status={status} artifacts={artifacts} stop={stop} draft={null} />;
}
