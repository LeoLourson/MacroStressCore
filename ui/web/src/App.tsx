import { Center, Loader, MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { lazy, Suspense, useState, type ReactNode } from 'react';
import { createBrowserRouter, Navigate, RouterProvider } from 'react-router';
import { ApiError } from './api/client';
import { SessionProvider } from './auth/session';
import { SignedInLayout } from './components/Layout';
import { Login } from './pages/Login';
import { RunsList } from './pages/RunsList';
import { resolveVariables, theme } from './theme';

// The list of stress tests is the landing page; everything else loads when it is opened, so
// the graph canvas and the portfolio editor are not parsed before they are needed.
const NewRun = lazy(() => import('./pages/NewRun').then((m) => ({ default: m.NewRun })));
const PortfolioEditor = lazy(() => import('./pages/PortfolioEditor').then((m) => ({ default: m.PortfolioEditor })));
const Portfolios = lazy(() => import('./pages/Portfolios').then((m) => ({ default: m.Portfolios })));
const Documentation = lazy(() => import('./pages/Documentation').then((m) => ({ default: m.Documentation })));
const RunPage = lazy(() => import('./pages/run/RunPage').then((m) => ({ default: m.RunPage })));

function page(element: ReactNode) {
  return (
    <Suspense
      fallback={
        <Center py="xl">
          <Loader />
        </Center>
      }
    >
      {element}
    </Suspense>
  );
}

const router = createBrowserRouter([
  { path: '/login', element: <Login /> },
  {
    element: <SignedInLayout />,
    children: [
      { path: '/', element: <RunsList /> },
      { path: '/new', element: page(<NewRun />) },
      { path: '/portfolios', element: page(<Portfolios />) },
      { path: '/portfolios/new', element: page(<PortfolioEditor />) },
      { path: '/runs/:runId', element: page(<RunPage />) },
      { path: '/documentation', element: page(<Documentation />) },
      { path: '/documentation/:owner/:slug', element: page(<Documentation />) },
      { path: '*', element: <Navigate to="/" replace /> },
    ],
  },
], { basename: import.meta.env.BASE_URL });

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // A 4xx will not heal by asking again; a lost connection may.
        retry: (count, error) => !(error instanceof ApiError && error.status >= 400 && error.status < 500) && count < 2,
        refetchOnWindowFocus: false,
      },
    },
  });
}

export function App() {
  const [queryClient] = useState(makeQueryClient);
  return (
    <MantineProvider theme={theme} defaultColorScheme="light" cssVariablesResolver={resolveVariables}>
      <Notifications position="top-right" />
      <QueryClientProvider client={queryClient}>
        <SessionProvider>
          <RouterProvider router={router} />
        </SessionProvider>
      </QueryClientProvider>
    </MantineProvider>
  );
}
