import React from 'react';
import {Box, Text} from 'ink';

const ACCENT = '#d97757';
const PRIMARY = '#e5e7eb';
const MUTED = '#8b8b8b';
const SUCCESS = '#6fba82';
const ERROR = '#d96b6b';

export const LOCAL_MODEL_CONFIG_FIELDS = Object.freeze([
  {id: 'baseUrl', label: 'API地址'},
  {id: 'modelName', label: '模型名称'},
  {id: 'apiMode', label: '接口协议'},
  {id: 'apiKey', label: 'API Key'},
  {id: 'save', label: '测试并保存'},
]);

export function normalizeLocalModelConfig(value = {}) {
  const apiMode = String(value.apiMode || 'responses') === 'chat_completions'
    ? 'chat_completions'
    : 'responses';
  return {
    provider: String(value.provider || 'custom'),
    baseUrl: String(value.baseUrl || 'https://api.openai.com/v1'),
    modelName: String(value.modelName || 'gpt-5-mini'),
    apiMode,
    apiKey: '',
    hasApiKey: Boolean(value.hasApiKey),
    overriddenFields: value.overriddenFields && typeof value.overriddenFields === 'object'
      ? {...value.overriddenFields}
      : {},
  };
}

export function localModelConfigPayload(value = {}) {
  const payload = {
    provider: String(value.provider || 'custom'),
    baseUrl: String(value.baseUrl || '').trim(),
    modelName: String(value.modelName || '').trim(),
    apiMode: value.apiMode === 'chat_completions' ? 'chat_completions' : 'responses',
  };
  const apiKey = String(value.apiKey || '').trim();
  if (apiKey) payload.apiKey = apiKey;
  return payload;
}

export function editLocalModelConfigText(value, cursor, input = {}) {
  const text = String(value ?? '');
  const offset = Math.max(0, Math.min(Number(cursor) || 0, text.length));
  const key = input.key || {};
  const character = String(input.character || '');
  if (key.leftArrow) return {value: text, cursor: Math.max(0, offset - 1)};
  if (key.rightArrow) return {value: text, cursor: Math.min(text.length, offset + 1)};
  if (key.home) return {value: text, cursor: 0};
  if (key.end) return {value: text, cursor: text.length};
  if (key.backspace) {
    if (!offset) return {value: text, cursor: offset};
    return {value: text.slice(0, offset - 1) + text.slice(offset), cursor: offset - 1};
  }
  if (key.delete) {
    return {value: text.slice(0, offset) + text.slice(offset + 1), cursor: offset};
  }
  if (!character || key.ctrl || key.meta || key.return || key.tab || key.escape) {
    return {value: text, cursor: offset};
  }
  const safe = character.replace(/[\r\n\u0000-\u001f\u007f]/g, '');
  if (!safe) return {value: text, cursor: offset};
  return {
    value: (text.slice(0, offset) + safe + text.slice(offset)).slice(0, 2_000),
    cursor: Math.min(2_000, offset + safe.length),
  };
}

function displayText(value, cursor, active, masked = false) {
  const text = masked ? '•'.repeat(Math.min(24, String(value || '').length)) : String(value || '');
  if (!active) return text;
  const safeCursor = masked
    ? Math.min(text.length, Number(cursor) || 0)
    : Math.max(0, Math.min(Number(cursor) || 0, text.length));
  return `${text.slice(0, safeCursor)}▏${text.slice(safeCursor)}`;
}

function ConfigRow({active, label, value, locked = ''}) {
  return (
    <Box>
      <Text color={active ? ACCENT : MUTED}>{active ? '❯ ' : '  '}</Text>
      <Box width={14}><Text color={active ? PRIMARY : MUTED} bold={active}>{label}</Text></Box>
      <Text color={locked ? MUTED : (active ? PRIMARY : MUTED)} wrap="truncate-end">
        {value || '—'}{locked ? `  由${locked}控制` : ''}
      </Text>
    </Box>
  );
}

export const LocalModelConfigPanel = React.memo(function LocalModelConfigPanel({
  draft,
  selected,
  cursor,
  loading,
  saving,
  error,
  notice,
}) {
  const activeField = LOCAL_MODEL_CONFIG_FIELDS[selected]?.id || 'baseUrl';
  const locked = draft?.overriddenFields || {};
  const secret = draft?.apiKey
    ? displayText(draft.apiKey, cursor, activeField === 'apiKey', true)
    : draft?.hasApiKey
      ? '••••••••  已保存，留空保持不变'
      : '尚未填写';
  const mode = draft?.apiMode === 'chat_completions'
    ? 'Responses   [Chat Completions]'
    : '[Responses]   Chat Completions';

  return (
    <Box flexDirection="column" borderStyle="round" borderColor={ACCENT} paddingX={2} paddingY={1} marginTop={1}>
      <Box justifyContent="space-between">
        <Text bold>配置本地模型</Text>
        <Text color={saving ? ACCENT : MUTED}>
          {saving ? '正在测试连接' : `${selected + 1}/${LOCAL_MODEL_CONFIG_FIELDS.length}`}
        </Text>
      </Box>
      {loading ? <Text color={MUTED}>正在读取本机配置…</Text> : (
        <>
          <ConfigRow
            active={activeField === 'baseUrl'}
            label="API地址"
            locked={locked.base_url}
            value={displayText(draft?.baseUrl, cursor, activeField === 'baseUrl')}
          />
          <ConfigRow
            active={activeField === 'modelName'}
            label="模型名称"
            locked={locked.model_name}
            value={displayText(draft?.modelName, cursor, activeField === 'modelName')}
          />
          <ConfigRow
            active={activeField === 'apiMode'}
            label="接口协议"
            locked={locked.api_mode}
            value={mode}
          />
          <ConfigRow
            active={activeField === 'apiKey'}
            label="API Key"
            locked={locked.api_key}
            value={secret}
          />
          <Box marginTop={1}>
            <Text color={activeField === 'save' ? SUCCESS : MUTED} bold={activeField === 'save'}>
              {activeField === 'save' ? '❯ ' : '  '}✓ 测试并保存
            </Text>
          </Box>
        </>
      )}
      {error ? <Text color={ERROR} wrap="wrap">{error}</Text> : null}
      {notice ? <Text color={SUCCESS}>{notice}</Text> : null}
      <Text color={MUTED}>↑↓选择 · ←→编辑/切换协议 · Enter下一项/保存 · Esc取消</Text>
    </Box>
  );
});
