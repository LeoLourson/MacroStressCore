// The contract of a UI plugin: a richer view of the results of one server plugin.
//
// A UI plugin lives in src/plugins/<name>/ with two files:
//   plugin.json — { "plugin_id", "versions", "components": [...] }: the server plugin it
//                 renders, the range of its versions it understands, the view components
//                 it implements (ResultView.component of the catalog);
//   index.tsx   — a default export of UiPlugin with the same id and components.
// It is found by import.meta.glob (src/plugins/index.ts); scripts/check-plugins.mjs checks
// plugin.json against src/plugins/manifest.json, generated from the server's registry, and
// fails the build on a mismatch. A component the server declares without a UI plugin is
// rendered by the standard view from the blocks of its ResultView.
import type { ComponentType } from 'react';
import type { ResultView } from '../api/catalog';
import type { Artifacts, CalculationResult, PositionContext } from '../api/types';
import type { Entries } from '../lib/provenance';

export interface PositionViewProps {
  result: CalculationResult;
  context: PositionContext | undefined;
  view: ResultView;
  artifacts: Artifacts;
  /** Origins of the report's numbers, by metric path. */
  entries: Entries;
  /** Scenario parameter name -> the label the analyst confirmed. */
  shocks: Record<string, string>;
}

export interface UiPluginMeta {
  plugin_id: string;
  /** Server plugin versions this UI understands: ">=3.2.0 <4.0.0". */
  versions: string;
  components: string[];
}

/** What a plugin reads to name the machine identifiers of a run in plain words. */
export interface GlossContext {
  artifacts: Artifacts;
}

export interface UiPlugin extends UiPluginMeta {
  /** View components by ResultView.component id. */
  views: Record<string, ComponentType<PositionViewProps>>;
  /** Notes the portfolio tab and the report show beside the numbers (a calibration in force). */
  notes?: ComponentType<{ artifacts: Artifacts }>;
  /**
   * Plain-language names of the plugin's identifiers a report may carry (a credit
   * instrument's covenants): [identifier, words] pairs. The report shows them beside the
   * identifier, never instead of it.
   */
  glosses?: (context: GlossContext) => Iterable<[string, string]>;
  /** Terms of the plugin's screens, explained in one sentence each (<Term name="…">). */
  glossary?: Record<string, string>;
}
