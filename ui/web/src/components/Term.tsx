import { Tooltip } from '@mantine/core';
import type { ReactNode } from 'react';
import { GLOSSARY } from '../lib/labels';

/** A domain term with its one-sentence explanation on hover. */
export function Term({ name, children }: { name: keyof typeof GLOSSARY | string; children?: ReactNode }) {
  const hint = GLOSSARY[name];
  if (!hint) return <>{children ?? name}</>;
  return (
    <Tooltip label={hint}>
      <span className="term" tabIndex={0}>
        {children ?? name}
      </span>
    </Tooltip>
  );
}
