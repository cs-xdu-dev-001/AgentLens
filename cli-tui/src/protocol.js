import {EventEmitter} from 'node:events';
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import stripAnsi from 'strip-ansi';

export const PROTOCOL_VERSION = 2;

export function sanitizeTerminalText(value) {
  return stripAnsi(String(value ?? '')).replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g, '');
}

const SECRET_PATTERNS = [
  [/-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----/g, '[已隐藏私钥]'],
  [/\bsk-[A-Za-z0-9_-]{12,}\b/g, '[已隐藏]'],
  [/\bBearer\s+[A-Za-z0-9._~-]{8,}\b/gi, 'Bearer [已隐藏]'],
  [/(api[_-]?key|token|password|secret|cookie|authorization|private[_-]?key)(\s*[:=]\s*)\S+/gi, '$1$2[已隐藏]'],
  [/(--(?:api[-_]?key|token|password|secret|cookie|authorization|private[-_]?key))(?:=|\s+)\S+/gi, '$1=[已隐藏]'],
  [/([a-z][a-z0-9+.-]*:\/\/[^:\s/]+:)[^@\s/]+@/gi, '$1[已隐藏]@'],
];

export function redact(value, limit = 500) {
  let text = sanitizeTerminalText(value);
  for (const [pattern, replacement] of SECRET_PATTERNS) text = text.replace(pattern, replacement);
  return text.length > limit ? `${text.slice(0, limit)}…` : text;
}

export class RuntimeClient extends EventEmitter {
  constructor({python, config}) {
    super();
    this.python = python;
    this.config = config;
    this.child = null;
    this.stderr = [];
  }

  start() {
    if (this.child) return;
    this.child = spawn(this.python, [
      '-m',
      'knowflow.tui.ink_bridge',
      '--config',
      JSON.stringify(this.config),
    ], {
      stdio: ['pipe', 'pipe', 'pipe'],
      env: process.env,
    });
    const lines = createInterface({input: this.child.stdout});
    lines.on('line', line => {
      try {
        const event = JSON.parse(line);
        if (event && typeof event === 'object') this.emit('message', event);
      } catch {
        this.emit('message', {type: 'protocol_error', message: 'Python运行时返回了无效消息。'});
      }
    });
    this.child.stderr.on('data', chunk => {
      const lines = redact(chunk, 2000).split(/\r?\n/).filter(Boolean);
      this.stderr.push(...lines);
      this.stderr = this.stderr.slice(-5);
    });
    this.child.on('error', error => {
      this.emit('message', {type: 'startup_failed', message: redact(error.message)});
    });
    this.child.on('exit', code => {
      this.emit('exit', {
        code: Number(code ?? 1),
        detail: this.stderr.at(-1) ?? '',
      });
      this.child = null;
    });
  }

  send(message) {
    if (!this.child?.stdin?.writable) return false;
    this.child.stdin.write(`${JSON.stringify(message)}\n`);
    return true;
  }

  close() {
    if (!this.child) return;
    this.send({type: 'shutdown'});
    const child = this.child;
    setTimeout(() => {
      if (child.exitCode === null) child.kill('SIGTERM');
    }, 500).unref();
  }
}
