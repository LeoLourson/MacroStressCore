// UI plugins found at build time: every src/plugins/<name>/index.tsx (see sdk.ts).
import type { ComponentType } from 'react';
import type { PositionViewProps, UiPlugin } from './sdk';

const modules = import.meta.glob<{ default: UiPlugin }>('./*/index.tsx', { eager: true });

export const UI_PLUGINS: UiPlugin[] = Object.values(modules)
  .map((module) => module.default)
  .sort((a, b) => a.plugin_id.localeCompare(b.plugin_id));

const COMPONENTS: Record<string, ComponentType<PositionViewProps>> = Object.assign(
  {},
  ...UI_PLUGINS.map((plugin) => plugin.views),
);

/** The UI plugin's component of a result view, or null: the standard view renders it then. */
export function viewComponent(component: string | null | undefined): ComponentType<PositionViewProps> | null {
  return component ? (COMPONENTS[component] ?? null) : null;
}

export function pluginNotes(): ComponentType<{ artifacts: import('../api/types').Artifacts }>[] {
  return UI_PLUGINS.flatMap((plugin) => (plugin.notes ? [plugin.notes] : []));
}
