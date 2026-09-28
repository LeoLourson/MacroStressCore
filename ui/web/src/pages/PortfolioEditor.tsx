import {
  ActionIcon,
  Alert,
  Anchor,
  Autocomplete,
  Badge,
  Button,
  Checkbox,
  Collapse,
  FileButton,
  Group,
  NumberInput,
  Paper,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconArrowLeft, IconDownload, IconPlus, IconTrash, IconUpload } from '@tabler/icons-react';
import { useEffect, useState } from 'react';
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router';
import { getCatalog, instrumentTypes, typeSpec, type EditorField, type EditorGroup } from '../api/catalog';
import { useCreatePortfolio } from '../api/queries';
import type { DraftPosition, PortfolioDraft } from '../api/types';
import { canRun, useClient, useSession } from '../auth/session';
import { ErrorAlert } from '../components/ErrorAlert';
import { FieldHelp } from '../components/FieldHelp';
import { typeName } from '../lib/format';
import {
  allowsNegative,
  draftFrom,
  derivedValue,
  emptyPosition,
  fieldHelp,
  fieldValue,
  fromScreen,
  groupsOf,
  missingFields,
  newRow,
  retype,
  toScreen,
  unitSuffix,
} from '../lib/portfolioFields';

/** One input of a plugin's form, by the kind of its field. */
function FieldInput({
  field,
  value,
  base,
  currency = base,
  automatic,
  onChange,
}: {
  field: EditorField;
  value: unknown;
  base: string;
  currency?: string;
  automatic?: string;
  onChange: (value: unknown) => void;
}) {
  const fieldLabel = <FieldHelp label={field.label} help={fieldHelp(field)} />;
  const choices = field.options.map(([value, label]) => ({ value, label }));
  if (typeof value === 'string' && value && value !== '__automatic__' && !choices.some((option) => option.value === value)) {
    choices.push({ value, label: value });
  }
  switch (field.kind) {
    case 'text':
    case 'date':
      return field.kind === 'text' && field.options.length ? (
        <Autocomplete label={fieldLabel} withAsterisk={field.required}
          data={field.options.map(([value, label]) => ({ value, label }))}
          value={typeof value === 'string' ? value : ''}
          onChange={(v) => onChange(v.trim() || undefined)} />
      ) : (
        <TextInput
          label={fieldLabel}
          withAsterisk={field.required}
          placeholder={field.kind === 'date' ? 'ГГГГ-ММ-ДД' : field.default != null ? String(field.default) : undefined}
          value={(value as string | undefined) ?? ''}
          onChange={(e) => onChange(e.currentTarget.value.trim() || undefined)}
        />
      );
    case 'dates':
      return (
        <TextInput
          label={fieldLabel}
          withAsterisk={field.required}
          value={((value as string[] | undefined) ?? []).join(', ')}
          onChange={(e) =>
            onChange(
              e.currentTarget.value
                .split(',')
                .map((d) => d.trim())
                .filter(Boolean),
            )
          }
        />
      );
    case 'enum':
      return (
        <Select
          label={fieldLabel}
          withAsterisk={field.required}
          data={field.derive_from ? [
            { value: '__automatic__', label: automatic ? `По ОКВЭД: ${choices.find((c) => c.value === automatic)?.label ?? automatic}` : 'По ОКВЭД — выберите отрасль' },
            ...choices,
          ] : choices}
          searchable
          value={(value as string | undefined) ?? null}
          onChange={(v) => onChange(v === '__automatic__' ? undefined : v ?? undefined)}
        />
      );
    case 'boolean':
      return (
        <Checkbox
          label={fieldLabel}
          checked={value === true}
          onChange={(e) => onChange(e.currentTarget.checked)}
        />
      );
    default:
      return (
        <NumberInput
          label={fieldLabel}
          withAsterisk={field.required}
          rightSection={
            <Text size="xs" c="dimmed" pr={6}>
              {unitSuffix(field.unit, base, currency)}
            </Text>
          }
          rightSectionWidth={field.unit === 'fx_quote' ? 84 : 72}
          decimalSeparator=","
          thousandSeparator=" "
          allowNegative={allowsNegative(field)}
          min={field.minimum == null ? undefined : toScreen(field.unit, field.minimum)}
          max={field.maximum == null ? undefined : toScreen(field.unit, field.maximum)}
          value={typeof value === 'number' ? toScreen(field.unit, value) : ''}
          onChange={(v) => onChange(v === '' || v == null ? undefined : fromScreen(field.unit, Number(v)))}
        />
      );
  }
}

