import Fuse from "fuse.js";
import { useEffect, useMemo, useRef, useState } from "react";

function historyItemId(index) {
  return `composer-history-option-${index}`;
}

export function ComposerHistorySearch({ entries, onClear, onClose, onSelect }) {
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const [confirmClear, setConfirmClear] = useState(false);
  const searchRef = useRef(null);
  const activeItemRef = useRef(null);
  const orderedEntries = useMemo(
    () => [...entries].reverse().map((text, index) => ({ id: index, text })),
    [entries],
  );
  const searchIndex = useMemo(() => new Fuse(orderedEntries, {
    keys: ["text"],
    threshold: 0.34,
    ignoreLocation: true,
    minMatchCharLength: 1,
  }), [orderedEntries]);
  const matches = useMemo(() => {
    const normalizedQuery = query.trim();
    if (!normalizedQuery) return orderedEntries;
    return searchIndex.search(normalizedQuery).map((result) => result.item);
  }, [orderedEntries, query, searchIndex]);

  useEffect(() => {
    searchRef.current?.focus();
  }, []);

  useEffect(() => {
    setActiveIndex(matches.length ? 0 : -1);
  }, [matches]);

  useEffect(() => {
    activeItemRef.current?.scrollIntoView({ block: "nearest" });
  }, [activeIndex]);

  const takeMatch = (match) => {
    if (match) onSelect(match.text);
  };

  const handleKeyDown = (event) => {
    if (event.isComposing || event.nativeEvent?.isComposing || event.keyCode === 229) return;
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
      return;
    }
    const cycleForward = (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "r";
    if (cycleForward || event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!matches.length) return;
      const delta = event.key === "ArrowUp" ? -1 : 1;
      setActiveIndex((current) => (current + delta + matches.length) % matches.length);
      return;
    }
    if (event.key === "Enter" && matches[activeIndex]) {
      event.preventDefault();
      takeMatch(matches[activeIndex]);
    }
  };

  const activeMatch = matches[activeIndex];

  return (
    <section
      className={"composer-history-search"}
      data-testid={"composer-history-search"}
      role={"region"}
      aria-label={"搜索输入历史"}
      onKeyDown={handleKeyDown}
    >
      <div className={"composer-history-heading"}>
        <strong>{`输入历史 ${entries.length} · 此浏览器`}</strong>
        <div className={"composer-history-actions"}>
          <button
            type={"button"}
            aria-label={confirmClear ? "确认清空输入历史" : "清空输入历史"}
            onClick={() => {
              if (confirmClear) onClear();
              else setConfirmClear(true);
            }}
          >
            {confirmClear ? "确认清空" : "清空"}
          </button>
          <button type={"button"} onClick={() => onClose()} aria-label={"关闭输入历史"}>{"关闭"}</button>
        </div>
      </div>
      <label className={"composer-history-query"}>
        <input
          ref={searchRef}
          value={query}
          role={"combobox"}
          aria-label={"筛选输入历史"}
          aria-controls={"composer-history-listbox"}
          aria-expanded={true}
          aria-activedescendant={activeMatch ? historyItemId(activeMatch.id) : undefined}
          placeholder={"筛选最近100条输入"}
          autoComplete={"off"}
          spellCheck={false}
          onChange={(event) => setQuery(event.target.value)}
        />
      </label>
      <div
        className={"composer-history-list"}
        id={"composer-history-listbox"}
        role={"listbox"}
        aria-label={"输入历史"}
      >
        {matches.map((match, index) => {
          const active = index === activeIndex;
          return (
            <button
              key={`${match.id}:${match.text}`}
              id={historyItemId(match.id)}
              className={active ? "composer-history-item active" : "composer-history-item"}
              type={"button"}
              role={"option"}
              aria-selected={active}
              ref={active ? activeItemRef : null}
              title={match.text}
              onClick={() => takeMatch(match)}
            >
              <span>{match.text}</span>
            </button>
          );
        })}
        {!matches.length ? (
          <div className={"composer-history-state"} role={"status"}>
            {query ? `没有匹配“${query.trim()}”的历史输入` : "还没有输入历史"}
          </div>
        ) : null}
      </div>
      <div className={"composer-history-footer"}>
        <span>{"Ctrl/⌘+R或↑↓继续查找 · Enter使用 · Esc返回"}</span>
      </div>
    </section>
  );
}
