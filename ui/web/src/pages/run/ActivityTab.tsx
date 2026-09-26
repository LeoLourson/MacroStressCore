import { Badge, Center, Group, Loader, Paper, SimpleGrid, Stack, Table, Text, Title } from '@mantine/core';
import { IconCheck, IconX } from '@tabler/icons-react';
import { useActivity } from '../../api/queries';
import type { ActivityItem, WorkflowView } from '../../api/types';
import { useSession } from '../../auth/session';
import { ErrorAlert } from '../../components/ErrorAlert';
import { number, timestamp } from '../../lib/format';
import { PROVIDERS, label } from '../../lib/labels';
import type { RunTabProps } from './RunPage';

// What each MCP tool does, in words; the machine name stays beside it.
const TOOLS: Record<string, string> = {
  'mcp-models.run_model': 'Расчёт модели позиции',
  'mcp-models.list_models': 'Каталог моделей',
  'mcp-models.describe_model': 'Описание модели',
  'mcp-portfolio.resolve_inputs': 'Данные позиции из снимка',
  'mcp-portfolio.get_portfolio': 'Состав портфеля',
  'mcp-runs.get_run_summary': 'Сводка прогона',
  'mcp-runs.get_position_metrics': 'Показатели позиции',
  'mcp-runs.get_metric_provenance': 'Происхождение числа',
  'mcp-runs.describe_model': 'Описание модели',
};

const PURPOSES: Record<string, string> = {
  answer: 'ответ',
  repair: 'исправление ответа',
  tool_turn: 'шаг с инструментами',
};

const SCHEMAS: Record<string, string> = {
  CausalOutput: 'граф влияния и сценарий',
  AdvisoryNarrative: 'текст резюме отчёта',
  tools: 'объяснение результатов',
};

function seconds(ms: number | null | undefined): string {
  return ms == null ? '—' : `${number(ms / 1000, ms < 10000 ? 2 : 1)} с`;
}

function Outcome({ item }: { item: ActivityItem }) {
  const ok = item.status === 'completed';
  return (
    <Group gap={4} wrap="nowrap" c={ok ? 'dimmed' : 'dark.7'}>
      {ok ? <IconCheck size={14} /> : <IconX size={14} />}
      <Text size="sm" fw={ok ? 400 : 600}>
        {ok ? 'выполнен' : 'ошибка'}
      </Text>
    </Group>
  );
}

function node(item: ActivityItem, workflow: WorkflowView | null | undefined): string {
  const [head, branch] = (item.node ?? '').split('/', 2);
  if (head === 'explain') return 'Объяснение результатов';
  const labels = Object.fromEntries(
    (workflow?.stages ?? []).flatMap((stage) => stage.nodes.map((n) => [n.node, n.label])),
  );
  const name = labels[head] ?? head;
  return branch ? `${name}: ${branch}` : name;
}

