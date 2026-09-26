// Build-time compatibility of the UI plugins with the server plugins.
//
// src/plugins/manifest.json is generated from the server's registry
// (`uv run msa-plugin ui-manifest`): the installed plugins, their versions and the view
// components their result views name. Every UI plugin (src/plugins/<name>/plugin.json)
// must render an installed plugin, understand its version, and implement only components
// that plugin declares. A declared component without a UI plugin is fine: the standard view
// renders it from the blocks of its ResultView. Any mismatch fails the build.
import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..', 'src', 'plugins');
const manifest = JSON.parse(readFileSync(join(root, 'manifest.json'), 'utf8'));

function parse(version) {
  const parts = version.split('.').map(Number);
  if (parts.length !== 3 || parts.some(Number.isNaN)) throw new Error(`not a version: ${version}`);
  return parts;
}

function compare(a, b) {
  for (let i = 0; i < 3; i += 1) if (a[i] !== b[i]) return a[i] - b[i];
  return 0;
}

/** ">=3.2.0 <4.0.0": every comparator must hold. */
function satisfies(version, range) {
  const v = parse(version);
  return range
    .trim()
    .split(/\s+/)
    .every((comparator) => {
      const match = /^(>=|<=|>|<|=)?(\d+\.\d+\.\d+)$/.exec(comparator);
      if (!match) throw new Error(`not a range: ${range}`);
      const c = compare(v, parse(match[2]));
      return { '>=': c >= 0, '<=': c <= 0, '>': c > 0, '<': c < 0, '=': c === 0 }[match[1] ?? '='];
    });
}

const problems = [];
const implemented = new Set();
for (const entry of readdirSync(root, { withFileTypes: true })) {
  if (!entry.isDirectory()) continue;
  const file = join(root, entry.name, 'plugin.json');
  if (!existsSync(file)) {
    problems.push(`src/plugins/${entry.name}: no plugin.json`);
    continue;
  }
  const meta = JSON.parse(readFileSync(file, 'utf8'));
  const version = manifest.plugins[meta.plugin_id];
  if (!version) {
    problems.push(`${entry.name}: server plugin ${meta.plugin_id} is not installed`);
    continue;
  }
  try {
    if (!satisfies(version, meta.versions)) {
      problems.push(`${entry.name}: renders ${meta.plugin_id} ${meta.versions}, the server has ${version}`);
    }
  } catch (error) {
    problems.push(`${entry.name}: ${error.message}`);
  }
  for (const component of meta.components) {
    implemented.add(component);
    if (manifest.components[component] !== meta.plugin_id) {
      problems.push(`${entry.name}: ${meta.plugin_id} declares no view component ${component}`);
    }
  }
}

for (const [component, pluginId] of Object.entries(manifest.components)) {
  if (!implemented.has(component)) {
    console.log(`check-plugins: ${component} (${pluginId}) has no UI plugin; the standard view renders it`);
  }
}
if (problems.length) {
  console.error('check-plugins: the UI plugins do not match the server plugins:');
  for (const problem of problems) console.error(`  - ${problem}`);
  console.error('Regenerate the manifest with `uv run msa-plugin ui-manifest` or update src/plugins/*/plugin.json.');
  process.exit(1);
}
console.log(`check-plugins: ok (sdk ${manifest.sdk_version}, ${implemented.size} UI components)`);
