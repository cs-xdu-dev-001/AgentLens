import React from 'react';
import {render} from 'ink';
import {MouseProvider} from '@ink-tools/ink-mouse';
import {App} from './app.jsx';
import {RuntimeClient} from './protocol.js';

if (process.argv.includes('--self-test')) {
  process.stdout.write('knowflow-ink-ok\n');
  process.exit(0);
}

function runtimeConfig() {
  try {
    const value = JSON.parse(process.env.KNOWFLOW_RUNTIME_CONFIG ?? '{}');
    return value && typeof value === 'object' ? value : {};
  } catch {
    return {};
  }
}

function envEnabled(value) {
  return ['1', 'true', 'yes', 'on'].includes(String(value ?? '').trim().toLowerCase());
}

const config = runtimeConfig();
const python = process.env.KNOWFLOW_RUNTIME_PYTHON || 'python3';
const version = process.env.KNOWFLOW_CLI_VERSION || 'development';
const mouseEnabled = envEnabled(process.env.KNOWFLOW_CLI_MOUSE);
const client = new RuntimeClient({python, config});

const instance = render(
  <MouseProvider autoEnable={mouseEnabled}>
    <App client={client} version={version} assumeYes={Boolean(config.assumeYes)} mouseEnabled={mouseEnabled} />
  </MouseProvider>,
  {exitOnCtrlC: false, alternateScreen: true},
);

process.once('SIGTERM', () => {
  client.close();
  instance.unmount();
  process.exit(143);
});
