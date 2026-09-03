import { useMemo, useState } from "react";
import { authApi } from "../api/client.js";
import { normalizeErrorMessage } from "../api/errors.js";
import { useAuth } from "../auth/AuthProvider.jsx";
import { AgentLensLogo } from "./AgentLensLogo.jsx";


function readUserCode() {
  if (typeof window === "undefined") return "";
  return String(new URLSearchParams(window.location.search).get("userCode") || "")
    .toUpperCase()
    .replace(/[^A-Z0-9-]/g, "")
    .slice(0, 11);
}


export function CliDeviceAuthPage({ active }) {
  const { user } = useAuth();
  const [state, setState] = useState("ready");
  const [message, setMessage] = useState("");
  const userCode = useMemo(readUserCode, []);
  const validCode = /^[A-Z2-9]{5}-[A-Z2-9]{5}$/.test(userCode);

  const decide = async (decision) => {
    if (!validCode || state !== "ready") return;
    setState("submitting");
    setMessage("");
    try {
      const result = await authApi.decideCliDevice(userCode, decision);
      setState(result?.status === "approved" ? "approved" : "denied");
    } catch (error) {
      setState("ready");
      setMessage(normalizeErrorMessage(error, "无法处理本次CLI登录请求。"));
    }
  };

  if (!active) return null;
  const finished = state === "approved" || state === "denied";

  return (
    <section className="cli-device-page" id="page-cli-auth" aria-labelledby="cli-device-title">
      <div className="cli-device-card">
        <div className="cli-device-brand" aria-hidden="true"><AgentLensLogo /></div>
        {finished ? (
          <>
            <h1 id="cli-device-title">{state === "approved" ? "CLI已连接" : "已拒绝登录"}</h1>
            <p>{state === "approved" ? "授权结果已安全发送到终端，可以关闭此页面。" : "终端无法访问你的AgentLens账号。"}</p>
          </>
        ) : (
          <>
            <h1 id="cli-device-title">允许AgentLens CLI登录？</h1>
            <p>确认后，当前终端将以<strong>{user?.displayName || user?.username || "当前账号"}</strong>身份访问AgentLens。</p>
            <div className="cli-device-code" aria-label={`验证码 ${userCode || "无效"}`}>{userCode || "验证码缺失"}</div>
            {!validCode ? <div className="cli-device-error" role="alert">登录链接无效，请回到终端重新发起。</div> : null}
            {message ? <div className="cli-device-error" role="alert">{message}</div> : null}
            <div className="cli-device-actions">
              <button type="button" className="secondary" disabled={!validCode || state === "submitting"} onClick={() => decide("deny")}>拒绝</button>
              <button type="button" className="primary" disabled={!validCode || state === "submitting"} onClick={() => decide("approve")}>{state === "submitting" ? "正在确认..." : "允许登录"}</button>
            </div>
          </>
        )}
      </div>
    </section>
  );
}
