import { Alert, Badge, Button, Center, CopyButton, Group, List, Loader, Paper, Select, Stack, Text, Textarea, Title } from '@mantine/core';
import { IconCheck, IconCopy, IconRefresh, IconSend } from '@tabler/icons-react';
import { Fragment, useRef, useState, type ReactNode } from 'react';
import { useExplain, useExplanations } from '../../api/queries';
import type { Explanation } from '../../api/types';
import { ErrorAlert } from '../../components/ErrorAlert';
import { FieldHelp } from '../../components/FieldHelp';
import { TracedNumber } from '../../components/Provenance';
import { describePath, timestamp } from '../../lib/format';
import { blocks, runs } from './ReportText';
import type { RunTabProps } from './RunPage';
import { useOrigins } from './useOrigins';

const REASONS: Record<string, string> = {
  tool_calling_unsupported: 'Подключённая модель не поддерживает чтение данных расчёта.',
  round_limit: 'Не удалось подготовить полный ответ за отведённое число шагов.',
  unverified_numbers: 'Ответ модели не прошёл проверку чисел.',
  llm_failed: 'Модель временно недоступна.',
};
const PATH = /\[(\/(?:positions|portfolio)\/[^\]]+)\]/g;

/** Small safe Markdown renderer; references remain linked to the recorded calculation. */
function AnswerText({ text, artifacts, status }: { text: string } & RunTabProps) {
  const { entries } = useOrigins(status);
  const types = Object.fromEntries((artifacts.results ?? []).map((r) => [r.position_id, r.instrument_type]));
  const inline = (text: string): ReactNode => {
    const parts: ReactNode[] = [];
    const styled = (value: string) => runs(value).map((run, i) => run.bold
      ? <strong key={i}>{run.text}</strong> : run.code ? <code key={i}>{run.text}</code> : <Fragment key={i}>{run.text}</Fragment>);
    let at = 0;
    for (const match of text.matchAll(PATH)) {
      parts.push(<Fragment key={`text-${at}`}>{styled(text.slice(at, match.index))}</Fragment>);
      const entry = entries.get(match[1]);
      const label = describePath(match[1], { names: artifacts.position_names, types });
      parts.push(<TracedNumber key={`ref-${match.index}`} entry={entry}><span className="answer-reference">{label}{entry ? '' : ' (источник в показателях расчёта)'}</span></TracedNumber>);
      at = match.index + match[0].length;
    }
    parts.push(<Fragment key={`text-${at}`}>{styled(text.slice(at))}</Fragment>);
    return parts;
  };
  return <div className="prose answer-prose">{blocks(text).map((block, index) => block.kind === 'h'
    ? <h3 key={index}>{inline(block.text)}</h3>
    : block.kind === 'ul' ? <ul key={index}>{block.items.map((item, i) => <li key={i}>{inline(item)}</li>)}</ul>
      : <p key={index}>{inline(block.text)}</p>)}</div>;
}