/** Every LLM answer and MCP tool call of the run: who asked, what for, how long it took. */
export function ActivityTab({ status, artifacts }: RunTabProps) {
  const activity = useActivity(status);
  const { me } = useSession();
  if (activity.error) return <ErrorAlert error={activity.error} />;
  if (!activity.data) {
    return (
      <Center py="xl">
        <Loader />
      </Center>
    );
  }
  const { llm, tools, items } = activity.data;
  const provider = me?.llm;
  return (
    <Stack gap="lg">
      <Text size="sm" c="dimmed" maw="80ch">
        Языковая модель строит граф влияния со сценарием, может переписать резюме отчёта и отвечает на вопросы по
        результатам, читая их через инструменты. Числа считают детерминированные модели плагинов; агенты вызывают их и
        данные портфеля через MCP-инструменты. Каждый вызов записан в журнал аудита с узлом, попыткой и тем, кто его
        запросил: процесс или языковая модель.
      </Text>
      <SimpleGrid cols={{ base: 1, sm: 2 }}>
        <Paper p="md">
          <Stack gap={4}>
            <Title order={5}>Языковая модель</Title>
            <Text size="sm">
              {label(PROVIDERS, provider?.provider)}
              {provider?.model && provider.provider !== 'mock' ? ` · ${provider.model}` : ''}
              {provider?.external ? ' · внешняя, только демо-данные' : ''}
            </Text>
            <Text size="sm">
              Ответов: <b>{llm.calls}</b>
              {llm.failed ? `, из них с ошибкой ${llm.failed}` : ''} · время {seconds(llm.duration_ms)}
            </Text>
            <Text size="sm">
              Токены: запрос {number(llm.prompt_tokens, 0)}, ответ {number(llm.completion_tokens, 0)}
            </Text>
          </Stack>
        </Paper>
        <Paper p="md">
          <Stack gap={4}>
            <Title order={5}>Инструменты MCP</Title>
            <Text size="sm">
              Вызовов: <b>{tools.calls}</b>
              {tools.failed ? `, из них с ошибкой ${tools.failed}` : ''} · время {seconds(tools.duration_ms)}
            </Text>
            {!!tools.by_llm && (
              <Text size="sm">
                По выбору языковой модели: <b>{tools.by_llm}</b>
              </Text>
            )}
            <Text size="sm" c="dimmed">
              mcp-portfolio — данные позиций из снимка, mcp-models — расчёт позиции, mcp-runs — чтение результатов для
              объяснения.
            </Text>
          </Stack>
        </Paper>
      </SimpleGrid>
      {items.length === 0 ? (
        <Text size="sm" c="dimmed">
          Вызовов пока не было.
        </Text>
      ) : (
        <Paper>
          <Table.ScrollContainer minWidth={900}>
            <Table fz="sm" verticalSpacing="xs">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Время</Table.Th>
                  <Table.Th>Кто</Table.Th>
                  <Table.Th>Этап</Table.Th>
                  <Table.Th>Что</Table.Th>
                  <Table.Th className="num-right">Длительность</Table.Th>
                  <Table.Th className="num-right">Токены</Table.Th>
                  <Table.Th>Итог</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {items.map((item, index) => {
                  const d = item.details;
                  const llmCall = item.kind === 'llm';
                  return (
                    <Table.Tr key={index}>
                      <Table.Td style={{ whiteSpace: 'nowrap' }}>{timestamp(item.at)}</Table.Td>
                      <Table.Td>
                        <Badge variant="light" color={llmCall ? 'steel' : 'gray'} tt="none" fw={500}>
                          {llmCall ? 'LLM' : 'MCP'}
                        </Badge>
                        {!llmCall && item.initiator === 'llm' && (
                          <Text size="xs" c="dimmed">
                            выбор LLM
                          </Text>
                        )}
                      </Table.Td>
                      <Table.Td>
                        {node(item, artifacts.workflow)}
                        {/* Only the causal agent retries; elsewhere the journal number counts graph confirmations. */}
                        {item.node === 'causal_agent' && item.attempt && item.attempt > 1 ? `, попытка ${item.attempt}` : ''}
                      </Table.Td>
                      <Table.Td>
                        {llmCall ? (
                          <>
                            {label(SCHEMAS, d.schema)} · {label(PURPOSES, d.purpose)}
                            <Text size="xs" c="dimmed" ff="monospace">
                              {d.model}
                            </Text>
                          </>
                        ) : (
                          <>
                            {TOOLS[item.name ?? ''] ?? item.name}
                            <Text size="xs" c="dimmed" ff="monospace">
                              {item.name}
                            </Text>
                          </>
                        )}
                        {d.error && (
                          <Text size="xs" c="dark.6">
                            {d.error}
                          </Text>
                        )}
                      </Table.Td>
                      <Table.Td className="num-right">{seconds(d.duration_ms)}</Table.Td>
                      <Table.Td className="num-right">
                        {llmCall && d.prompt_tokens != null
                          ? `${number(d.prompt_tokens, 0)} → ${number(d.completion_tokens, 0)}`
                          : '—'}
                        {llmCall && d.reasoning_tokens ? (
                          <Text size="xs" c="dimmed">
                            рассуждение {number(d.reasoning_tokens, 0)}
                          </Text>
                        ) : null}
                      </Table.Td>
                      <Table.Td>
                        <Outcome item={item} />
                      </Table.Td>
                    </Table.Tr>
                  );
                })}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        </Paper>
      )}
    </Stack>
  );
}
