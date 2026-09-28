import { FieldHelp } from '../../../components/FieldHelp';
import {
  ActionIcon,
  Alert,
  Blockquote,
  Button,
  Divider,
  Drawer,
  Group,
  List,
  NumberInput,
  Paper,
  SegmentedControl,
  Select,
  SimpleGrid,
  Stack,
  Text,
  TextInput,
  Textarea,
  Title,
  Tooltip,
} from '@mantine/core';
import { sha256 } from '@noble/hashes/sha2.js';
import { bytesToHex, utf8ToBytes } from '@noble/hashes/utils.js';
import { IconAlertTriangle, IconPlus, IconTrash } from '@tabler/icons-react';
import { useState } from 'react';
import type { Distribution, Evidence, Graph, GraphEdge, SourceDocument, Violation } from '../../../api/types';
import { day, elasticityText, NBSP, nodeLabels } from '../../../lib/format';
import { DISTRIBUTIONS, EVIDENCE_KINDS, label } from '../../../lib/labels';
import { fragmentPlace } from '../../../lib/origin';
import { problemText } from './problems';
import { descriptiveEdge } from '../../../lib/graph';

const FIELDS: Record<Distribution['family'], [string, string, number][]> = {
  point: [['value', 'Значение', 1]],
  triangular: [
    ['low', 'Минимум', 0],
    ['mode', 'Наиболее вероятное', 0.5],
    ['high', 'Максимум', 1],
  ],
  uniform: [
    ['low', 'Минимум', 0],
    ['high', 'Максимум', 1],
  ],
  lognormal: [
    ['mu', 'μ (среднее логарифма)', 0],
    ['sigma', 'σ (разброс логарифма)', 1],
  ],
};

export function fragmentText(evidence: Evidence, document: SourceDocument | null | undefined): string | null {
  if (evidence.kind !== 'document' || !document || evidence.source_id !== document.doc_id) return null;
  const fragment = document.fragments.find((f) => f.locator === evidence.locator);
  return fragment ? fragment.text.split(/\s+/).join(' ') : null;
}

/** What an evidence rests on, in words: the place of a fragment, or the kind of the source. */
export function evidencePlace(evidence: Evidence, document: SourceDocument | null | undefined): string {
  return evidence.kind === 'document' && document && evidence.source_id === document.doc_id
    ? fragmentPlace(evidence.locator, document.fragments)
    : label(EVIDENCE_KINDS, evidence.kind);
}

/** The places of several evidences, sentences of one text together: «Сценарий, предложения 5, 6». */
export function evidencePlaces(evidence: Evidence[], document: SourceDocument | null | undefined): string {
  const sentences = new Map<string, string[]>();
  for (const place of new Set(evidence.map((e) => evidencePlace(e, document)))) {
    const [head, number] = place.split(', предложение ');
    sentences.set(head, [...(sentences.get(head) ?? []), ...(number ? [number] : [])]);
  }
  return [...sentences]
    .map(([head, numbers]) =>
      numbers.length === 0
        ? head
        : `${head}, ${numbers.length > 1 ? 'предложения' : 'предложение'}${NBSP}${numbers.join(`,${NBSP}`)}`,
    )
    .join('; ');
}

export function EvidenceCard({
  evidence,
  document,
  onRemove,
}: {
  evidence: Evidence;
  document: SourceDocument | null | undefined;
  onRemove?: () => void;
}) {
  const quote = fragmentText(evidence, document);
  const details =
    evidence.kind === 'document'
      ? quote
        ? []
        : [`место в документе: ${evidence.locator}`]
      : [
          `источник: ${evidence.source_id}`,
          `где: ${evidence.locator}`,
          ...(evidence.author ? [`автор: ${evidence.author}`] : []),
          ...(evidence.as_of ? [`на дату: ${day(evidence.as_of)}`] : []),
        ];
  return (
    <Paper p="sm" bg="gray.0" withBorder={false}>
      <Group justify="space-between" align="flex-start" wrap="nowrap">
        <Stack gap={4} miw={0}>
          <Text size="sm" fw={600}>
            {evidencePlace(evidence, document)}
          </Text>
          {quote && (
            <Blockquote p="xs" fz="sm" color="gray" style={{ margin: 0 }}>
              {quote}
            </Blockquote>
          )}
          {details.length > 0 && (
            <Text size="xs" c="dimmed">
              {details.join(' · ')}
            </Text>
          )}
        </Stack>
        {onRemove && (
          <Tooltip label="Удалить источник">
            <ActionIcon variant="subtle" color="gray" onClick={onRemove} aria-label="Удалить источник">
              <IconTrash size={16} />
            </ActionIcon>
          </Tooltip>
        )}
      </Group>
    </Paper>
  );
}

