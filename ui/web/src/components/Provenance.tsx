import { Blockquote, Group, List, Popover, ScrollArea, Stack, Text, UnstyledButton } from '@mantine/core';
import { IconInfoCircle } from '@tabler/icons-react';
import { createContext, useContext, type ReactNode } from 'react';
import type { Artifacts, TraceNumber } from '../api/types';
import { plural } from '../lib/format';
import { describeOrigin } from '../lib/origin';

/** The run whose numbers are on screen: their origins are read against its artifacts. */
export const RunArtifacts = createContext<Artifacts | null>(null);

function Part({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Stack gap={4}>
      <Text size="xs" c="dark.4" fw={600}>
        {title}
      </Text>
      {children}
    </Stack>
  );
}

/** How the number was reached and what it rests on, in the analyst's terms. */
export function OriginBody({ entry, withHow = true }: { entry: TraceNumber; withHow?: boolean }) {
  const artifacts = useContext(RunArtifacts);
  if (!artifacts) return null;
  const view = describeOrigin(entry, artifacts);
  return (
    <Stack gap="sm">
      {withHow && <Text size="sm">{view.how}</Text>}
      {view.scenario.length > 0 && (
        <Part title="Сценарий">
          <List size="sm" spacing={2}>
            {view.scenario.map((line) => (
              <List.Item key={line}>{line}</List.Item>
            ))}
          </List>
        </Part>
      )}
      {view.quotes.map((q) => (
        <Part key={q.where} title={q.where}>
          <Blockquote p="xs" fz="sm" color="gray" iconSize={0} styles={{ root: { borderWidth: 1 } }}>
            {q.text}
          </Blockquote>
        </Part>
      ))}
      {view.inputs.map((group) => (
        <Part key={group.position} title={`Данные позиции ${group.position}`}>
          <Text size="sm">
            {group.items.join(', ')}
            {group.more > 0 ? ` и ещё ${plural(group.more, 'показатель', 'показателя', 'показателей')}` : ''}
          </Text>
          <Text size="xs" c="dark.3">
            {group.bases.join('; ')}
          </Text>
        </Part>
      ))}
      {view.data.length > 0 && (
        <Part title="Данные снимка">
          <List size="xs" spacing={2}>
            {view.data.map((line) => (
              <List.Item key={line}>{line}</List.Item>
            ))}
          </List>
        </Part>
      )}
      {view.positions.length > 0 && (
        <Part title="Позиции в итоге среза">
          <Text size="sm">{view.positions.join(', ')}</Text>
          <Text size="xs" c="dark.3">
            Исходные данные каждой позиции — в её разборе на вкладке «Позиции».
          </Text>
        </Part>
      )}
    </Stack>
  );
}

/** A number that opens its origin in place. */
export function TracedNumber({ entry, children }: { entry: TraceNumber | undefined; children: ReactNode }) {
  if (!entry) return <>{children}</>;
  return (
    <Popover width={400} position="bottom-start" shadow="md" withArrow>
      <Popover.Target>
        <UnstyledButton component="span" className="ref-number" aria-label="Откуда это число">
          {children}
        </UnstyledButton>
      </Popover.Target>
      <Popover.Dropdown p={0}>
        <ScrollArea.Autosize mah={440} type="auto">
          <Stack gap="xs" p="md">
            <Text fw={600} size="sm">
              Откуда это число
            </Text>
            <OriginBody entry={entry} />
          </Stack>
        </ScrollArea.Autosize>
      </Popover.Dropdown>
    </Popover>
  );
}

export function OriginNote({ children }: { children: ReactNode }) {
  return (
    <Group gap={4} c="dark.3">
      <IconInfoCircle size={14} />
      <Text size="xs">{children}</Text>
    </Group>
  );
}
