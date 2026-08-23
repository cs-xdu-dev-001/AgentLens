import {execFile} from 'node:child_process';
import {readdir} from 'node:fs/promises';
import {relative, resolve, sep} from 'node:path';
import {promisify} from 'node:util';
import Fuse from 'fuse.js';

const execFileAsync = promisify(execFile);
const MAX_INDEX_PATHS = 10_000;
const MAX_SUGGESTIONS = 15;
const SKIPPED_DIRECTORIES = new Set([
  '.git', '.hg', '.jj', '.svn', '.tmp', '.venv', 'build', 'dist', 'node_modules',
]);

function normalizedPath(value) {
  return String(value ?? '').replaceAll(sep, '/').replace(/^\.\//, '').replace(/^\/+|\/+$/g, '');
}

function isSensitivePath(value) {
  return normalizedPath(value).split('/').some(part => {
    const lowered = part.toLowerCase();
    return lowered === '.git'
      || lowered === '.ssh'
      || lowered === '.tmp'
      || lowered === 'id_rsa'
      || lowered === 'id_ed25519'
      || lowered === '.env'
      || lowered.startsWith('.env.');
  });
}

function visiblePath(value) {
  const path = normalizedPath(value);
  const parts = path.split('/').map(part => part.toLowerCase());
  return path
    && !path.startsWith('../')
    && !isSensitivePath(path)
    && !parts.some(part => SKIPPED_DIRECTORIES.has(part));
}

function directoryEntries(paths) {
  const directories = new Set();
  for (const path of paths) {
    const parts = path.split('/');
    for (let index = 1; index < parts.length; index += 1) {
      directories.add(`${parts.slice(0, index).join('/')}/`);
    }
  }
  return [...directories];
}

async function gitPaths(root) {
  try {
    const {stdout} = await execFileAsync(
      'git',
      ['-c', 'core.quotepath=false', 'ls-files', '--cached', '--others', '--exclude-standard'],
      {cwd: root, encoding: 'utf8', timeout: 5_000, windowsHide: true, maxBuffer: 8 * 1024 * 1024},
    );
    return stdout.split(/\r?\n/u).filter(visiblePath).slice(0, MAX_INDEX_PATHS);
  } catch {
    return null;
  }
}

async function walkedPaths(root) {
  const files = [];
  const pending = [root];
  while (pending.length && files.length < MAX_INDEX_PATHS) {
    const directory = pending.shift();
    let entries = [];
    try {
      entries = await readdir(directory, {withFileTypes: true});
    } catch {
      continue;
    }
    for (const entry of entries) {
      if (entry.isSymbolicLink()) continue;
      const absolute = resolve(directory, entry.name);
      const path = normalizedPath(relative(root, absolute));
      if (!visiblePath(path)) continue;
      if (entry.isDirectory()) {
        if (!SKIPPED_DIRECTORIES.has(entry.name.toLowerCase())) pending.push(absolute);
      } else if (entry.isFile()) {
        files.push(path);
      }
      if (files.length >= MAX_INDEX_PATHS) break;
    }
  }
  return files;
}

export async function loadWorkspacePaths(workspaceRoot) {
  const root = resolve(String(workspaceRoot ?? '').trim() || '.');
  const files = await gitPaths(root) ?? await walkedPaths(root);
  return [...new Set([...directoryEntries(files), ...files])];
}

export function fileMentionAtCursor(input, cursorOffset = String(input ?? '').length) {
  const value = String(input ?? '');
  const cursor = Math.max(0, Math.min(value.length, Number(cursorOffset) || 0));
  const prefix = value.slice(0, cursor);
  const quoted = prefix.match(/(?:^|\s)(@"([^"\n]*))$/u);
  const bare = prefix.match(/(?:^|\s)(@([^\s@]*))$/u);
  const match = quoted ?? bare;
  if (!match) return null;
  const token = match[1];
  return {
    start: cursor - token.length,
    end: cursor,
    token,
    query: match[2] ?? '',
    quoted: Boolean(quoted),
  };
}

export function workspaceFileSuggestions(paths, mention, limit = MAX_SUGGESTIONS) {
  if (!mention) return [];
  const available = [...new Set((paths ?? []).filter(visiblePath))];
  const query = normalizedPath(mention.query).toLowerCase();
  const matched = query
    ? new Fuse(available.map(path => ({path})), {
      threshold: 0.35,
      location: 0,
      distance: 120,
      ignoreLocation: false,
      keys: ['path'],
    }).search(query, {limit}).map(result => result.item.path)
    : available.filter(path => !path.slice(0, -1).includes('/')).slice(0, limit);
  return matched.slice(0, limit).map(path => ({
    value: `@${path}`,
    path,
    kind: 'file',
    source: 'file',
    description: path.endsWith('/') ? '目录' : '文件',
  }));
}

export function longestSuggestionPrefix(suggestions) {
  const values = (suggestions ?? []).map(item => String(item?.path ?? ''));
  if (!values.length) return '';
  let prefix = values[0];
  for (const value of values.slice(1)) {
    let index = 0;
    while (index < prefix.length && index < value.length && prefix[index] === value[index]) index += 1;
    prefix = prefix.slice(0, index);
    if (!prefix) break;
  }
  return prefix;
}

export function applyFileMention(input, mention, path, {complete = true} = {}) {
  const value = String(input ?? '');
  const filePath = String(path ?? '');
  const needsQuotes = filePath.includes(' ');
  const replacement = needsQuotes ? `@"${filePath}"` : `@${filePath}`;
  const suffix = complete ? ' ' : '';
  const next = value.slice(0, mention.start) + replacement + suffix + value.slice(mention.end);
  return {value: next, cursor: mention.start + replacement.length + suffix.length};
}
