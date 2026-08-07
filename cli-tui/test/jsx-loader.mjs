import {readFile} from 'node:fs/promises';
import {transform} from 'esbuild';

export async function load(url, context, nextLoad) {
  if (!url.endsWith('.jsx')) return nextLoad(url, context);
  const source = await readFile(new URL(url), 'utf8');
  const result = await transform(source, {
    format: 'esm',
    jsx: 'automatic',
    loader: 'jsx',
    sourcemap: 'inline',
    target: 'node22',
  });
  return {format: 'module', source: result.code, shortCircuit: true};
}
