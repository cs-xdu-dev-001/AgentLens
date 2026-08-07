import React from 'react';
import {render} from 'ink';
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

const config = runtimeConfig();
const python = process.env.KNOWFLOW_RUNTIME_PYTHON || 'python3';
const version = process.env.KNOWFLOW_CLI_VERSION || 'development';
const client = new RuntimeClient({python, config});

const instance = render(
  <App client={client} version={version} assumeYes={Boolean(config.assumeYes)} />,
  {exitOnCtrlC: false},
);

process.once('SIGTERM', () => {
  client.close();
  instance.unmount();
  process.exit(143);
});
