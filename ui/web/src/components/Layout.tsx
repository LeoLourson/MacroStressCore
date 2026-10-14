import {
  AppShell,
  Avatar,
  Box,
  Center,
  Container,
  Group,
  Loader,
  Menu,
  SegmentedControl,
  Text,
  Tooltip,
  UnstyledButton,
} from '@mantine/core';
import { IconChevronDown, IconLogout, IconUserCircle } from '@tabler/icons-react';
import { Link, NavLink, Navigate, Outlet, useLocation } from 'react-router';
import type { Mode } from '../api/types';
import { externalLlm, useSession } from '../auth/session';
import { MODES, PROVIDERS, ROLES, label } from '../lib/labels';

function Logo() {
  return (
    <Text fw={600} size="lg" c="dark.8">
      MacroStress
    </Text>
  );
}

/** Which language model builds the graphs, always in view; an external one limits the data. */
function LlmBadge({ external }: { external: boolean }) {
  const { me } = useSession();
  const llm = me?.llm;
  if (!llm) return null;
  const name = label(PROVIDERS, llm.provider);
  const text = external ? `${name} · для демонстрации` : llm.provider === 'mock' ? name : `${name} · ${llm.model}`;
  const tip = external
    ? `Внешняя языковая модель ${llm.model} (${llm.base_url}): работа только на синтетических демо-портфелях.`
    : llm.provider === 'mock'
      ? 'Граф строится по фикстуре без языковой модели.'
      : `Модель ${llm.model} на ${llm.base_url}, внутри периметра.`;
  return (
    <Tooltip label={tip} multiline maw={360}>
      <Text size="xs" c="dimmed" visibleFrom="md">
        LLM: {text}
      </Text>
    </Tooltip>
  );
}

function UserMenu() {
  const { me, config, apiKey, signIn, signOut } = useSession();
  if (!me) return null;
  const roles = Object.entries(config.demo_keys ?? {});
  return (
    <Menu position="bottom-end" width={260} shadow="md">
      <Menu.Target>
        <UnstyledButton aria-label="Меню пользователя">
          <Group gap={8} wrap="nowrap">
            <Avatar size={30} color="steel" radius="xl">
              <IconUserCircle size={20} />
            </Avatar>
            <Box visibleFrom="sm">
              <Text size="sm" fw={500} lh={1.2}>
                {label(ROLES, me.role)}
              </Text>
              <Text size="xs" c="dimmed" lh={1.2}>
                {me.actor}
              </Text>
            </Box>
            <IconChevronDown size={14} />
          </Group>
        </UnstyledButton>
      </Menu.Target>
      <Menu.Dropdown>
        {roles.length > 0 && (
          <>
            <Menu.Label>Войти в другой роли (демо)</Menu.Label>
            {roles.map(([role, key]) => (
              <Menu.Item key={role} disabled={key === apiKey} onClick={() => signIn(key)}>
                {label(ROLES, role)}
                {key === apiKey ? ' — сейчас' : ''}
              </Menu.Item>
            ))}
            <Menu.Divider />
          </>
        )}
        <Menu.Item leftSection={<IconLogout size={16} />} onClick={signOut}>
          Выйти
        </Menu.Item>
      </Menu.Dropdown>
    </Menu>
  );
}

/** A section of the app; the current one is marked in steel, the others stay quiet. */
function NavItem({ to, label: text, match }: { to: string; label: string; match: (path: string) => boolean }) {
  const active = match(useLocation().pathname);
  return (
    <Text
      component={NavLink}
      to={to}
      size="sm"
      fw={active ? 600 : 500}
      c={active ? 'steel.8' : 'gray.7'}
      td="none"
      aria-current={active ? 'page' : undefined}
    >
      {text}
    </Text>
  );
}

function Header() {
  const { me, mode, modes, setMode } = useSession();
  const external = externalLlm(me);
  return (
    <Container size="xl" h="100%">
      <Group h="100%" justify="space-between" wrap="nowrap">
        <Group gap="xl" wrap="nowrap">
          <Link to="/" style={{ textDecoration: 'none' }}>
            <Logo />
          </Link>
          <Group gap="lg" wrap="nowrap" visibleFrom="sm">
            <NavItem to="/" label="Стресс-тесты" match={(path) => !path.startsWith('/portfolios')} />
            <NavItem to="/portfolios" label="Портфели" match={(path) => path.startsWith('/portfolios')} />
          </Group>
        </Group>
        <Group gap="md" wrap="nowrap">
          <LlmBadge external={!!external} />
          {modes.length > 1 && (
            <SegmentedControl
              size="xs"
              value={mode}
              onChange={(value) => setMode(value as Mode)}
              data={modes.map((m) => ({ value: m, label: MODES[m] }))}
            />
          )}
          <UserMenu />
        </Group>
      </Group>
    </Container>
  );
}

/** Pages of a signed-in person: without a key they lead to the sign-in page. */
export function SignedInLayout() {
  const { apiKey, me, meLoading, meError } = useSession();
  const location = useLocation();
  if (!apiKey || meError) {
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  }
  if (meLoading || !me) {
    return (
      <Center h="100vh">
        <Loader />
      </Center>
    );
  }
  return (
    <AppShell header={{ height: 60 }} padding={0}>
      <AppShell.Header>
        <Header />
      </AppShell.Header>
      <AppShell.Main>
        <Container size="xl" py="lg" px={{ base: 'md', sm: 'lg' }}>
          <Outlet />
        </Container>
      </AppShell.Main>
    </AppShell>
  );
}
