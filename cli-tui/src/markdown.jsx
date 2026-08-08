import React, {useMemo} from 'react';
import {Box, Text} from 'ink';
import {marked} from 'marked';
import {sanitizeTerminalText} from './protocol.js';

const ACCENT = '#d97757';
const PRIMARY = '#e5e7eb';
const MUTED = '#8b8b8b';

function plainText(token) {
  if (!token) return '';
  if (typeof token === 'string') return token;
  if (Array.isArray(token)) return token.map(plainText).join('');
  if (Array.isArray(token.tokens)) return token.tokens.map(plainText).join('');
  return String(token.text ?? token.raw ?? '');
}

function Inline({tokens = []}) {
  return (
    <Text color={PRIMARY} wrap="wrap">
      {tokens.map((token, index) => {
        const key = `${token.type}-${index}`;
        if (token.type === 'strong') return <Text key={key} bold><Inline tokens={token.tokens} /></Text>;
        if (token.type === 'em') return <Text key={key} italic><Inline tokens={token.tokens} /></Text>;
        if (token.type === 'codespan') return <Text key={key} color={ACCENT}>{token.text}</Text>;
        if (token.type === 'link') return <Text key={key} color={ACCENT} underline><Inline tokens={token.tokens} /></Text>;
        if (token.type === 'del') return <Text key={key} strikethrough><Inline tokens={token.tokens} /></Text>;
        if (token.type === 'br') return <Text key={key}>{'\n'}</Text>;
        if (Array.isArray(token.tokens)) return <Inline key={key} tokens={token.tokens} />;
        return <Text key={key}>{token.text ?? token.raw ?? ''}</Text>;
      })}
    </Text>
  );
}

function Blocks({tokens = [], compact = false}) {
  return tokens.map((token, index) => {
    const key = `${token.type}-${index}`;
    if (token.type === 'space') return null;
    if (token.type === 'heading') {
      return <Box key={key} marginTop={compact ? 0 : 1}><Text color={PRIMARY} bold><Inline tokens={token.tokens} /></Text></Box>;
    }
    if (token.type === 'paragraph' || token.type === 'text') {
      return <Box key={key} marginBottom={compact ? 0 : 1}><Inline tokens={token.tokens ?? [{type: 'text', text: token.text}]} /></Box>;
    }
    if (token.type === 'code') {
      return (
        <Box key={key} marginBottom={compact ? 0 : 1} paddingLeft={1} borderStyle="single" borderLeft borderRight={false} borderTop={false} borderBottom={false} borderColor={MUTED}>
          <Text color={PRIMARY}>{token.text}</Text>
        </Box>
      );
    }
    if (token.type === 'blockquote') {
      return (
        <Box key={key} paddingLeft={1} borderStyle="single" borderLeft borderRight={false} borderTop={false} borderBottom={false} borderColor={MUTED}>
          <Blocks tokens={token.tokens} compact />
        </Box>
      );
    }
    if (token.type === 'list') {
      return (
        <Box key={key} flexDirection="column" marginBottom={compact ? 0 : 1}>
          {token.items.map((item, itemIndex) => (
            <Box key={`${key}-${itemIndex}`}>
              <Text color={MUTED}>{token.ordered ? `${Number(token.start ?? 1) + itemIndex}. ` : '• '}</Text>
              <Box flexDirection="column" flexGrow={1}>
                <Blocks tokens={item.tokens} compact />
              </Box>
            </Box>
          ))}
        </Box>
      );
    }
    if (token.type === 'table') {
      const rows = [token.header, ...token.rows];
      return (
        <Box key={key} flexDirection="column" marginBottom={compact ? 0 : 1}>
          {rows.map((row, rowIndex) => <Text color={PRIMARY} key={`${key}-${rowIndex}`}>{row.map(plainText).join(' │ ')}</Text>)}
        </Box>
      );
    }
    if (token.type === 'hr') return <Text key={key} color={MUTED}>────────────────</Text>;
    return <Text color={PRIMARY} key={key}>{plainText(token)}</Text>;
  });
}

export function MarkdownText({children}) {
  const source = sanitizeTerminalText(children);
  const tokens = useMemo(() => {
    try {
      return marked.lexer(source, {gfm: true});
    } catch {
      return [{type: 'paragraph', tokens: [{type: 'text', text: source}]}];
    }
  }, [source]);
  return <Box flexDirection="column" width="100%"><Blocks tokens={tokens} /></Box>;
}