/** A table field (covenants): rows of its columns. */
function TableInput({
  field,
  rows,
  base,
  onChange,
}: {
  field: EditorField;
  rows: Record<string, unknown>[];
  base: string;
  onChange: (rows: Record<string, unknown>[]) => void;
}) {
  const set = (index: number, name: string, value: unknown) =>
    onChange(rows.map((row, i) => (i === index ? { ...row, [name]: value } : row)));
  return (
    <Stack gap="xs">
      <Group justify="space-between" align="flex-start">
        <Text size="sm" fw={600}>
          <FieldHelp label={field.label} help={fieldHelp(field)} />
        </Text>
        <Button size="xs" variant="default" leftSection={<IconPlus size={14} />} onClick={() => onChange([...rows, newRow(field)])}>
          Добавить строку
        </Button>
      </Group>
      {rows.length === 0 && (
        <Text size="sm" c="dimmed">
          Строк нет.
        </Text>
      )}
      {rows.map((row, index) => (
        <Group key={index} align="flex-end" gap="sm" wrap="wrap">
          {field.columns.map((column) => (
            <div key={column.name} style={{ width: column.kind === 'dates' ? 320 : 200 }}>
              <FieldInput field={column} value={row[column.name]} base={base} onChange={(v) => set(index, column.name, v)} />
            </div>
          ))}
          <ActionIcon
            variant="subtle"
            color="gray"
            aria-label="Удалить строку"
            mb={4}
            onClick={() => onChange(rows.filter((_, i) => i !== index))}
          >
            <IconTrash size={16} />
          </ActionIcon>
        </Group>
      ))}
    </Stack>
  );
}

function Group_({
  group,
  position,
  base,
  onChange,
}: {
  group: EditorGroup;
  position: DraftPosition;
  base: string;
  onChange: (position: DraftPosition) => void;
}) {
  const filled = group.fields.some((f) => position.values[f.name] != null || position.tables[f.name]?.length);
  const [open, setOpen] = useState(!group.folded || filled);
  const simple = group.fields.filter((f) => f.kind !== 'table' && !f.advanced && !(f.unit === 'fx_quote' && position.currency === base));
  const advanced = group.fields.filter((f) => f.kind !== 'table' && f.advanced);
  const tables = group.fields.filter((f) => f.kind === 'table');
  const [more, setMore] = useState(advanced.some((f) => position.values[f.name] != null));
  const setValue = (name: string, value: unknown) => {
    const values = { ...position.values };
    if (value == null) delete values[name];
    else values[name] = value;
    onChange({ ...position, values });
  };
  const grid = (fields: EditorField[]) => (
    <SimpleGrid cols={{ base: 1, sm: 2, md: 3 }} className="portfolio-field-grid">
      {fields.map((field) => (
        <FieldInput key={field.name} field={field}
          value={field.derive_from && !position.values[field.name] ? '__automatic__' : fieldValue(field, position)}
          automatic={derivedValue(field, position)} base={base} currency={position.currency}
          onChange={(v) => setValue(field.name, v)} />
      ))}
    </SimpleGrid>
  );
  return (
    <Stack gap="xs">
      <Anchor component="button" type="button" onClick={() => setOpen(!open)} w="fit-content" c="dark.7">
        <Title order={5}>
          {open ? '▾' : '▸'} {group.title}
        </Title>
      </Anchor>
      <Collapse in={open}>
        <Stack gap="sm">
          {simple.length > 0 && grid(simple)}
          {advanced.length > 0 && (
            <>
              <Anchor component="button" type="button" size="sm" w="fit-content" onClick={() => setMore(!more)}>
                {more ? 'Скрыть дополнительные входы модели' : 'Дополнительные входы модели'}
              </Anchor>
              <Collapse in={more}>{grid(advanced)}</Collapse>
            </>
          )}
          {tables.map((field) => (
            <TableInput
              key={field.name}
              field={field}
              rows={position.tables[field.name] ?? []}
              base={base}
              onChange={(rows) => onChange({ ...position, tables: { ...position.tables, [field.name]: rows } })}
            />
          ))}
        </Stack>
      </Collapse>
    </Stack>
  );
}

