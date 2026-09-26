import { useMemo } from 'react';
import { useTrace } from '../../api/queries';
import type { RunStatus } from '../../api/types';
import { entriesOf } from '../../lib/provenance';
import { hasReport } from '../../lib/stages';

/** The origins of the run's report numbers, read once per state of the run. */
export function useOrigins(status: RunStatus) {
  const trace = useTrace(status, hasReport(status));
  const entries = useMemo(() => entriesOf(trace.data), [trace.data]);
  return { entries, trace };
}