function Answer({ item, onRetry, busy, ...props }: { item: Explanation; onRetry: (question: string) => void; busy: boolean } & RunTabProps) {
  const answer = item.answer;
  const pending = item.status === 'queued' || item.status === 'running';
  return (
    <Paper component="article" p={{ base: 'md', sm: 'lg' }} className="explanation-item" aria-label={item.question}>
      <Stack gap="md">
        <Group justify="space-between" align="flex-start" wrap="wrap">
          <Stack gap={4} style={{ flex: 1, minWidth: 0 }}>
            <Text fw={600} className="question-text">{item.question}</Text>
            <Text size="xs" c="dimmed">{item.created_by} · {timestamp(item.created_at)}</Text>
          </Stack>
          {answer && <CopyButton value={answer.text}>{({ copied, copy }) => (
            <Button variant="subtle" size="compact-sm" onClick={copy} leftSection={copied ? <IconCheck size={15} /> : <IconCopy size={15} />}>
              {copied ? 'Скопировано' : 'Копировать'}
            </Button>
          )}</CopyButton>}
        </Group>
        {pending && <Group gap="sm" role="status" aria-live="polite">
          <Loader size="xs" />
          <Text size="sm" c="dimmed">{item.status === 'queued' ? 'Вопрос принят. Ожидаем начала обработки…' : 'Изучаем результаты и проверяем числа…'}</Text>
        </Group>}
        {item.status === 'failed' && <Alert color="orange" title="Не удалось подготовить ответ">
          <Stack gap="sm">
            <Text size="sm">Повторите запрос. Текст вопроса сохранён.</Text>
            <Button variant="default" size="sm" w="fit-content" leftSection={<IconRefresh size={15} />} onClick={() => onRetry(item.question)} disabled={busy}>Повторить вопрос</Button>
            {item.error && <details className="answer-details"><summary>Технические сведения</summary><Text size="xs" mt="xs">{item.error}</Text></details>}
          </Stack>
        </Alert>}
        {answer && <>
          {answer.mode === 'structured' && <Alert variant="light" color="gray" title="Доступна сводка вместо ответа">
            <Text size="sm">{REASONS[(answer.fallback_reason ?? '').split(':')[0]] ?? 'Не удалось сформировать ответ на вопрос.'} Ниже — сохранённые результаты стресс-теста.</Text>
          </Alert>}
          {answer.mode === 'llm' ? <AnswerText text={answer.text} {...props} /> : <Stack gap="md">
            {answer.sections.map((section, index) => <Stack key={index} gap={6}>
              <Title order={5}>{section.title}</Title>
              <List size="sm" spacing={6}>{section.lines.map((line, i) => <List.Item key={i}>{line}</List.Item>)}</List>
            </Stack>)}
            <Button variant="subtle" size="sm" w="fit-content" leftSection={<IconRefresh size={15} />} onClick={() => onRetry(item.question)} disabled={busy}>Попробовать получить ответ</Button>
          </Stack>}
          <Group justify="space-between" gap="sm">
            <Badge variant="light" color={answer.mode === 'llm' ? 'teal' : 'gray'} tt="none" fw={500}>
              {answer.mode === 'llm' ? 'Числа сверены с расчётом' : 'Сводка из данных расчёта'}
            </Badge>
          </Group>
          {!!answer.tool_calls.length && <details className="answer-details">
            <summary>Источники ответа и проверка</summary>
            <Stack gap="xs" mt="sm">
              <Text size="xs" c="dimmed">Проверено чисел: {answer.numbers.length}. Обращений к данным: {answer.tool_calls.length}.</Text>
              {answer.tool_calls.map((call) => <Text size="xs" key={call.call_id}>
                {({ get_run_summary: 'Сводка стресс-теста', get_position_metrics: 'Показатели позиции', get_metric_provenance: 'Происхождение показателя', describe_model: 'Описание модели' } as Record<string, string>)[call.name.split('.').at(-1)!] ?? call.name}
                {typeof call.arguments.position_id === 'string' ? ` · ${call.arguments.position_id}` : ''}{call.ok ? '' : ' — данные не получены'}
              </Text>)}
            </Stack>
          </details>}
        </>}
      </Stack>
    </Paper>
  );
}

