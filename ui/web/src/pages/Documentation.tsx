// The mathematics of the platform and of its plugins (GET /v1/docs). Each level of the
// contents is divided on one basis: first by who owns the formula (the platform for every
// instrument, or a plugin for its own), then the platform's pages in the order a stress test
// calculates, and a plugin's pages in the order the plugin declares. A page is the page
// header and one section per «## » heading of its Markdown.
import { Box, Center, Group, Loader, NavLink, Select, Stack, Text } from '@mantine/core';
import { Link, Navigate, useNavigate, useParams } from 'react-router';
import { useDocs } from '../api/queries';
import type { DocPage, Documentation as Docs } from '../api/types';
import { ErrorAlert } from '../components/ErrorAlert';
import { Markdown } from '../components/Markdown';
import { NARROW, PageHeader, PageSection } from '../components/Page';
import { Hint } from '../components/Term';

const PLATFORM = 'platform';

const DIVISION =
  'Формулы разделены по тому, кто их считает: платформа — одинаково для всех инструментов, плагин — ' +
  'для своих инструментов и выводов. Страницы платформы идут в порядке расчёта стресс-теста, страницы ' +
  'плагина он несёт сам.';

interface Chapter {
  owner: string;
  label: string;
  pages: DocPage[];
}

function groups(docs: Docs): Chapter[] {
  return [
    { owner: PLATFORM, label: 'Платформа', pages: docs.platform },
    ...docs.plugins.map((plugin) => ({ owner: plugin.plugin_id, label: plugin.label, pages: plugin.pages })),
  ];
}

function href(owner: string, slug: string) {
  return `/documentation/${owner}/${slug}`;
}

function Contents({ docs, owner, slug }: { docs: Docs; owner: string; slug: string }) {
  const [platform, ...plugins] = groups(docs);
  const links = (group: Chapter) =>
    group.pages.map((page) => (
      <NavLink
        key={page.slug}
        component={Link}
        to={href(group.owner, page.slug)}
        label={page.title}
        active={group.owner === owner && page.slug === slug}
        py={6}
        style={{ borderRadius: 'var(--mantine-radius-sm)' }}
      />
    ));
  return (
    <Stack gap="lg">
      <Text fw={600} size="sm">
        <Hint text={DIVISION}>Документация</Hint>
      </Text>
      <Stack gap={2}>
        <Text size="xs" fw={500} c="dimmed" mb={4}>
          Платформа
        </Text>
        {links(platform)}
      </Stack>
      <Stack gap="sm">
        <Text size="xs" fw={500} c="dimmed">
          Плагины
        </Text>
        {plugins.map((group) => (
          <Stack key={group.owner} gap={2}>
            <Text size="sm" fw={500} mb={2}>
              {group.label}
            </Text>
            {links(group)}
          </Stack>
        ))}
      </Stack>
    </Stack>
  );
}

/** The page's Markdown split at its «## » headings: the lead, then one section per heading. */
function sections(markdown: string) {
  const [lead, ...rest] = markdown.split(/^## /m);
  return {
    lead: lead.trim(),
    parts: rest.map((part) => {
      const [title, ...body] = part.split('\n');
      return { title: title.trim(), body: body.join('\n').trim() };
    }),
  };
}

export function Documentation() {
  const docs = useDocs();
  const navigate = useNavigate();
  const { owner = '', slug = '' } = useParams();
  if (docs.error) return <ErrorAlert error={docs.error} />;
  if (!docs.data) {
    return (
      <Center py="xl">
        <Loader />
      </Center>
    );
  }
  const all = groups(docs.data);
  const group = all.find((item) => item.owner === owner);
  const page = group?.pages.find((item) => item.slug === slug);
  if (!group || !page) {
    const first = all.find((item) => item.pages.length > 0);
    return first ? <Navigate to={href(first.owner, first.pages[0].slug)} replace /> : null;
  }
  const plugin = docs.data.plugins.find((item) => item.plugin_id === owner);
  const { lead, parts } = sections(page.markdown);
  return (
    <Group align="flex-start" gap="xl" wrap="nowrap">
      <Box w={260} visibleFrom="sm" style={{ flexShrink: 0, position: 'sticky', top: 84 }}>
        <Contents docs={docs.data} owner={owner} slug={slug} />
      </Box>
      <Stack gap="lg" style={{ flex: 1, minWidth: 0, maxWidth: NARROW }}>
        <Select
          hiddenFrom="sm"
          aria-label="Страница документации"
          value={`${owner}/${slug}`}
          onChange={(value) => value && navigate(`/documentation/${value}`)}
          allowDeselect={false}
          data={all.map((item) => ({
            group: item.label,
            items: item.pages.map((p) => ({ value: `${item.owner}/${p.slug}`, label: p.title })),
          }))}
        />
        <PageHeader
          title={page.title}
          meta={plugin ? `Плагин «${plugin.label}», версия ${plugin.version}` : 'Платформа'}
        />
        {lead && (
          <PageSection>
            <Markdown>{lead}</Markdown>
          </PageSection>
        )}
        {parts.map((part) => (
          <PageSection key={part.title} title={part.title}>
            <Markdown>{part.body}</Markdown>
          </PageSection>
        ))}
      </Stack>
    </Group>
  );
}