function PositionEditor({
  position,
  base,
  onChange,
}: {
  position: DraftPosition;
  base: string;
  onChange: (position: DraftPosition) => void;
}) {
  const spec = typeSpec(position.instrument_type);
  const currencies = getCatalog().units.currencies;
  return (
    <Stack gap="lg">
      <SimpleGrid cols={{ base: 1, sm: 2, md: 3 }} className="portfolio-field-grid">
        <TextInput
          label={<FieldHelp label="Код позиции" help="Уникальный код позиции в портфеле: латиница, цифры, дефис, например P1" />}
          withAsterisk
          value={position.position_id}
          onChange={(e) => onChange({ ...position, position_id: e.currentTarget.value.trim() })}
        />
        <TextInput
          label={<FieldHelp label="Эмитент или название" help="Как позиция называется в списке и в отчёте" />}
          withAsterisk
          value={position.name}
          onChange={(e) => onChange({ ...position, name: e.currentTarget.value })}
        />
        <Select
          label={<FieldHelp label="Тип инструмента" help={spec?.description || 'Вид инструмента: от него зависят поля и модель расчёта'} />}
          withAsterisk
          data={instrumentTypes().map((item) => ({ value: item.asset_type, label: item.label }))}
          value={position.instrument_type}
          onChange={(v) => v && onChange(retype(position, v))}
          allowDeselect={false}
        />
        <TextInput
          label={<FieldHelp label="ОКВЭД 2 эмитента" help="Основной вид деятельности эмитента, например 46.63: по нему событие находит позицию" />}
          withAsterisk={spec?.issuer_required}
          value={position.okved ?? ''}
          onChange={(e) => onChange({ ...position, okved: e.currentTarget.value.trim() })}
        />
        <Select
          label={<FieldHelp label="Валюта инструмента" help="Валюта договора или котировки акции" />}
          data={currencies.length ? currencies : [base]}
          value={position.currency}
          onChange={(v) => v && onChange({ ...position, currency: v })}
          allowDeselect={false}
        />
      </SimpleGrid>
      <Text size="sm" c="dimmed">
        * Обязательные поля. Пояснение к полю появляется при наведении на его название.
      </Text>
      {groupsOf(position.instrument_type).map((group) => (
        <Group_ key={`${position.instrument_type}:${group.group_id}`} group={group} position={position} base={base} onChange={onChange} />
      ))}
    </Stack>
  );
}

function problems(draft: PortfolioDraft): string[] {
  const out: string[] = [];
  if (!draft.name.trim()) out.push('Укажите название портфеля.');
  const ids = draft.positions.map((p) => p.position_id);
  if (new Set(ids).size !== ids.length) out.push('Коды позиций повторяются.');
  for (const p of draft.positions) {
    const needsOkved = typeSpec(p.instrument_type)?.issuer_required;
    if (!p.position_id || !p.name.trim()) out.push(`${p.position_id || 'Позиция без кода'}: заполните код и название.`);
    if ((needsOkved || p.okved) && !/^\d{2}(\.\d{1,2}){0,2}$/.test(p.okved ?? '')) {
      out.push(`${p.position_id}: укажите ОКВЭД эмитента вида 46.63.`);
    }
    const missing = missingFields(p);
    if (missing.length) out.push(`${p.position_id}: не хватает — ${missing.map((f) => f.label.toLowerCase()).join(', ')}.`);
  }
  return out;
}

function download(draft: PortfolioDraft) {
  const blob = new Blob([JSON.stringify(draft, null, 2)], { type: 'application/json' });
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = `${draft.name || 'portfolio'}.json`;
  link.click();
  URL.revokeObjectURL(link.href);
}