export function ExplainTab(props: RunTabProps) {
  const { status, artifacts } = props;
  const list = useExplanations(status.run_id);
  const ask = useExplain(status.run_id);
  const [question, setQuestion] = useState('');
  const [position, setPosition] = useState<string | null>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const sending = useRef(false);
  const items = [...(list.data ?? [])].sort((a, b) => b.created_at.localeCompare(a.created_at));
  const waiting = items.some((item) => item.status === 'queued' || item.status === 'running');
  const busy = ask.isPending || waiting;
  const results = artifacts.results ?? [];
  const ready = results.length > 0;
  const names = artifacts.position_names ?? {};
  const send = (text: string, draft?: string) => {
    if (!text.trim() || busy || sending.current || !ready || text.length > 2000) return;
    sending.current = true;
    ask.mutate(text, {
      onSuccess: () => { if (draft != null) setQuestion((current) => current === draft ? '' : current); },
      onSettled: () => { sending.current = false; },
    });
  };
  const prefix = position ? `По позиции ${names[position] ?? position} (${position}): ` : '';
  const message = prefix + question.trim();
  const examples = [
    'Что сильнее всего влияет на результат портфеля?',
    'Какой сценарий приводит к наибольшим потерям?',
    results.some((r) => r.execution !== 'completed') ? 'Какие позиции не рассчитаны и чего не хватает?' : 'На каких допущениях основан расчёт?',
  ];
  return (
    <Stack gap="lg" maw={920}>
      <Stack gap={6}>
        <Title order={3}>Разбор результатов</Title>
        <Text size="sm" c="dimmed" maw="72ch">Спросите о причинах потерь, конкретной позиции или допущениях. Ответ использует данные этого стресс-теста; числа проходят проверку.</Text>
      </Stack>
      <Paper component="form" p={{ base: 'md', sm: 'lg' }} onSubmit={(event) => { event.preventDefault(); send(message, question); }}>
        <Stack gap="md">
          <Select label={<FieldHelp label="Что разобрать" help="Выберите весь портфель или отдельную позицию. Каждый вопрос рассматривается отдельно с данными этого стресс-теста." />}
            data={[{ value: '__portfolio__', label: 'Весь портфель' }, ...(artifacts.positions ?? []).map((p) => ({ value: p.position.position_id, label: `${names[p.position.position_id] ?? p.instrument.name} · ${p.position.position_id}` }))]}
            value={position ?? '__portfolio__'} onChange={(value) => setPosition(value === '__portfolio__' ? null : value)} allowDeselect={false} searchable maw={420} />
          <Textarea ref={input} label={<FieldHelp label="Ваш вопрос" help="Опишите, что хотите понять в результатах. Можно указать показатель или сравнить позиции. Каждый вопрос самостоятельный; расчёты и утверждённый отчёт он не меняет." />}
            placeholder="Например: почему эта позиция теряет больше остальных?"
            autosize minRows={3} maxRows={8} maxLength={2000 - prefix.length} value={question}
            onChange={(e) => { setQuestion(e.currentTarget.value); if (ask.error) ask.reset(); }}
            onKeyDown={(e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && !e.nativeEvent.isComposing) { e.preventDefault(); send(message, question); } }} />
          {!items.length && <Group gap="xs" align="stretch">
            {examples.map((example) => <Button key={example} type="button" className="question-example" size="sm" variant="default"
              onClick={() => { setQuestion(example); input.current?.focus(); }}>{example}</Button>)}
          </Group>}
          {!ready && <Alert color="gray">Вопросы станут доступны после расчёта позиций. Проверьте сценарий и недостающие данные.</Alert>}
          {waiting && <Text size="sm" c="dimmed" role="status">Ответ готовится. Следующий вопрос можно написать сейчас и отправить после завершения.</Text>}
          {ask.error && <ErrorAlert error={ask.error} />}
          <Group justify="space-between" gap="sm">
            <Text size="xs" c="dimmed">{question.length} / {2000 - prefix.length} · Ctrl / ⌘ + Enter — отправить</Text>
            <Button type="submit" leftSection={<IconSend size={16} />} loading={ask.isPending} disabled={!question.trim() || busy || !ready || message.length > 2000}>Получить объяснение</Button>
          </Group>
        </Stack>
      </Paper>
      {list.error && <Stack gap="sm"><ErrorAlert error={list.error} /><Button variant="default" w="fit-content" onClick={() => list.refetch()}>Загрузить историю ещё раз</Button></Stack>}
      {list.isPending ? <Center py="md" role="status"><Loader size="sm" /><Text size="sm" ml="sm">Загружаем вопросы…</Text></Center>
        : items.length > 0 && <Stack gap="md">
          <Title order={4}>Вопросы и ответы</Title>
          {items.map((item) => <Answer key={item.explanation_id} item={item} onRetry={(question) => send(question)} busy={busy} {...props} />)}
        </Stack>}
    </Stack>
  );
}
