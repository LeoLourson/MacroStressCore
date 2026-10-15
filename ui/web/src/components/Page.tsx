// The two containers every screen is built from. A page has one header; its content is a
// column of sections. A section is a card at the page level only: inside it, groups are set
// apart by space and a smaller heading, never by a card within a card. The card padding and
// the outer cell padding of a flush table are the same, so headings, text and the first
// column of a table share one left edge.
import { Anchor, Box, Group, Paper, Stack, Text, Title } from '@mantine/core';
import { IconArrowLeft } from '@tabler/icons-react';
import type { ReactNode } from 'react';
import { Link } from 'react-router';
import { Hint } from './Term';

/** The one narrow width: forms and a single column of reading. Everything else is full width. */
export const NARROW = 880;

function Heading({ order, title, hint }: { order: 2 | 3 | 4; title: ReactNode; hint?: ReactNode }) {
  return <Title order={order}>{hint ? <Hint text={hint}>{title}</Hint> : title}</Title>;
}

/** Back link, title with its hint, one line of facts, and the page's one main action. */
export function PageHeader({
  title,
  hint,
  back,
  meta,
  actions,
}: {
  title: ReactNode;
  hint?: ReactNode;
  back?: { to: string; label: string };
  meta?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <Stack gap={6}>
      {back && (
        <Anchor component={Link} to={back.to} size="sm" w="fit-content">
          <Group gap={4} wrap="nowrap">
            <IconArrowLeft size={14} /> {back.label}
          </Group>
        </Anchor>
      )}
      <Group justify="space-between" align="center" gap="sm" mih={36}>
        <Box style={{ flex: '1 1 320px', minWidth: 0 }}>
          <Heading order={2} title={title} hint={hint} />
        </Box>
        {actions && <Group gap="xs">{actions}</Group>}
      </Group>
      {meta && (
        <Text size="sm" c="dimmed" component="div">
          {meta}
        </Text>
      )}
    </Stack>
  );
}

/**
 * A card with a heading. `aside` is a quiet fact or the section's own action at the right of
 * the heading; `flush` lets a table run to the card's edges.
 */
export function PageSection({
  title,
  hint,
  aside,
  flush,
  children,
}: {
  title?: ReactNode;
  hint?: ReactNode;
  aside?: ReactNode;
  flush?: boolean;
  children: ReactNode;
}) {
  const head = (title || aside) && (
    <Group justify="space-between" align="center" gap="xs" mih={28} px={flush ? 'lg' : 0} pt={flush ? 'lg' : 0} pb={flush ? 'sm' : 0} style={{ columnGap: 'var(--mantine-spacing-md)' }}>
      {title ? <Heading order={3} title={title} hint={hint} /> : <span />}
      {/* On a narrow screen the quiet part goes under the heading rather than squeezing it. */}
      {aside && (
        <Group gap="xs" c="dimmed" fz="sm">
          {aside}
        </Group>
      )}
    </Group>
  );
  return (
    // A wide table scrolls inside its card; it never widens the page.
    <Paper p={flush ? 0 : 'lg'} className={flush ? 'flush' : undefined} style={{ minWidth: 0 }}>
      {flush ? (
        <>
          {head}
          <Box style={{ overflowX: 'auto' }}>{children}</Box>
        </>
      ) : (
        <Stack gap="md" style={{ overflowX: 'auto' }}>
          {head}
          {children}
        </Stack>
      )}
    </Paper>
  );
}

/**
 * The one bar that stays at the bottom of the screen while its decision is open: the state in
 * one short line at the left, the actions at the right, all of one height. The analyst's
 * confirmation of the graph and the risk manager's decision use it alike.
 */
export function ActionBar({ status, actions, id }: { status: ReactNode; actions: ReactNode; id?: string }) {
  return (
    <Paper
      id={id}
      px="lg"
      py="sm"
      shadow="md"
      style={{ position: 'sticky', bottom: 16, zIndex: 20, borderColor: 'var(--mantine-color-gray-4)' }}
    >
      <Group justify="space-between" align="center" gap="sm">
        <Text size="sm" c="dimmed" component="div" style={{ flex: '1 1 240px', minWidth: 0 }}>
          {status}
        </Text>
        <Group gap="xs">{actions}</Group>
      </Group>
    </Paper>
  );
}

/** A group inside a section: a small heading, its hint, and what it holds. */
export function Subsection({ title, hint, aside, children }: { title: ReactNode; hint?: ReactNode; aside?: ReactNode; children: ReactNode }) {
  return (
    <Stack gap="xs">
      <Group justify="space-between" align="baseline" wrap="nowrap" gap="md">
        <Heading order={4} title={title} hint={hint} />
        {aside && (
          <Text size="sm" c="dimmed" component="div">
            {aside}
          </Text>
        )}
      </Group>
      {children}
    </Stack>
  );
}