function NewEvidence({
  document,
  author,
  onAdd,
}: {
  document: SourceDocument | null | undefined;
  author: string;
  onAdd: (evidence: Evidence) => void;
}) {
  const fragments = document?.fragments ?? [];
  const [kind, setKind] = useState<Evidence['kind']>(fragments.length ? 'document' : 'expert_assumption');
  const [locator, setLocator] = useState<string | null>(fragments[0]?.locator ?? null);
  const [source, setSource] = useState('');
  const [where, setWhere] = useState('');
  const [text, setText] = useState('');
  const [who, setWho] = useState(author);
  const [asOf, setAsOf] = useState(new Date().toISOString().slice(0, 10));

  const add = () => {
    if (kind === 'document') {
      const fragment = fragments.find((f) => f.locator === locator);
      if (!fragment || !document) return;
      onAdd({
        kind,
        source_id: document.doc_id,
        locator: fragment.locator,
        fragment_sha256: fragment.sha256,
      });
      return;
    }
    // Like a document fragment, the evidence is addressed by the SHA-256 of its text.
    onAdd({
      kind,
      source_id: source.trim(),
      locator: where.trim(),
      fragment_sha256: bytesToHex(sha256(utf8ToBytes(text.trim()))),
      ...(kind === 'expert_assumption' ? { author: who.trim(), as_of: asOf } : {}),
    });
    setSource('');
    setWhere('');
    setText('');
  };

  const ready =
    kind === 'document'
      ? !!locator
      : !!(source.trim() && where.trim() && text.trim() && (kind !== 'expert_assumption' || (who.trim() && asOf)));

  return (
    <Stack gap="sm">
      <Select
        label={<FieldHelp label="Тип источника" help="Выберите основание связи: текст события, историческая оценка или допущение эксперта." />}
        data={Object.entries(EVIDENCE_KINDS)
          .filter(([value]) => value !== 'document' || fragments.length > 0)
          .map(([value, text]) => ({ value, label: text }))}
        value={kind}
        onChange={(v) => v && setKind(v as Evidence['kind'])}
        allowDeselect={false}
      />
      {kind === 'document' ? (
        <Select
          label={<FieldHelp label="Фрагмент текста события" help="Фрагмент исходного документа, подтверждающий эту связь графа." />}
          data={fragments.map((f) => ({
            value: f.locator,
            label: `${fragmentPlace(f.locator, fragments)}: ${f.text.split(/\s+/).join(' ').slice(0, 90)}`,
          }))}
          value={locator}
          onChange={setLocator}
          allowDeselect={false}
        />
      ) : (
        <>
          <TextInput
            label={<FieldHelp label="Источник" help="Название документа, исследования или экспертной оценки, на которые вы ссылаетесь." />}
            placeholder="Например: отчёт отраслевого союза, 2025"
            value={source}
            onChange={(e) => setSource(e.currentTarget.value)}
          />
          <TextInput
            label={<FieldHelp label="Где в источнике" help="Укажите раздел, таблицу или страницу, чтобы другой аналитик мог найти основание." />}
            placeholder="Раздел, таблица или страница"
            value={where}
            onChange={(e) => setWhere(e.currentTarget.value)}
          />
          <Textarea
            label={<FieldHelp label="Обоснование" help="Объясните, почему причина влияет на следствие и откуда взята сила связи." />}
            autosize
            minRows={2}
            value={text}
            onChange={(e) => setText(e.currentTarget.value)}
          />
          {kind === 'expert_assumption' && (
            <SimpleGrid cols={2}>
              <TextInput label={<FieldHelp label="Автор" help="Имя эксперта, отвечающего за допущение." />} value={who} onChange={(e) => setWho(e.currentTarget.value)} />
              <TextInput
                label={<FieldHelp label="По состоянию на" help="Дата, на которую допущение актуально." />}
                type="date"
                value={asOf}
                onChange={(e) => setAsOf(e.currentTarget.value)}
              />
            </SimpleGrid>
          )}
        </>
      )}
      <Button variant="light" leftSection={<IconPlus size={16} />} disabled={!ready} onClick={add} w="fit-content">
        Добавить источник
      </Button>
    </Stack>
  );
}

function ElasticityInput({ value, onChange }: { value: Distribution; onChange: (d: Distribution) => void }) {
  const current = value as unknown as Record<string, number>;
  return (
    <Stack gap="xs">
      <Select
        label={<FieldHelp label="Сила связи (эластичность)" help="На сколько процентов меняется следствие при изменении причины на 1%. Выберите точное значение или распределение неопределённости." />}
        data={Object.entries(DISTRIBUTIONS).map(([v, text]) => ({ value: v, label: text }))}
        value={value.family}
        allowDeselect={false}
        onChange={(family) => {
          if (!family) return;
          const fields = FIELDS[family as Distribution['family']];
          const next: Record<string, unknown> = { family };
          for (const [name, , fallback] of fields) next[name] = current[name] ?? current.value ?? fallback;
          onChange(next as unknown as Distribution);
        }}
      />
      <SimpleGrid cols={FIELDS[value.family].length}>
        {FIELDS[value.family].map(([name, caption]) => (
          <NumberInput
            key={name}
            label={<FieldHelp label={caption} help="Параметр выбранного распределения силы связи. Введите коэффициент без знака: направление задаётся отдельно." />}
            value={current[name]}
            decimalSeparator=","
            step={0.1}
            onChange={(v) => onChange({ ...value, [name]: typeof v === 'number' ? v : Number(v) || 0 } as Distribution)}
          />
        ))}
      </SimpleGrid>
    </Stack>
  );
}

