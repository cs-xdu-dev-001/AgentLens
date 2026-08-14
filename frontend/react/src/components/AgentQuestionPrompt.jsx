import { useEffect, useMemo, useRef, useState } from "react";
import { agentRunApi } from "../api/client.js";

export function AgentQuestionPrompt({
  autoFocus = false,
  interactive = true,
  question,
  queuedCount = 0,
}) {
  const options = useMemo(
    () => (Array.isArray(question?.options) ? question.options.slice(0, 4) : []),
    [question],
  );
  const [custom, setCustom] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const rootRef = useRef(null);
  const answered = question?.status !== "waiting";

  useEffect(() => {
    if (!autoFocus || !interactive || answered) return undefined;
    const frame = window.requestAnimationFrame(() => {
      rootRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
      rootRef.current
        ?.querySelector("button:not(:disabled), input:not(:disabled)")
        ?.focus({ preventScroll: true });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [answered, autoFocus, interactive, question?.questionId]);

  useEffect(() => {
    if (!interactive || answered) return undefined;
    const handleFocusRequest = () => {
      rootRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
      rootRef.current
        ?.querySelector("button:not(:disabled), input:not(:disabled)")
        ?.focus({ preventScroll: true });
    };
    window.addEventListener("knowflow:react-agent-interaction-focus", handleFocusRequest);
    return () => window.removeEventListener(
      "knowflow:react-agent-interaction-focus",
      handleFocusRequest,
    );
  }, [answered, interactive, question?.questionId]);

  async function submit(answer, selectedOptions = []) {
    if (submitting || answered || !String(answer || "").trim()) return;
    setSubmitting(true);
    setError("");
    try {
      await agentRunApi.answer(question.runId, {
        questionId: question.questionId,
        answer: String(answer).trim(),
        selectedOptions,
      });
      window.dispatchEvent(new CustomEvent("knowflow:react-agent-question-resume", {
        detail: { runId: question.runId, questionId: question.questionId },
      }));
    } catch (nextError) {
      setError("回答提交失败，请检查网络后重试。");
      setSubmitting(false);
    }
  }

  return (
    <section
      className={`agent-question-prompt${answered ? " answered" : ""}`}
      aria-busy={submitting}
      aria-live="polite"
      ref={rootRef}
    >
      <div className="agent-question-header">
        <span>{question.header || "需要确认"}</span>
        {queuedCount ? <span>另有{queuedCount}项待处理</span> : null}
      </div>
      <div className="agent-question-text">{question.question || "请选择下一步。"}</div>
      {interactive ? (
      <div className="agent-question-options" role="group" aria-label="可选回答">
        {options.map((option, index) => {
          const label = String(option?.label || `选项${index + 1}`);
          const value = String(option?.value || label);
          return (
            <button
              type="button"
              className="agent-question-option"
              disabled={submitting || answered}
              key={`${value}-${index}`}
              onClick={() => submit(value, [value])}
            >
              <span>{label}</span>
              {option?.description ? (
                <span className="agent-question-option-description">
                  {option.description}
                </span>
              ) : null}
            </button>
          );
        })}
      </div>
      ) : null}
      {interactive && question.allowCustom !== false && !answered ? (
        <form
          className="agent-question-custom"
          onSubmit={(event) => {
            event.preventDefault();
            submit(custom);
          }}
        >
          <input
            value={custom}
            maxLength={4000}
            disabled={submitting}
            onChange={(event) => setCustom(event.target.value)}
            placeholder="输入其他回答"
            aria-label="自定义回答"
          />
          <button type="submit" disabled={submitting || !custom.trim()}>
            {submitting ? "提交中" : "提交"}
          </button>
        </form>
      ) : null}
      {!interactive && !answered ? (
        <button
          className="agent-question-jump"
          type="button"
          onClick={() => window.dispatchEvent(
            new CustomEvent("knowflow:react-agent-interaction-focus"),
          )}
        >
          前往当前请求
        </button>
      ) : null}
      {error ? <div className="agent-question-error" role="alert">{error}</div> : null}
    </section>
  );
}
