import { useState } from "react";
import {
  AGENT_NOTIFICATION_PREFERENCE_EVENT,
  agentNotificationPreference,
  saveAgentNotificationPreference,
} from "./agentWindowFeedback.js";
import { notifyToast } from "./errorFeedback.js";

const LABELS = {
  blocked: "浏览器已阻止桌面提醒，请在站点权限中重新允许",
  disabled: "开启任务桌面提醒",
  enabled: "关闭任务桌面提醒",
  unsupported: "当前浏览器不支持桌面提醒",
};

function publishPreference(enabled) {
  window.dispatchEvent(new CustomEvent(AGENT_NOTIFICATION_PREFERENCE_EVENT, {
    detail: { enabled },
  }));
}

export function AgentNotificationToggle() {
  const [preference, setPreference] = useState(() => agentNotificationPreference());

  const updatePreference = (enabled) => {
    saveAgentNotificationPreference(enabled);
    const next = agentNotificationPreference();
    setPreference(next);
    publishPreference(next.enabled);
    notifyToast(next.enabled ? "任务桌面提醒已开启" : "任务桌面提醒已关闭");
  };

  const handleClick = async () => {
    if (preference.state === "unsupported") return;
    if (preference.state === "blocked") {
      notifyToast(LABELS.blocked);
      return;
    }
    if (preference.enabled) {
      updatePreference(false);
      return;
    }
    try {
      const permission = window.Notification.permission === "granted"
        ? "granted"
        : await window.Notification.requestPermission();
      if (permission === "granted") updatePreference(true);
      else {
        const next = agentNotificationPreference();
        setPreference(next);
        publishPreference(false);
        notifyToast(next.state === "blocked" ? LABELS.blocked : "未开启任务桌面提醒");
      }
    } catch {
      notifyToast("无法开启桌面提醒，请检查浏览器站点权限");
    }
  };

  const label = LABELS[preference.state] || LABELS.disabled;
  return (
    <button
      aria-label={label}
      aria-pressed={preference.enabled}
      className={`chat-notification-toggle is-${preference.state}`}
      disabled={preference.state === "unsupported"}
      onClick={handleClick}
      title={label}
      type={"button"}
    >
      <svg aria-hidden={"true"} focusable={"false"} viewBox={"0 0 20 20"}>
        <path d={"M5.3 8.2a4.7 4.7 0 0 1 9.4 0v3.2l1.3 2H4l1.3-2z"} />
        <path d={"M8.2 15.1a2 2 0 0 0 3.6 0"} />
        {preference.state === "disabled" ? <path d={"M4 4l12 12"} /> : null}
      </svg>
    </button>
  );
}
