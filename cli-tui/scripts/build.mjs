import {build} from 'esbuild';
import {mkdir, readFile, readdir, writeFile} from 'node:fs/promises';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const output = resolve(root, '..', 'backend', 'knowflow', 'ink_tui', 'index.mjs');
const notices = resolve(dirname(output), 'THIRD_PARTY_LICENSES.txt');

await mkdir(dirname(output), {recursive: true});
const result = await build({
  entryPoints: [resolve(root, 'src', 'index.jsx')],
  outfile: output,
  bundle: true,
  platform: 'node',
  format: 'esm',
  target: ['node22'],
  jsx: 'automatic',
  sourcemap: false,
  minify: true,
  legalComments: 'none',
  metafile: true,
  alias: {
    'react-devtools-core': resolve(root, 'src', 'react-devtools-core-stub.js'),
  },
  banner: {
    js: '#!/usr/bin/env node\nimport {createRequire as __createRequire} from "node:module"; const require = __createRequire(import.meta.url);',
  },
});
const bundledSource = await readFile(output, 'utf8');
await writeFile(output, bundledSource.replace(/[\t ]+$/gm, ''), 'utf8');

const packages = new Map();
for (const input of Object.keys(result.metafile.inputs)) {
  const absolute = resolve(root, input).replaceAll('\\', '/');
  const marker = '/node_modules/';
  const markerIndex = absolute.lastIndexOf(marker);
  if (markerIndex < 0) continue;
  const packageRoot = absolute.slice(0, markerIndex + marker.length);
  const parts = absolute.slice(markerIndex + marker.length).split('/');
  const name = parts[0].startsWith('@') ? `${parts[0]}/${parts[1]}` : parts[0];
  const directory = resolve(packageRoot, name);
  packages.set(`${name}:${directory}`, {name, directory});
}

const sections = [
  'AgentLens Ink TUI third-party notices',
  'Generated from the packages included in the bundled terminal UI.',
];
for (const {name, directory} of [...packages.values()].sort((a, b) => a.name.localeCompare(b.name))) {
  let metadata = {};
  try {
    metadata = JSON.parse(await readFile(resolve(directory, 'package.json'), 'utf8'));
  } catch {}
  let licenseText = '';
  try {
    const files = await readdir(directory);
    const licenseFile = files.find(file => /^licen[cs]e(?:\.|$)/i.test(file));
    if (licenseFile) licenseText = await readFile(resolve(directory, licenseFile), 'utf8');
  } catch {}
  sections.push(
    `\n${'='.repeat(72)}\n${name} ${metadata.version ?? ''}\nLicense: ${metadata.license ?? 'see package'}\n${licenseText.trim() || 'See the package repository for the complete license text.'}`,
  );
}
await writeFile(notices, `${sections.join('\n')}\n`, 'utf8');

console.log(`Built ${output}`);
console.log(`Wrote ${notices}`);
