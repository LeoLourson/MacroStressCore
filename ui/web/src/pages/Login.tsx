import { Alert, Button, Center, Paper, PasswordInput, Stack, Text, Title } from '@mantine/core';
import { IconChartLine, IconSignature, IconAlertTriangle } from '@tabler/icons-react';
import { useState, type FormEvent } from 'react';
import { Navigate, useLocation } from 'react-router';
import { useSession } from '../auth/session';

const ROLE_BUTTONS: Record<string, { title: string; text: string; Icon: typeof IconChartLine }> = {
  analyst: {
    title: 'Войти как аналитик',
    text: 'Запускает стресс-тесты, проверяет граф влияния и сценарий',
    Icon: IconChartLine,
  },
  risk_manager: {
    title: 'Войти как риск-менеджер',
    text: 'Читает отчёт и принимает решение: утвердить, вернуть или отклонить',
    Icon: IconSignature,
  },
};

export function Login() {
  const { apiKey, me, meError, config, signIn } = useSession();
  const location = useLocation();
  const [key, setKey] = useState('');
  const from = (location.state as { from?: string } | null)?.from ?? '/';
  if (apiKey && me) return <Navigate to={from} replace />;

  const presets = Object.entries(config.demo_keys ?? {});
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (key.trim()) signIn(key.trim());
  };

  return (
    <Center mih="100vh" p="md">
      <Stack w="100%" maw={440} gap="lg">
        <Stack gap={4}>
          <Title order={2}>MacroStress</Title>
          <Text c="dimmed">Оценка влияния макро- и регуляторных событий на кредитный или инвестиционный портфель.</Text>
        </Stack>
        {meError && (
          <Alert icon={<IconAlertTriangle />} color="orange">
            {meError.userMessage}
          </Alert>
        )}
        {presets.length > 0 ? (
          <Stack gap="sm">
            {presets.map(([role, value]) => {
              const view = ROLE_BUTTONS[role] ?? { title: role, text: '', Icon: IconChartLine };
              return (
                <Paper key={role} p={0}>
                  <Button
                    variant="subtle"
                    color="dark"
                    fullWidth
                    h="auto"
                    p="md"
                    justify="flex-start"
                    leftSection={<view.Icon size={28} stroke={1.6} />}
                    onClick={() => signIn(value)}
                  >
                    <Stack gap={4} align="flex-start">
                      <Text fw={600}>{view.title}</Text>
                      <Text size="sm" c="dimmed" fw={400} style={{ whiteSpace: 'normal', textAlign: 'left' }}>
                        {view.text}
                      </Text>
                    </Stack>
                  </Button>
                </Paper>
              );
            })}
          </Stack>
        ) : (
          <Paper p="lg">
            <form onSubmit={submit}>
              <Stack>
                <PasswordInput
                  label="Ключ доступа"
                  description="Личный ключ выдаёт администратор. Права определяются ролью ключа."
                  value={key}
                  onChange={(e) => setKey(e.currentTarget.value)}
                  autoFocus
                />
                <Button type="submit" disabled={!key.trim()}>
                  Войти
                </Button>
              </Stack>
            </form>
          </Paper>
        )}
      </Stack>
    </Center>
  );
}
