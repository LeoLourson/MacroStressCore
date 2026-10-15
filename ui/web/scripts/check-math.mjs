// Build-time check of the documentation of the mathematics: every formula of the platform's
// pages (src/msa/engine/docs) and of each plugin's (src/msa/plugins/<id>/docs) must typeset
// in KaTeX in strict mode, so a page never shows a red formula or raw LaTeX. Russian words
// inside a formula belong in \text{...}. Any failure names the file and the formula.
import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import katex from 'katex';

const repo = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..');
const roots = [join(repo, 'src', 'msa', 'engine', 'docs')];
const plugins = join(repo, 'src', 'msa', 'plugins');
for (const entry of readdirSync(plugins, { withFileTypes: true })) {
  if (entry.isDirectory() && existsSync(join(plugins, entry.name, 'docs'))) roots.push(join(plugins, entry.name, 'docs'));
}

const problems = [];
let count = 0;
function check(file, tex, displayMode) {
  count += 1;
  try {
    katex.renderToString(tex, { displayMode, throwOnError: true, strict: 'error' });
  } catch (error) {
    problems.push(`${relative(repo, file)}: ${error.message}\n    ${tex.trim().split('\n').join('\n    ')}`);
  }
}

for (const root of roots) {
  for (const name of readdirSync(root).filter((n) => n.endsWith('.md'))) {
    const file = join(root, name);
    // Block formulas first, then inline ones outside code spans.
    const text = readFileSync(file, 'utf8').replace(/^\$\$\n([\s\S]*?)\n\$\$$/gm, (_, tex) => {
      check(file, tex, true);
      return '';
    });
    for (const line of text.split('\n')) {
      const plain = line.replace(/`[^`]*`/g, '');
      if (plain.includes('$$')) problems.push(`${relative(repo, file)}: a $$ block must stand on lines of its own`);
      for (const match of plain.matchAll(/\$([^$]+)\$/g)) check(file, match[1], false);
      if ((plain.match(/\$/g) ?? []).length % 2) problems.push(`${relative(repo, file)}: unbalanced $ in «${line.trim()}»`);
    }
  }
}

if (problems.length) {
  console.error(`Formulas of the documentation do not typeset:\n${problems.join('\n')}`);
  process.exit(1);
}
console.log(`documentation formulas: ${count} typeset`);
