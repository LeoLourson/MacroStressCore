import { FieldHelp } from '../components/FieldHelp';
import {
  Anchor,
  Blockquote,
  Button,
  Checkbox,
  Collapse,
  Divider,
  FileInput,
  Group,
  Paper,
  SegmentedControl,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Textarea,
  Title,
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { IconArrowLeft, IconChevronDown, IconChevronRight, IconFileText, IconPlayerPlay } from '@tabler/icons-react';
import { useEffect, useState, type FormEvent } from 'react';
import { Link, Navigate, useLocation, useNavigate, useSearchParams } from 'react-router';
import { useLibraryEvents, usePortfolio, usePortfolios, useStartRun, useWorkflows, type StartInput } from '../api/queries';
import { canRun, useSession } from '../auth/session';
import { ErrorAlert } from '../components/ErrorAlert';
import { metricValue, plural, typeName } from '../lib/format';

type Source = 'library' | 'text' | 'file' | 'url';

const SOURCE_LABELS: Record<Source, string> = {
  library: 'Из библиотеки',
  text: 'Свой текст',
  file: 'Документ',
  url: 'Ссылка',
};

/** What «Запустить заново» carries over from an earlier stress test. */
export interface RerunState {
  portfolioId?: string;
  eventText?: string;
  scenario?: string;
  /** Start with the provider's stronger model: the earlier run's model could not build the graph. */
  strongModel?: boolean;
}

/** One part of the form: a quiet heading, separated from the previous part by a rule. */
function Section({ title, first, children }: { title: string; first?: boolean; children: React.ReactNode }) {
  return (
    <>
      {!first && <Divider />}
      <Stack gap="md">
        <Title order={5}>{title}</Title>
        {children}
      </Stack>
    </>
  );
}

interface SizedParameter {
  value: number;
  unit: string;
}

/** The position's size as its plugin states it: the first sourced number of its parameters. */
function sizeOf(params: Record<string, unknown>): SizedParameter | null {
  for (const value of Object.values(params)) {
    const p = value as SizedParameter | null;
    if (p && typeof p === 'object' && typeof p.value === 'number' && typeof p.unit === 'string') return p;
  }
  return null;
}

function PortfolioPositions({ portfolioId }: { portfolioId: string | null }) {
  const [open, { toggle }] = useDisclosure(false);
  const bundle = usePortfolio(portfolioId, true);
  if (!portfolioId || !bundle.data) return null;
  const { instruments, positions, parties } = bundle.data;
  const byId = Object.fromEntries(instruments.map((i) => [i.instrument_id, i]));
  const okved = Object.fromEntries(parties.map((p) => [p.party_id, p.okved]));
  const types = [...new Set(instruments.map((i) => typeName(i.instrument_type)))];
  return (
    <Stack gap="xs">
      <Group gap="xs">
        <Text size="sm" c="dimmed">
          {plural(positions.length, 'позиция', 'позиции', 'позиций')}: {types.join(', ').toLowerCase()}; базовая валюта{' '}
          {bundle.data.portfolio.base_currency}
        </Text>
        <Anchor component="button" type="button" size="sm" onClick={toggle}>
          {open ? 'Скрыть состав' : 'Показать состав'}
        </Anchor>
      </Group>
      <Collapse in={open}>
        <Table withTableBorder>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Позиция</Table.Th>
              <Table.Th>Тип</Table.Th>
              <Table.Th>ОКВЭД эмитента</Table.Th>
              <Table.Th className="num-right">Размер</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {positions.map((position) => {
              const instrument = byId[position.instrument_id];
              const size = sizeOf(position.params);
              return (
                <Table.Tr key={position.position_id}>
                  <Table.Td>
                    {position.position_id}
                    <Text size="xs" c="dimmed">
                      {instrument?.name}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    {typeName(instrument?.instrument_type)} · {instrument?.currency}
                  </Table.Td>
                  <Table.Td>{(instrument?.issuer_id && okved[instrument.issuer_id]) || '—'}</Table.Td>
                  <Table.Td className="num-right">{size ? metricValue(size.value, size.unit) : '—'}</Table.Td>
                </Table.Tr>
              );
            })}
          </Table.Tbody>
        </Table>
      </Collapse>
    </Stack>
  );
}

/** Agent plugins that are off by default: the analyst may add them to this run. */
function OptionalAgents({ chosen, onChange }: { chosen: string[]; onChange: (ids: string[]) => void }) {
  const workflows = useWorkflows();
  const agents = (workflows.data?.find((w) => w.workflow_id === 'stress_test')?.agents ?? []).filter(
    (a) => !a.enabled && a.extends.stress_test,
  );
  const [opened, { toggle }] = useDisclosure(chosen.length > 0);
  if (!agents.length) return null;
  return (
    <>
      <Divider />
      <Anchor component="button" type="button" size="sm" w="fit-content" c="dimmed" onClick={toggle}>
        <Group gap={4}>
          {opened ? <IconChevronDown size={14} /> : <IconChevronRight size={14} />}
          Дополнительные агенты (необязательно, {agents.length} на выбор)
        </Group>
      </Anchor>
      <Collapse in={opened}>
        <Stack gap="xs">
          <Text size="sm" c="dimmed">
            Они пишут только в своё пространство и не меняют сценарий, расчёты и отчёт.
          </Text>
          <Checkbox.Group value={chosen} onChange={onChange}>
            <Stack gap="xs">
              {agents.map((a) => (
                <Checkbox key={a.agent_id} value={a.agent_id} label={a.label} description={a.description || undefined} />
              ))}
            </Stack>
          </Checkbox.Group>
        </Stack>
      </Collapse>
    </>
  );
}

/** Where the library event comes from: links to check it, folded until asked for. */
function EventSources({ sources }: { sources: { source_id: string; title: string; url?: string | null }[] }) {
  const [opened, { toggle }] = useDisclosure(false);
  return (
    <Stack gap={4}>
      <Anchor component="button" type="button" size="sm" w="fit-content" onClick={toggle}>
        {opened ? 'Скрыть источники' : `Источники события (${sources.length})`}
      </Anchor>
      <Collapse in={opened}>
        <Stack gap={4}>
          {sources.map((s) => (
            <Anchor key={s.source_id} href={s.url ?? undefined} target="_blank" rel="noreferrer" size="sm">
              {s.source_id} · {s.title}
            </Anchor>
          ))}
        </Stack>
      </Collapse>
    </Stack>
  );
}

export function NewRun() {
  const { me, mode } = useSession();
  const navigate = useNavigate();
  const rerun = (useLocation().state as RerunState | null) ?? {};
  // A portfolio just saved in the editor, or chosen on the portfolios page.
  const [query] = useSearchParams();
  const asked = query.get('portfolio');
  const demo = mode === 'demo';
  const sources: Source[] = demo ? ['library', 'text', 'file'] : ['text', 'url', 'file'];

  const portfolios = usePortfolios(true);
  const events = useLibraryEvents(demo);
  const start = useStartRun();

  const [portfolioId, setPortfolioId] = useState<string | null>(rerun.portfolioId ?? asked ?? null);
  const [source, setSource] = useState<Source>(rerun.eventText ? 'text' : sources[0]);
  const [eventId, setEventId] = useState<string | null>(null);
  const [text, setText] = useState(rerun.eventText ?? '');
  const [url, setUrl] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [scenario, setScenario] = useState(rerun.scenario ?? '');
  const [review, setReview] = useState(false);
  const [strong, setStrong] = useState(!!rerun.strongModel);
  const [agents, setAgents] = useState<string[]>([]);
  const [missing, setMissing] = useState(false);
  const [presetLoaded, setPresetLoaded] = useState(false);
  const [fullEvent, setFullEvent] = useState(false);

  useEffect(() => {
    if (!demo || rerun.eventText || presetLoaded || !events.data || !portfolios.data) return;
    const preset = events.data.find((e) => e.metadata?.default_start);
    if (preset && !eventId && source === 'library') {
      setEventId(preset.event_id);
      setScenario(preset.metadata?.scenario_text ?? '');
      if (!rerun.portfolioId && !asked && portfolios.data.some((p) => p.portfolio_id === preset.metadata?.portfolio_id)) {
        setPortfolioId(preset.metadata!.portfolio_id!);
      }
      setReview(true);
    }
    setPresetLoaded(true);
  }, [demo, rerun.eventText, rerun.portfolioId, asked, presetLoaded, events.data, portfolios.data, eventId, source]);

  useEffect(() => {
    if (!portfolioId && portfolios.data?.length) setPortfolioId(portfolios.data[0].portfolio_id);
  }, [portfolioId, portfolios.data]);

  const chosen = events.data?.find((e) => e.event_id === eventId) ?? null;

  if (!canRun(me)) return <Navigate to="/" replace />;

  const pickEvent = (id: string | null) => {
    setEventId(id);
    setFullEvent(false);
    const picked = events.data?.find((e) => e.event_id === id);
    // The library event brings its own words about strength; the analyst may change them.
    setScenario(picked?.metadata?.scenario_text ?? '');
  };

  const event = (): StartInput['event'] | null => {
    switch (source) {
      case 'library':
        return eventId ? { kind: 'library', id: eventId } : null;
      case 'text':
        return text.trim() ? { kind: 'text', text: text.trim() } : null;
      case 'url':
        return url.trim() ? { kind: 'url', url: url.trim() } : null;
      case 'file':
        return file ? { kind: 'file', file } : null;
    }
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const input = event();
    if (!portfolioId?.trim() || !input) {
      setMissing(true);
      return;
    }
    start.mutate(
      { portfolioId: portfolioId.trim(), event: input, scenario: scenario.trim() || null, review, agents, strongModel: strong },
      { onSuccess: (status) => navigate(`/runs/${status.run_id}`) },
    );
  };

  return (
    <form onSubmit={submit}>
      <Stack gap="lg" maw={860}>
        <Stack gap={4}>
          <Anchor component={Link} to="/" size="sm">
            <Group gap={4}>
              <IconArrowLeft size={14} /> Все стресс-тесты
            </Group>
          </Anchor>
          <Title order={2}>Новый стресс-тест</Title>
        </Stack>

        <Paper p="lg">
        <Stack gap="lg">
        <Section first title="Портфель">
          {demo || portfolios.data?.length ? (
            <Select
              label={<FieldHelp label="Какой портфель проверяем" help="Выберите сохранённый портфель. Ниже можно проверить его состав перед запуском." />}
              data={(portfolios.data ?? []).map((p) => ({
                value: p.portfolio_id,
                label: p.name && p.name !== p.portfolio_id ? `${p.name} (${p.portfolio_id})` : p.portfolio_id,
              }))}
              value={portfolioId}
              onChange={setPortfolioId}
              allowDeselect={false}
              maw={420}
            />
          ) : (
            <TextInput
              label={<FieldHelp label="Идентификатор портфеля" help="Код портфеля в системах банка." />}
              value={portfolioId ?? ''}
              onChange={(e) => setPortfolioId(e.currentTarget.value)}
              maw={420}
            />
          )}
          <PortfolioPositions portfolioId={portfolioId} />
          {demo && (
            <Anchor component={Link} to="/portfolios/new" size="sm" w="fit-content">
              Собрать свой портфель
            </Anchor>
          )}
        </Section>

        <Section title="Событие">
          <SegmentedControl
            value={source}
            onChange={(v) => setSource(v as Source)}
            data={sources.map((s) => ({ value: s, label: SOURCE_LABELS[s] }))}
            w="fit-content"
          />
          {source === 'library' && (
            <>
              <Select
                label="Событие из библиотеки"
                placeholder="Выберите событие"
                data={(events.data ?? []).map((e) => ({ value: e.event_id, label: e.title }))}
                value={eventId}
                onChange={pickEvent}
                maw={520}
              />
              {chosen?.metadata?.description && (
                <Text size="sm" c="dimmed">{chosen.metadata?.description}</Text>
              )}
              {chosen && (
                <Blockquote color="steel" p="md" fz="sm">
                  <Text size="sm" lineClamp={fullEvent || chosen.text.length <= 600 ? undefined : 6} style={{ whiteSpace: 'pre-wrap' }}>
                    {chosen.text}
                  </Text>
                  {chosen.text.length > 600 && (
                    <Anchor component="button" type="button" size="sm" mt="xs" onClick={() => setFullEvent(!fullEvent)}>
                      {fullEvent ? 'Свернуть текст' : 'Прочитать событие полностью'}
                    </Anchor>
                  )}
                </Blockquote>
              )}
              {!!chosen?.metadata?.sources?.length && <EventSources sources={chosen.metadata.sources} />}
            </>
          )}
          {source === 'text' && (
            <Textarea
              label={<FieldHelp label="Текст события" help="Опишите, что произошло: новость, постановление или решение регулятора." />}
              placeholder="Например: введён утилизационный сбор на спецтехнику; расчёты через платёжных посредников удлинились до 45 дней"
              autosize
              minRows={4}
              value={text}
              onChange={(e) => setText(e.currentTarget.value)}
            />
          )}
          {source === 'url' && (
            <TextInput
              label={<FieldHelp label="Адрес документа" help="Полный адрес страницы с текстом события, начиная с https://." />}
              placeholder="https://…"
              value={url}
              onChange={(e) => setUrl(e.currentTarget.value)}
            />
          )}
          {source === 'file' && (
            <FileInput
              label={<FieldHelp label="Документ события" help="PDF, DOCX или TXT. Для скана без текстового слоя загрузите текстовую версию." />}
              placeholder="Выберите файл"
              accept=".pdf,.docx,.txt"
              leftSection={<IconFileText size={16} />}
              value={file}
              onChange={setFile}
              clearable
              maw={520}
            />
          )}
        </Section>

        <Section title="Сценарий">
          <Textarea
            label={<FieldHelp label="Изменения в сценарии" help="Опишите силу события числом или диапазоном. Для акций отдельно укажите изменение рыночного индекса или отрасли: рост затрат не равен падению цены акции. Все допущения проверяются до расчёта." />}
            placeholder="Например: сбор поднимет стоимость техники примерно на 10 %, не меньше 6 % и не больше 14 %; платежи задержатся на 30–60 дней"
            autosize
            minRows={3}
            value={scenario}
            onChange={(e) => setScenario(e.currentTarget.value)}
          />
          <Checkbox
            label={<FieldHelp label="Остановиться для проверки графа, даже если система не нашла ошибок" help="С этой отметкой вы проверите граф до расчёта. Без неё остановка требуется при ошибках графа или неподтверждённом сценарии." />}
            checked={review}
            onChange={(e) => setReview(e.currentTarget.checked)}
          />
          {me?.llm?.strong_model && (
            <Checkbox
              label={<FieldHelp label={`Строить граф более сильной моделью (${me.llm.strong_model})`} help="Надёжнее строит граф влияния для сложных событий и портфелей, но отвечает дольше: около двух минут на граф. Эта модель отвечает на все вызовы стресс-теста, включая отчёт." />}
              checked={strong}
              onChange={(e) => setStrong(e.currentTarget.checked)}
            />
          )}
        </Section>

        <OptionalAgents chosen={agents} onChange={setAgents} />

        {missing && !(portfolioId?.trim() && event()) && (
          <Text c="orange.9" size="sm">
            Укажите портфель и событие.
          </Text>
        )}
        {start.error && <ErrorAlert error={start.error} />}
        <Divider />
        <Group>
          <Button type="submit" size="md" leftSection={<IconPlayerPlay size={18} />} loading={start.isPending}>
            Запустить стресс-тест
          </Button>
          <Button variant="subtle" color="gray" component={Link} to="/">
            Отмена
          </Button>
        </Group>
        </Stack>
        </Paper>
      </Stack>
    </form>
  );
}