/** One edge of the graph: what it says, what grounds it, and, at the stop, how to change it. */
export function EdgeDrawer({
  graph,
  index,
  document,
  problems,
  editing,
  author,
  onClose,
  onChange,
  onRemove,
}: {
  graph: Graph;
  index: number | null;
  document: SourceDocument | null | undefined;
  problems: Violation[];
  editing: boolean;
  author: string;
  onClose: () => void;
  onChange: (edge: GraphEdge) => void;
  onRemove: () => void;
}) {
  const edge = index != null ? graph.edges[index] : undefined;
  const descriptive = edge ? descriptiveEdge(graph, edge) : false;
  const names = nodeLabels(graph);
  return (
    <Drawer
      opened={!!edge}
      onClose={onClose}
      position="right"
      size="lg"
      title={
        edge && (
          <Title order={4}>
            {names[edge.src] ?? edge.src} → {names[edge.dst] ?? edge.dst}
          </Title>
        )
      }
    >
      {edge && (
        <Stack gap="md">
          {problems.length > 0 && (
            <Alert color="orange" variant="light" icon={<IconAlertTriangle />} title="Что не так">
              <List size="sm">
                {problems.map((p, i) => (
                  <List.Item key={i}>{problemText(p, graph)}</List.Item>
                ))}
              </List>
            </Alert>
          )}
          {descriptive ? (
            <Text size="sm">
              Связь объясняет влияние события на прямой фактор. Величина изменения задаётся
              параметром сценария; эластичность и задержка этой стрелки не меняют расчёт.
            </Text>
          ) : editing ? (
            <Stack gap="sm">
              <SimpleGrid cols={2}>
                <Stack gap={4}>
                  <Text size="sm" fw={500}>
                    Направление влияния
                  </Text>
                  <SegmentedControl
                    value={String(edge.sign)}
                    onChange={(v) => onChange({ ...edge, sign: Number(v) as 1 | -1 })}
                    data={[
                      { value: '1', label: 'Усиливает (+)' },
                      { value: '-1', label: 'Ослабляет (−)' },
                    ]}
                  />
                </Stack>
                <NumberInput
                  label={<FieldHelp label="Задержка, мес." help="Через сколько полных месяцев начинает действовать связь. 0 — сразу." />}
                  min={0}
                  max={36}
                  allowDecimal={false}
                  value={edge.lag_months}
                  onChange={(v) => onChange({ ...edge, lag_months: Math.max(0, Math.min(36, Number(v) || 0)) })}
                />
              </SimpleGrid>
              <ElasticityInput value={edge.elasticity} onChange={(elasticity) => onChange({ ...edge, elasticity })} />
              <Text size="xs" c="dimmed">
                Правки сразу попадают в черновик и проверяются; на расчёт они уйдут после «Подтвердить».
              </Text>
            </Stack>
          ) : (
            <SimpleGrid cols={3}>
              <Stack gap={0}>
                <Text size="xs" c="dimmed">
                  Направление
                </Text>
                <Text size="sm">{edge.sign === 1 ? 'Усиливает (+)' : 'Ослабляет (−)'}</Text>
              </Stack>
              <Stack gap={0}>
                <Text size="xs" c="dimmed">
                  Сила связи
                </Text>
                <Text size="sm">{elasticityText(edge.elasticity)}</Text>
              </Stack>
              <Stack gap={0}>
                <Text size="xs" c="dimmed">
                  Задержка
                </Text>
                <Text size="sm">{edge.lag_months ? `${edge.lag_months} мес.` : 'нет'}</Text>
              </Stack>
            </SimpleGrid>
          )}

          <Divider label="Источники" labelPosition="left" />
          {edge.evidence.length === 0 && (
            <Text size="sm" c="orange.9">
              У связи нет источника. Добавьте его, иначе расчёт нельзя продолжить.
            </Text>
          )}
          {edge.evidence.map((evidence, i) => (
            <EvidenceCard
              key={i}
              evidence={evidence}
              document={document}
              onRemove={
                editing ? () => onChange({ ...edge, evidence: edge.evidence.filter((_, j) => j !== i) }) : undefined
              }
            />
          ))}
          {editing && (
            <>
              <Divider label="Добавить источник" labelPosition="left" />
              <NewEvidence
                document={document}
                author={author}
                onAdd={(evidence) => onChange({ ...edge, evidence: [...edge.evidence, evidence] })}
              />
              <Divider />
              <Button
                variant="subtle"
                color="gray"
                leftSection={<IconTrash size={16} />}
                onClick={onRemove}
                w="fit-content"
              >
                Удалить связь из графа
              </Button>
            </>
          )}
        </Stack>
      )}
    </Drawer>
  );
}
