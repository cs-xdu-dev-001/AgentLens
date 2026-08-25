import React from 'react';
import {render} from 'ink';
import {MouseProvider} from '@ink-tools/ink-mouse';
import {App, resolveTerminalMode} from './app.jsx';
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
const {fullscreenEnabled, mouseEnabled} = resolveTerminalMode(process.env);
const client = new RuntimeClient({python, config});
const CONFIGURE_EXIT_CODE = 42;
let instance;

const requestConfigure = () => {
  client.close();
  instance?.unmount();
  setImmediate(() => process.exit(CONFIGURE_EXIT_CODE));
};

instance = render(
  <MouseProvider autoEnable={mouseEnabled}>
    <App
      client={client}
      version={version}
      workspaceRoot={String(config.workspaceRoot || '')}
      assumeYes={Boolean(config.assumeYes)}
      fullscreenEnabled={fullscreenEnabled}
      mouseEnabled={mouseEnabled}
      startupAction={String(config.startupAction || '')}
      onConfigure={config.mode === 'remote' ? null : requestConfigure}
    />
  </MouseProvider>,
  {
    exitOnCtrlC: false,
    alternateScreen: fullscreenEnabled,
    incrementalRendering: true,
    maxFps: 30,
  },
);

process.once('SIGTERM', () => {
  client.close();
  instance.unmount();
  process.exit(143);
});