/** A draft from a JSON file in this editor's format. */
function parseImport(text: string): PortfolioDraft {
  const raw = JSON.parse(text);
  if (!raw || !Array.isArray(raw.positions)) throw new Error('not a draft');
  return {
    name: raw.name ?? 'Импорт',
    base_currency: raw.base_currency ?? 'RUB',
    positions: raw.positions.map((p: Partial<DraftPosition>) => ({
      ...p,
      values: p.values ?? {},
      tables: p.tables ?? {},
      currency: p.currency ?? raw.base_currency ?? 'RUB',
    })),
  };
}

export function PortfolioEditor() {
  const { me, mode } = useSession();
  const client = useClient();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const from = params.get('from');
  const create = useCreatePortfolio();
  const [draft, setDraft] = useState<PortfolioDraft>({ name: '', base_currency: 'RUB', positions: [emptyPosition(1, 'RUB')] });
  const [selected, setSelected] = useState(0);
  const [importError, setImportError] = useState<string | null>(null);
  const [touched, setTouched] = useState(false);

  useEffect(() => {
    if (!from) return;
    client
      .portfolio(from)
      .then(async (bundle) => {
        const snapshot = bundle.portfolio.snapshot_id ? await client.snapshot(bundle.portfolio.snapshot_id) : { items: [] };
        setDraft(draftFrom(`Копия ${bundle.portfolio.name || from}`, bundle, snapshot.items));
        setSelected(0);
      })
      .catch(() => setImportError(`Портфель ${from} не найден.`));
  }, [from, client]);

  if (!canRun(me)) return <Navigate to="/" replace />;
  if (mode !== 'demo') return <Navigate to="/portfolios" replace />;

  const position = draft.positions[selected];
  const issues = problems(draft);
  const update = (next: DraftPosition) =>
    setDraft({ ...draft, positions: draft.positions.map((p, i) => (i === selected ? next : p)) });

  const save = () => {
    setTouched(true);
    if (issues.length) return;
    const payload: PortfolioDraft = {
      ...draft,
      positions: draft.positions.map((p) => ({ ...p, okved: p.okved || null })),
    };
    create.mutate(payload, {
      onSuccess: ({ portfolio_id }) => {
        notifications.show({ message: `Портфель «${draft.name}» сохранён`, color: 'teal' });
        navigate(`/new?portfolio=${encodeURIComponent(portfolio_id)}`);
      },
    });
  };

  return (
    <Stack gap="lg" maw={1100}>
      <Stack gap={4}>
        <Anchor component={Link} to="/portfolios" size="sm">
          <Group gap={4}>
            <IconArrowLeft size={14} /> Все портфели
          </Group>
        </Anchor>
        <Title order={2}>{from ? 'Копия портфеля' : 'Новый портфель'}</Title>
        <Text size="sm" c="dimmed" maw="80ch">
          Каждое введённое число сохранится как допущение аналитика с вашим
          именем и сегодняшней датой: отчёт сошлётся на него как на источник. Портфель хранится семь дней в демо-контуре.
        </Text>
      </Stack>

      <Paper p="lg">
        <Group align="flex-end" justify="space-between" gap="md">
          <Group align="flex-end" gap="md">
            <TextInput
              label={<FieldHelp label="Название портфеля" help="Под этим названием портфель виден при запуске стресс-теста" />}
              withAsterisk
              value={draft.name}
              onChange={(e) => setDraft({ ...draft, name: e.currentTarget.value })}
              w={{ base: '100%', sm: 320 }}
              maxLength={80}
            />
            <Select
              label={<FieldHelp label="Базовая валюта" help="Валюта, в которой считаются итоги портфеля" />}
              data={getCatalog().units.currencies.length ? getCatalog().units.currencies : ['RUB']}
              value={draft.base_currency}
              onChange={(v) => v && setDraft({ ...draft, base_currency: v })}
              allowDeselect={false}
              w={180}
            />
          </Group>
          <Group gap="xs">
            <FileButton
              accept="application/json,.json"
              onChange={(file) => {
                setImportError(null);
                file
                  ?.text()
                  .then((text) => {
                    setDraft(parseImport(text));
                    setSelected(0);
                  })
                  .catch(() => setImportError('Файл не похож на портфель: ожидается JSON этого редактора.'));
              }}
            >
              {(props) => (
                <Button variant="default" leftSection={<IconUpload size={16} />} {...props}>
                  Импорт JSON
                </Button>
              )}
            </FileButton>
            <Button variant="default" leftSection={<IconDownload size={16} />} onClick={() => download(draft)}>
              Экспорт JSON
            </Button>
          </Group>
        </Group>
        {importError && (
          <Alert color="orange" variant="light" mt="md">
            {importError}
          </Alert>
        )}
      </Paper>

      <Paper>
        <Table.ScrollContainer minWidth={620}>
        <Table highlightOnHover verticalSpacing="xs">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Позиция</Table.Th>
              <Table.Th>Тип</Table.Th>
              <Table.Th>ОКВЭД</Table.Th>
              <Table.Th>Валюта</Table.Th>
              <Table.Th>Готовность</Table.Th>
              <Table.Th w={40} />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {draft.positions.map((p, index) => {
              const missing = missingFields(p).length;
              return (
                <Table.Tr
                  key={index}
                  className="clickable-row"
                  onClick={() => setSelected(index)}
                  bg={index === selected ? 'steel.0' : undefined}
                >
                  <Table.Td>
                    <Text size="sm" fw={500}>
                      {p.name || '—'}
                    </Text>
                    <Text size="xs" c="dimmed">
                      {p.position_id}
                    </Text>
                  </Table.Td>
                  <Table.Td>{typeName(p.instrument_type)}</Table.Td>
                  <Table.Td>{p.okved || '—'}</Table.Td>
                  <Table.Td>{p.currency}</Table.Td>
                  <Table.Td>
                    {missing ? (
                      <Badge variant="light" color="orange" c="orange.9" tt="none" fw={500}>
                        не хватает {missing}
                      </Badge>
                    ) : (
                      <Badge variant="light" color="teal" c="teal.9" tt="none" fw={500}>
                        ✓ готова
                      </Badge>
                    )}
                  </Table.Td>
                  <Table.Td>
                    {draft.positions.length > 1 && (
                      <ActionIcon
                        variant="subtle"
                        color="gray"
                        aria-label="Удалить позицию"
                        onClick={(e) => {
                          e.stopPropagation();
                          setDraft({ ...draft, positions: draft.positions.filter((_, i) => i !== index) });
                          setSelected(Math.max(0, Math.min(selected, draft.positions.length - 2)));
                        }}
                      >
                        <IconTrash size={16} />
                      </ActionIcon>
                    )}
                  </Table.Td>
                </Table.Tr>
              );
            })}
          </Table.Tbody>
        </Table>
        </Table.ScrollContainer>
        <Group p="sm">
          <Button
            variant="subtle"
            leftSection={<IconPlus size={16} />}
            onClick={() => {
              setDraft({ ...draft, positions: [...draft.positions, emptyPosition(draft.positions.length + 1, draft.base_currency)] });
              setSelected(draft.positions.length);
            }}
          >
            Добавить позицию
          </Button>
        </Group>
      </Paper>

      {position && (
        <Paper p="lg">
          <Stack gap="md">
            <Title order={4}>{position.name || position.position_id || 'Позиция'}</Title>
            <PositionEditor key={selected} position={position} base={draft.base_currency} onChange={update} />
          </Stack>
        </Paper>
      )}

      {touched && issues.length > 0 && (
        <Alert color="orange" variant="light" title="Портфель ещё не готов">
          <Stack gap={2}>
            {issues.map((issue) => (
              <Text key={issue} size="sm">
                {issue}
              </Text>
            ))}
          </Stack>
        </Alert>
      )}
      {create.error && <ErrorAlert error={create.error} />}
      <Group>
        <Button size="md" onClick={save} loading={create.isPending}>
          Сохранить и перейти к стресс-тесту
        </Button>
        <Button variant="subtle" color="gray" component={Link} to="/portfolios">
          Отмена
        </Button>
      </Group>
    </Stack>
  );
}
