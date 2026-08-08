import React, {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {Box, Text, useApp, useInput, useStdout} from 'ink';
import {useOnWheel} from '@ink-tools/ink-mouse';
import {ScrollView} from 'ink-scroll-view';
import stripAnsi from 'strip-ansi';
import {
  commandSuggestions,
  dynamicCommandTask,
  mergeCommands,
  resolveCommand,
} from './commands.js';
import {PROTOCOL_VERSION, redact} from './protocol.js';
import {MarkdownText} from './markdown.jsx';

const ACCENT = '#d97757';
const PRIMARY = '#e5e7eb';
const MUTED = '#8b8b8b';
const SUCCESS = '#6fba82';
const WARNING = '#d9a441';
const ERROR = '#d96b6b';
const SPINNER = ['·', '✢', '✳', '✶', '✻', '✽'];
const SGR_MOUSE_INPUT = /(?:\u001b)?\[<\d{1,3};\d{1,4};\d{1,4}[Mm]/g;
const X10_MOUSE_INPUT = /(?:\u001b)?\[M[\x20-\x7f]{3}/g;
const UNSAFE_CONTROL_INPUT = /[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F-\u009F]/g;

function envEnabled(value) {
  return ['1', 'true', 'yes', 'on'].includes(String(value ?? '').trim().toLowerCase());
}

export function resolveTerminalMode(env = process.env) {
  const fullscreenEnabled = envEnabled(env.KNOWFLOW_CLI_FULLSCREEN);
  return {
    fullscreenEnabled,
    mouseEnabled: fullscreenEnabled && envEnabled(env.KNOWFLOW_CLI_MOUSE),
  };
}

export function sanitizeComposerInput(value) {
  const withoutMouse = String(value ?? '').replace(SGR_MOUSE_INPUT, '').replace(X10_MOUSE_INPUT, '');
  return stripAnsi(withoutMouse)
    .replace(/\r\n?/g, '\n')
    .replace(UNSAFE_CONTROL_INPUT, '');
}

const PERMISSION_MODES = [
  {id: 'ask', label: '询问', detail: '写入和命令执行前确认'},
  {id: 'autoEdit', label: '自动编辑', detail: '普通文件修改自动通过，命令仍确认'},
  {id: 'bypass', label: '完全访问', detail: '所有工具自动通过，请仅在可信目录使用'},
];

function useSpinner(active) {
  const [frame, setFrame] = useState(0);
  useEffect(() => {
    if (!active) return undefined;
    const timer = setInterval(() => setFrame(value => (value + 1) % SPINNER.length), 100);
    return () => clearInterval(timer);
  }, [active]);
  return SPINNER[frame];
}

function safeJson(value, limit = 1200) {
  if (value === undefined || value === null || value === '') return '';
  if (typeof value === 'string') return redact(value, limit);
  try {
    return redact(JSON.stringify(value, null, 2), limit);
  } catch {
    return redact(value, limit);
  }
}

function activityFromEvent(previous, event) {
  const callId = String(event.toolCallId ?? event.stepId ?? event.toolName ?? event.type);
  const current = previous.get(callId) ?? {};
  const next = new Map(previous);
  const output = event.output ?? event.errorMessage ?? current.output;
  next.set(callId, {
    id: callId,
    name: String(event.toolName ?? event.name ?? current.name ?? '工具调用'),
    status: String(event.status ?? current.status ?? 'running'),
    arguments: event.arguments ?? current.arguments,
    output,
    elapsedSeconds: event.elapsedSeconds ?? current.elapsedSeconds,
    totalLines: event.totalLines ?? current.totalLines,
    totalBytes: event.totalBytes ?? current.totalBytes,
    latencyMs: event.latencyMs ?? current.latencyMs,
    errorCode: event.errorCode ?? current.errorCode,
  });
  return next;
}

function statusSymbol(status, spinner) {
  if (['success', 'succeeded', 'completed'].includes(status)) return {symbol: '✓', color: SUCCESS};
  if (['failed', 'error'].includes(status)) return {symbol: '✕', color: ERROR};
  if (status === 'cancelled') return {symbol: '■', color: MUTED};
  if (status === 'waiting') return {symbol: '!', color: WARNING};
  return {symbol: spinner, color: ACCENT};
}

function ActivityView({activities, expanded, running}) {
  const spinner = useSpinner(running);
  const rows = [...activities.values()];
  if (!rows.length) return null;
  return (
    <Box flexDirection="column" marginLeft={1} marginTop={1}>
      {rows.map(row => {
        const state = statusSymbol(row.status, spinner);
        const elapsed = row.elapsedSeconds !== undefined
          ? `${Number(row.elapsedSeconds).toFixed(1)}s`
          : row.latencyMs !== undefined
            ? `${(Number(row.latencyMs) / 1000).toFixed(1)}s`
            : '';
        const metrics = [elapsed, row.totalLines ? `${row.totalLines}行` : '', row.totalBytes ? `${row.totalBytes}B` : '']
          .filter(Boolean)
          .join(' · ');
        return (
          <Box key={row.id} flexDirection="column">
            <Box>
              <Text color={state.color}>{state.symbol} </Text>
              <Text color={PRIMARY} bold={row.status === 'running'}>{row.name}</Text>
              <Text color={MUTED}>{metrics ? `  ${metrics}` : ''}</Text>
            </Box>
            {expanded && (row.arguments || row.output || row.errorCode) ? (
              <Box flexDirection="column" marginLeft={2}>
                {row.arguments ? <Text color={MUTED}>输入 {safeJson(row.arguments, 600)}</Text> : null}
                {row.output ? <Text color={row.status === 'failed' ? ERROR : MUTED}>{safeJson(row.output)}</Text> : null}
                {row.errorCode ? <Text color={ERROR}>{row.errorCode}</Text> : null}
              </Box>
            ) : null}
          </Box>
        );
      })}
    </Box>
  );
}

function CommandMenu({suggestions, selected}) {
  if (!suggestions.length) return null;
  const visible = suggestions.slice(Math.max(0, selected - 2), Math.max(0, selected - 2) + 6);
  const start = Math.max(0, selected - 2);
  return (
    <Box flexDirection="column" marginBottom={1} paddingLeft={1}>
      {visible.map((command, offset) => {
        const active = start + offset === selected;
        const source = command.source === 'builtin' ? '' : ` [${command.source}]`;
        return (
          <Box key={`${command.source}:${command.value}`}>
            <Text color={active ? ACCENT : PRIMARY} bold={active}>{active ? '❯ ' : '  '}{command.value}</Text>
            <Text color={MUTED}>  {command.description}{source}</Text>
          </Box>
        );
      })}
      {suggestions.length > visible.length ? <Text color={MUTED}>  {selected + 1}/{suggestions.length}</Text> : null}
    </Box>
  );
}

function PermissionPicker({selected}) {
  return (
    <Box flexDirection="column" marginBottom={1} paddingLeft={1}>
      <Text bold>权限模式</Text>
      {PERMISSION_MODES.map((mode, index) => (
        <Box key={mode.id}>
          <Text color={index === selected ? ACCENT : PRIMARY} bold={index === selected}>
            {index === selected ? '❯ ' : '  '}{mode.label}
          </Text>
          <Text color={MUTED}>  {mode.detail}</Text>
        </Box>
      ))}
      <Text color={MUTED}>↑↓选择  Enter确认  Esc关闭</Text>
    </Box>
  );
}

function ApprovalPrompt({approval, selected}) {
  const options = ['允许一次', '本次会话允许', '拒绝'];
  return (
    <Box flexDirection="column" marginY={1} paddingLeft={1}>
      <Text color={WARNING} bold>需要确认：{approval.toolName ?? '工具调用'}</Text>
      <Text color={MUTED}>风险 {approval.risk ?? 'unknown'}{approval.destructive ? ' · 可能产生破坏性修改' : ''}</Text>
      {approval.inputSummary ? <Text color={PRIMARY}>{safeJson(approval.inputSummary, 700)}</Text> : null}
      <Box marginTop={1}>
        {options.map((option, index) => (
          <Text key={option} color={index === selected ? ACCENT : MUTED} bold={index === selected}>
            {index === selected ? '❯ ' : '  '}{option}{'  '}
          </Text>
        ))}
      </Box>
      <Text color={MUTED}>Enter确认  y允许  s会话允许  n拒绝</Text>
    </Box>
  );
}

function Welcome({version, model}) {
  return (
    <Box flexDirection="column" marginBottom={1}>
      <Box>
        <Text color={ACCENT} bold>KnowFlow</Text>
        <Text color={MUTED}> v{version}</Text>
      </Box>
      <Text color={PRIMARY}>{model || '正在连接模型'} <Text color={MUTED}>· {process.cwd()}</Text></Text>
      <Text color={MUTED}>输入任务，/查看命令</Text>
    </Box>
  );
}

function Transcript({items}) {
  return (
    <Box flexDirection="column">
      {items.map(item => (
        <Box key={item.id} marginBottom={item.role === 'user' ? 1 : 0}>
          {item.role === 'user' ? <Text color={ACCENT} bold>› </Text> : null}
          {item.role === 'error' ? (
            <Text color={ERROR}>错误：{item.content}</Text>
          ) : item.role === 'assistant' ? (
            <MarkdownText>{item.content}</MarkdownText>
          ) : (
            <Text color={PRIMARY} wrap="wrap">{item.content}</Text>
          )}
        </Box>
      ))}
    </Box>
  );
}

function capabilityText(section, status) {
  const value = status && typeof status === 'object' ? status : {};
  if (section === 'tools') {
    const web = value.webSearch ?? {};
    return [
      '工具状态',
      `web_search  ${web.configured ? (web.enabled ? '已启用' : '已停用') : '未配置'}`,
      web.configured ? '使用/tool:web_search可定向调用，也可直接让Agent自主判断。' : '配置：knowflow tools configure web-search',
    ].join('\n');
  }
  if (section === 'mcp') {
    const mcp = value.mcp ?? {};
    const servers = Array.isArray(mcp.servers) ? mcp.servers : [];
    return [
      `MCP  ${mcp.connected ?? 0}/${mcp.count ?? servers.length}已连接`,
      ...servers.map(item => `${item.status === 'connected' ? '✓' : '·'} ${item.name}  ${item.status}  ${(item.enabledTools ?? []).length}个工具`),
      servers.length ? '管理：knowflow mcp list' : '添加：knowflow mcp add <名称> <URL> --auth oauth',
    ].join('\n');
  }
  if (section === 'skills') {
    const skills = value.skills ?? {};
    const items = Array.isArray(skills.items) ? skills.items : [];
    return [
      `Skills  ${skills.count ?? items.length}个可用`,
      ...items.map(item => `✓ ${item.name ?? item.slug}  ${item.version ?? ''}  [${item.sourceKind ?? 'local'}]`),
      '安装：knowflow skills install <目录或SKILL.md>',
    ].join('\n');
  }
  const memory = value.memory ?? {};
  return [
    '长期记忆（Mem0）',
    `状态  ${memory.configured ? (memory.enabled ? '已启用' : '已配置但停用') : '未配置'}`,
    memory.configured ? '管理：knowflow memory list|enable|disable' : '配置：knowflow memory configure',
  ].join('\n');
}

function MouseWheelCapture({targetRef, onWheel}) {
  useOnWheel(targetRef, onWheel);
  return null;
}

function ComposerInput({value, cursorOffset, placeholder}) {
  if (!value) return <Text color={MUTED}>{placeholder}</Text>;
  const cursor = Math.max(0, Math.min(value.length, cursorOffset));
  const before = value.slice(0, cursor);
  const current = value[cursor] ?? ' ';
  const after = value.slice(cursor + (cursor < value.length ? 1 : 0));
  return (
    <Text color={PRIMARY} wrap="wrap">
      {before}<Text inverse>{current}</Text>{after}
    </Text>
  );
}

export function App({
  client,
  version = 'development',
  assumeYes = false,
  fullscreenEnabled = false,
  mouseEnabled = false,
}) {
  const {exit} = useApp();
  const {stdout} = useStdout();
  const scrollRef = useRef(null);
  const viewportRef = useRef(null);
  const scrollPinnedRef = useRef(true);
  const [ready, setReady] = useState(false);
  const [model, setModel] = useState('');
  const [commands, setCommands] = useState(() => mergeCommands());
  const [usage, setUsage] = useState({});
  const [input, setInput] = useState('');
  const inputRef = useRef('');
  const [cursorOffset, setCursorOffset] = useState(0);
  const cursorOffsetRef = useRef(0);
  const [dismissedInput, setDismissedInput] = useState('');
  const [selectedSuggestion, setSelectedSuggestion] = useState(0);
  const [transcript, setTranscript] = useState([]);
  const [assistantDraft, setAssistantDraft] = useState('');
  const assistantDraftRef = useRef('');
  const [activities, setActivities] = useState(new Map());
  const activitiesRef = useRef(activities);
  const [expanded, setExpanded] = useState(false);
  const [transcriptMode, setTranscriptMode] = useState(false);
  const transcriptModeRef = useRef(false);
  const [running, setRunning] = useState(false);
  const [phase, setPhase] = useState('正在启动');
  const [approval, setApproval] = useState(null);
  const [approvalChoice, setApprovalChoice] = useState(0);
  const [permissionMode, setPermissionMode] = useState(assumeYes ? 'bypass' : 'ask');
  const permissionRef = useRef(permissionMode);
  const [permissionPicker, setPermissionPicker] = useState(false);
  const [permissionChoice, setPermissionChoice] = useState(0);
  const [queue, setQueue] = useState([]);
  const [lastQuestion, setLastQuestion] = useState('');
  const [history, setHistory] = useState([]);
  const [historyIndex, setHistoryIndex] = useState(-1);
  const historyDraftRef = useRef('');
  const sessionApprovals = useRef(new Set());
  const requestCounter = useRef(0);
  const spinner = useSpinner(running && !approval);

  useEffect(() => {
    activitiesRef.current = activities;
  }, [activities]);
  useEffect(() => {
    permissionRef.current = permissionMode;
  }, [permissionMode]);

  useEffect(() => {
    const handleResize = () => scrollRef.current?.remeasure();
    stdout.on?.('resize', handleResize);
    return () => stdout.off?.('resize', handleResize);
  }, [stdout]);

  useEffect(() => {
    const immediate = setImmediate(() => {
      scrollRef.current?.remeasure();
      if (scrollPinnedRef.current) scrollRef.current?.scrollToBottom();
    });
    return () => clearImmediate(immediate);
  }, [activities, assistantDraft, expanded, transcript]);

  const scrollConversation = useCallback(delta => {
    const scroller = scrollRef.current;
    if (!scroller) return;
    const current = scroller.getScrollOffset();
    const bottom = scroller.getBottomOffset();
    const next = Math.max(0, Math.min(bottom, current + delta));
    scroller.scrollTo(next);
    scrollPinnedRef.current = next >= bottom;
  }, []);

  const scrollPage = useCallback(direction => {
    const height = Math.max(1, scrollRef.current?.getViewportHeight() ?? 1);
    scrollConversation(direction * Math.max(1, Math.floor(height / 2)));
  }, [scrollConversation]);

  const handleWheel = useCallback(event => {
    if (event.button === 'wheel-up') scrollConversation(-3);
    else if (event.button === 'wheel-down') scrollConversation(3);
  }, [scrollConversation]);

  const toggleTranscriptMode = useCallback(() => {
    const next = !transcriptModeRef.current;
    transcriptModeRef.current = next;
    setTranscriptMode(next);
    scrollRef.current?.scrollToBottom();
    scrollPinnedRef.current = true;
  }, []);

  const closeTranscriptMode = useCallback(() => {
    transcriptModeRef.current = false;
    setTranscriptMode(false);
  }, []);

  const appendItem = useCallback((role, content) => {
    const text = String(content ?? '').trim();
    if (!text) return;
    setTranscript(items => [...items, {id: `${Date.now()}-${Math.random()}`, role, content: text}]);
  }, []);

  const approvalKey = event => [event.serverName, event.toolName, event.risk, Boolean(event.destructive)].join('|');

  const decideApproval = useCallback((decision, event = approval) => {
    if (!event) return;
    if (decision === 'allow_session') sessionApprovals.current.add(approvalKey(event));
    client.send({type: 'approve', decision: decision === 'allow_session' ? 'allow_once' : decision});
    setApproval(null);
    setApprovalChoice(0);
    setPhase('继续执行');
  }, [approval, client]);

  useEffect(() => {
    const onMessage = message => {
      if (message.type === 'ready') {
        if (message.protocolVersion !== PROTOCOL_VERSION) {
          appendItem('error', `运行时协议不兼容：需要v${PROTOCOL_VERSION}，收到v${message.protocolVersion ?? '未知'}`);
          setReady(false);
          setPhase('协议不兼容');
          return;
        }
        setReady(true);
        setModel(String(message.model ?? '默认模型'));
        setCommands(mergeCommands(message.commands));
        setPhase('就绪');
        return;
      }
      if (message.type === 'agent_event') {
        const event = message.event ?? {};
        if (event.type === 'text_delta') {
          const delta = String(event.text ?? event.delta ?? '');
          assistantDraftRef.current += delta;
          setAssistantDraft(assistantDraftRef.current);
        } else if (['tool_started', 'tool_progress', 'tool_result'].includes(event.type)) {
          setActivities(value => activityFromEvent(value, event));
          setPhase(event.type === 'tool_result' ? '整理结果' : `执行${event.toolName ?? '工具'}`);
        } else if (event.type === 'agent_step') {
          setPhase(String(event.name ?? '分析任务'));
        } else if (event.type === 'approval_required') {
          const mode = permissionRef.current;
          const sessionAllowed = sessionApprovals.current.has(approvalKey(event));
          const autoEdit = mode === 'autoEdit'
            && event.risk === 'write'
            && !event.destructive;
          if (mode === 'bypass' || autoEdit || sessionAllowed) {
            client.send({type: 'approve', decision: 'allow_once'});
          } else {
            setApproval(event);
            setPhase('等待确认');
          }
        } else if (event.type === 'model_retry') {
          setPhase('模型请求重试');
        } else if (event.type === 'memory_started') {
          setActivities(value => activityFromEvent(value, {
            ...event,
            type: 'tool_started',
            toolCallId: `memory:${event.runId ?? 'current'}`,
            toolName: '长期记忆整理',
          }));
          setPhase('整理长期记忆');
        } else if (event.type === 'memory_result') {
          setActivities(value => activityFromEvent(value, {
            ...event,
            type: 'tool_result',
            toolCallId: `memory:${event.runId ?? 'current'}`,
            toolName: '长期记忆整理',
            output: event.status === 'success' ? `写入${event.count ?? 0}条` : undefined,
          }));
        }
        return;
      }
      if (message.type === 'capability_status') {
        appendItem('assistant', capabilityText(message.section, message.status));
        return;
      }
      if (message.type === 'capability_failed') {
        appendItem('error', message.message ?? '读取能力状态失败。');
        return;
      }
      if (message.type === 'turn_completed') {
        appendItem('assistant', assistantDraftRef.current || message.answer);
        assistantDraftRef.current = '';
        setAssistantDraft('');
        setRunning(false);
        setPhase(message.cancelled ? '已取消' : '就绪');
        return;
      }
      if (message.type === 'turn_failed') {
        appendItem('error', `${message.message}  输入/retry重试`);
        assistantDraftRef.current = '';
        setAssistantDraft('');
        setRunning(false);
        setPhase('执行失败');
        return;
      }
      if (message.type === 'cancel_requested') {
        setPhase(message.accepted ? '正在取消' : '当前任务无法取消');
        if (!message.accepted && message.message) appendItem('error', message.message);
        return;
      }
      if (message.type === 'busy') {
        appendItem('error', message.message ?? '当前任务尚未结束。');
        return;
      }
      if (message.type === 'approval_queued') {
        setPhase('审批已提交');
        return;
      }
      if (message.type === 'session_reset') {
        setTranscript([]);
        setActivities(new Map());
        sessionApprovals.current.clear();
        setPermissionMode('ask');
        setPhase('新会话');
        return;
      }
      if (message.type === 'doctor_result') {
        for (const check of message.checks ?? []) {
          appendItem(check.ready ? 'assistant' : 'error', `${check.ready ? '✓' : '✕'} ${check.name}：${check.detail}`);
        }
        return;
      }
      if (['doctor_failed', 'startup_failed', 'protocol_error'].includes(message.type)) {
        appendItem('error', message.message ?? '运行时错误');
        if (message.type === 'startup_failed') setRunning(false);
      }
    };
    const onExit = ({code, detail}) => {
      if (code !== 0) appendItem('error', `Python运行时已退出（${code}）${detail ? `：${detail}` : ''}`);
      setReady(false);
      setRunning(false);
      setPhase('运行时已停止');
    };
    client.on('message', onMessage);
    client.on('exit', onExit);
    client.start();
    return () => {
      client.off('message', onMessage);
      client.off('exit', onExit);
      client.close();
    };
  }, [appendItem, client]);

  useEffect(() => {
    if (running || approval || !ready || queue.length === 0) return;
    const [next, ...remaining] = queue;
    setQueue(remaining);
    requestCounter.current += 1;
    setRunning(true);
    setActivities(new Map());
    assistantDraftRef.current = '';
    setAssistantDraft('');
    setLastQuestion(next);
    setHistory(items => [...items.filter(item => item !== next), next].slice(-100));
    setHistoryIndex(-1);
    appendItem('user', next);
    client.send({type: 'submit', requestId: `turn-${requestCounter.current}`, text: next});
  }, [approval, appendItem, client, queue, ready, running]);

  const suggestions = useMemo(() => {
    if (input === dismissedInput) return [];
    return commandSuggestions(input, commands, usage);
  }, [commands, dismissedInput, input, usage]);

  useEffect(() => setSelectedSuggestion(0), [input]);

  const updateComposer = useCallback((value, cursor = String(value ?? '').length) => {
    const next = String(value ?? '');
    const nextCursor = Math.max(0, Math.min(next.length, cursor));
    inputRef.current = next;
    cursorOffsetRef.current = nextCursor;
    setInput(next);
    setCursorOffset(nextCursor);
    if (next !== dismissedInput) setDismissedInput('');
  }, [dismissedInput]);

  const startTurn = useCallback(text => {
    if (!ready) {
      appendItem('error', '运行时尚未准备好。');
      return;
    }
    if (running || approval) {
      setQueue(items => [...items, text]);
      setPhase(`已排队${queue.length + 1}个任务`);
      return;
    }
    requestCounter.current += 1;
    setRunning(true);
    setActivities(new Map());
    assistantDraftRef.current = '';
    setAssistantDraft('');
    setLastQuestion(text);
    setHistory(items => [...items.filter(item => item !== text), text].slice(-100));
    setHistoryIndex(-1);
    appendItem('user', text);
    client.send({type: 'submit', requestId: `turn-${requestCounter.current}`, text});
  }, [approval, appendItem, client, queue.length, ready, running]);

  const executeInput = useCallback(raw => {
    const text = String(raw ?? '').trim();
    if (!text) return;
    const parsed = resolveCommand(text, commands);
    if (!parsed) {
      if (/^\/[A-Za-z0-9:_-]+(?:\s|$)/.test(text)) {
        appendItem('error', `未知命令：${text.split(/\s+/, 1)[0]}。输入/查看可用命令。`);
        return;
      }
      startTurn(text);
      return;
    }
    const {command, args} = parsed;
    setUsage(value => ({...value, [command.value]: (value[command.value] ?? 0) + 1}));
    if (command.source !== 'builtin') {
      startTurn(dynamicCommandTask(command.value, args));
      return;
    }
    if (command.value === '/exit') {
      client.close();
      exit();
    } else if (command.value === '/new') {
      client.send({type: 'reset'});
    } else if (command.value === '/clear') {
      setTranscript([]);
      setActivities(new Map());
    } else if (command.value === '/model') {
      appendItem('assistant', `当前模型：${model || '默认模型'}`);
    } else if (command.value === '/status') {
      appendItem('assistant', `${running ? '执行中' : '就绪'} · ${queue.length}个排队任务 · ${PERMISSION_MODES.find(item => item.id === permissionMode)?.label}`);
    } else if (command.value === '/permissions') {
      setPermissionChoice(Math.max(0, PERMISSION_MODES.findIndex(item => item.id === permissionMode)));
      setPermissionPicker(true);
    } else if (['/tools', '/mcp', '/skills', '/memory'].includes(command.value)) {
      client.send({type: 'capabilities', section: command.value.slice(1)});
      setPhase(`读取${command.value.slice(1)}状态`);
    } else if (command.value === '/tools:configure') {
      appendItem('assistant', '在另一个终端运行：knowflow tools configure web-search\nKey会隐藏输入并写入独立credentials.json。');
    } else if (command.value === '/mcp:add') {
      appendItem('assistant', '添加OAuth MCP：knowflow mcp add <名称> <URL> --auth oauth\n添加后按提示运行knowflow mcp oauth <ID>。');
    } else if (command.value === '/mcp:oauth') {
      appendItem('assistant', '运行：knowflow mcp oauth <ID>\nCLI会打开浏览器并在本机回环地址接收OAuth回调。');
    } else if (command.value === '/skills:install') {
      appendItem('assistant', '运行：knowflow skills install <目录或SKILL.md>');
    } else if (command.value === '/memory:configure') {
      appendItem('assistant', '运行：knowflow memory configure\n配置完成后运行knowflow memory enable。');
    } else if (command.value === '/doctor') {
      client.send({type: 'doctor'});
      setPhase('检查SRT沙箱');
    } else if (command.value === '/tasks') {
      appendItem('assistant', queue.length ? queue.map((item, index) => `${index + 1}. ${item}`).join('\n') : '当前没有排队任务。');
    } else if (command.value === '/retry') {
      if (lastQuestion) startTurn(lastQuestion);
      else appendItem('error', '没有可重试的问题。');
    } else {
      appendItem('assistant', [
        '常用命令：/new /model /permissions /tools /mcp /skills /memory /doctor /tasks /retry /exit',
        '快捷键：Shift+Tab切换权限，Ctrl+O查看记录，Ctrl+E展开工具，Ctrl+C取消，Ctrl+D退出',
        '输入/后使用↑↓选择，Tab或→补全，Esc关闭。',
      ].join('\n'));
    }
  }, [appendItem, client, commands, exit, lastQuestion, model, permissionMode, queue, running, startTurn]);

  const acceptSuggestion = useCallback(() => {
    const suggestion = suggestions[selectedSuggestion];
    if (!suggestion) return;
    const next = `${suggestion.value} `;
    updateComposer(next);
    setDismissedInput(next);
  }, [selectedSuggestion, suggestions, updateComposer]);

  const submitComposer = useCallback(value => {
    const selected = suggestions[selectedSuggestion];
    if (selected && value.trim() !== selected.value) {
      acceptSuggestion();
      return;
    }
    updateComposer('', 0);
    setDismissedInput('');
    historyDraftRef.current = '';
    executeInput(value);
  }, [acceptSuggestion, executeInput, selectedSuggestion, suggestions, updateComposer]);

  useInput((character, key) => {
    if (approval) {
      if (key.leftArrow || key.upArrow) setApprovalChoice(value => (value + 2) % 3);
      else if (key.rightArrow || key.downArrow) setApprovalChoice(value => (value + 1) % 3);
      else if (key.return) decideApproval(['allow_once', 'allow_session', 'deny'][approvalChoice]);
      else if (character.toLowerCase() === 'y') decideApproval('allow_once');
      else if (character.toLowerCase() === 's') decideApproval('allow_session');
      else if (character.toLowerCase() === 'n' || key.escape) decideApproval('deny');
      return;
    }
    if (permissionPicker) {
      if (key.upArrow) setPermissionChoice(value => (value + PERMISSION_MODES.length - 1) % PERMISSION_MODES.length);
      else if (key.downArrow) setPermissionChoice(value => (value + 1) % PERMISSION_MODES.length);
      else if (key.return) {
        setPermissionMode(PERMISSION_MODES[permissionChoice].id);
        setPermissionPicker(false);
      } else if (key.escape) setPermissionPicker(false);
      return;
    }
    if (key.ctrl && character === 'c') {
      if (running) client.send({type: 'cancel'});
      else if (inputRef.current) updateComposer('', 0);
      else exit();
      return;
    }
    if (key.ctrl && character === 'd' && !running && !inputRef.current) {
      client.close();
      exit();
      return;
    }
    if (key.ctrl && character === 'o') {
      toggleTranscriptMode();
      return;
    }
    if (transcriptModeRef.current) {
      if (key.escape) closeTranscriptMode();
      else if (fullscreenEnabled && key.pageUp) scrollPage(-1);
      else if (fullscreenEnabled && key.pageDown) scrollPage(1);
      else if (fullscreenEnabled && key.upArrow) scrollConversation(-1);
      else if (fullscreenEnabled && key.downArrow) scrollConversation(1);
      else if (fullscreenEnabled && key.home) {
        scrollRef.current?.scrollToTop();
        scrollPinnedRef.current = false;
      } else if (fullscreenEnabled && key.end) {
        scrollRef.current?.scrollToBottom();
        scrollPinnedRef.current = true;
      }
      return;
    }
    if (key.ctrl && character === 'e') {
      setExpanded(value => !value);
      return;
    }
    if (key.ctrl && character === 'r' && history.length) {
      const next = historyIndex < 0 ? history.length - 1 : Math.max(0, historyIndex - 1);
      if (historyIndex < 0) historyDraftRef.current = inputRef.current;
      setHistoryIndex(next);
      updateComposer(history[next]);
      return;
    }
    if (key.shift && key.tab) {
      const index = PERMISSION_MODES.findIndex(item => item.id === permissionRef.current);
      setPermissionMode(PERMISSION_MODES[(index + 1) % PERMISSION_MODES.length].id);
      return;
    }
    if (fullscreenEnabled && key.pageUp) {
      scrollPage(-1);
      return;
    }
    if (fullscreenEnabled && key.pageDown) {
      scrollPage(1);
      return;
    }
    if (suggestions.length) {
      if (key.upArrow) {
        setSelectedSuggestion(value => (value + suggestions.length - 1) % suggestions.length);
        return;
      }
      if (key.downArrow) {
        setSelectedSuggestion(value => (value + 1) % suggestions.length);
        return;
      }
      if (key.tab || key.rightArrow) {
        acceptSuggestion();
        return;
      }
      if (key.return) {
        submitComposer(inputRef.current);
        return;
      }
      if (key.escape) {
        setDismissedInput(input);
        return;
      }
    }
    if (!inputRef.current && history.length && key.upArrow) {
      historyDraftRef.current = inputRef.current;
      const next = historyIndex < 0 ? history.length - 1 : Math.max(0, historyIndex - 1);
      setHistoryIndex(next);
      updateComposer(history[next]);
      return;
    }
    if (historyIndex >= 0 && key.upArrow) {
      const next = Math.max(0, historyIndex - 1);
      setHistoryIndex(next);
      updateComposer(history[next]);
      return;
    }
    if (historyIndex >= 0 && key.downArrow) {
      const next = historyIndex + 1;
      if (next >= history.length) {
        setHistoryIndex(-1);
        updateComposer(historyDraftRef.current);
      } else {
        setHistoryIndex(next);
        updateComposer(history[next]);
      }
      return;
    }
    if (key.return) {
      submitComposer(inputRef.current);
      return;
    }
    if (key.leftArrow) {
      const next = Math.max(0, cursorOffsetRef.current - 1);
      cursorOffsetRef.current = next;
      setCursorOffset(next);
      return;
    }
    if (key.rightArrow) {
      const next = Math.min(inputRef.current.length, cursorOffsetRef.current + 1);
      cursorOffsetRef.current = next;
      setCursorOffset(next);
      return;
    }
    if (key.home) {
      cursorOffsetRef.current = 0;
      setCursorOffset(0);
      return;
    }
    if (key.end) {
      cursorOffsetRef.current = inputRef.current.length;
      setCursorOffset(inputRef.current.length);
      return;
    }
    if (key.backspace) {
      const value = inputRef.current;
      const cursor = cursorOffsetRef.current;
      if (cursor > 0) {
        updateComposer(
          value.slice(0, cursor - 1) + value.slice(cursor),
          cursor - 1,
        );
      }
      return;
    }
    if (key.delete) {
      const value = inputRef.current;
      const cursor = cursorOffsetRef.current;
      if (cursor < value.length) {
        updateComposer(
          value.slice(0, cursor) + value.slice(cursor + 1),
          cursor,
        );
      }
      return;
    }
    if (key.ctrl || key.meta || key.tab || key.escape) return;
    const text = sanitizeComposerInput(character);
    if (!text) return;
    const value = inputRef.current;
    const cursor = cursorOffsetRef.current;
    updateComposer(
      value.slice(0, cursor) + text + value.slice(cursor),
      cursor + text.length,
    );
    if (historyIndex >= 0) {
      setHistoryIndex(-1);
      historyDraftRef.current = '';
    }
  }, {
    isActive: true,
  });

  const permission = PERMISSION_MODES.find(item => item.id === permissionMode) ?? PERMISSION_MODES[0];
  const narrow = (stdout.columns ?? 80) < 72;
  const frameHeight = Math.max(1, (stdout.rows ?? 24) - 1);
  const conversation = (
    <Box key="conversation" flexDirection="column" width="100%">
      <Welcome version={version} model={model} />
      <Transcript items={transcript} />
      {running || activities.size ? <ActivityView activities={activities} expanded={expanded} running={running} /> : null}
      {assistantDraft ? (
        <Box marginTop={1}>
          <MarkdownText>{assistantDraft}</MarkdownText>
        </Box>
      ) : null}
    </Box>
  );
  const transcriptFooter = (
    <Box borderStyle="single" borderLeft={false} borderRight={false} borderBottom={false} borderColor={MUTED} paddingLeft={1} justifyContent="space-between">
      <Text color={PRIMARY}>对话记录</Text>
      <Text color={MUTED}>
        {fullscreenEnabled
          ? `${mouseEnabled ? '滚轮/' : ''}↑↓滚动 · PgUp/PgDn翻页 · Home/End定位`
          : '使用终端滚轮浏览并拖动选择文本'} · Ctrl+O/Esc返回
      </Text>
    </Box>
  );
  const controls = (
    <>
      {approval ? <ApprovalPrompt approval={approval} selected={approvalChoice} /> : null}
      <Box marginTop={1}>
        <Text color={running ? ACCENT : MUTED}>{running && !approval ? `${spinner} ${phase}` : phase}</Text>
        {running ? <Text color={MUTED}> · Ctrl+C取消</Text> : null}
        {queue.length ? <Text color={MUTED}> · 队列{queue.length}</Text> : null}
      </Box>
      {permissionPicker ? <PermissionPicker selected={permissionChoice} /> : null}
      {!permissionPicker && !approval ? <CommandMenu suggestions={suggestions} selected={selectedSuggestion} /> : null}
      <Box flexDirection="column" marginTop={suggestions.length || permissionPicker ? 0 : 1} borderStyle="round" borderLeft={false} borderRight={false} borderColor={ACCENT} paddingX={1} flexShrink={0}>
        <Box>
          <Text color={ACCENT}>❯ </Text>
          <ComposerInput
            value={input}
            cursorOffset={cursorOffset}
            placeholder={running ? '继续输入可加入队列' : '输入任务，/查看命令'}
          />
        </Box>
      </Box>
      <Box justifyContent="space-between" flexShrink={0}>
        <Text color={permissionMode === 'bypass' ? ERROR : permissionMode === 'autoEdit' ? WARNING : MUTED}>
          {permission.label}{narrow ? '' : ' · Shift+Tab切换'}
        </Text>
        {!narrow ? (
          <Text color={MUTED}>
            {model || '连接中'} · {fullscreenEnabled ? 'Ctrl+O记录' : '终端滚轮浏览'} · Ctrl+E工具详情
          </Text>
        ) : null}
      </Box>
    </>
  );

  if (!fullscreenEnabled) {
    return (
      <Box flexDirection="column" paddingX={1}>
        {conversation}
        {transcriptMode ? transcriptFooter : controls}
      </Box>
    );
  }

  return (
    <Box flexDirection="column" height={frameHeight} paddingX={1} overflow="hidden">
      <Box ref={viewportRef} flexDirection="column" flexGrow={1} flexShrink={1} minHeight={1} overflow="hidden">
        {mouseEnabled ? <MouseWheelCapture targetRef={viewportRef} onWheel={handleWheel} /> : null}
        <ScrollView
          ref={scrollRef}
          flexGrow={1}
          flexShrink={1}
          minHeight={1}
          onScroll={offset => {
            const bottom = scrollRef.current?.getBottomOffset() ?? 0;
            scrollPinnedRef.current = bottom - offset <= 1;
          }}
          onContentHeightChange={() => {
            if (scrollPinnedRef.current) scrollRef.current?.scrollToBottom();
          }}
        >
          {conversation}
        </ScrollView>
      </Box>
      {transcriptMode ? transcriptFooter : controls}
    </Box>
  );
}
