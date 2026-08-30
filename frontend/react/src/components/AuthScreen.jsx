import { useEffect, useState } from "react";
import { BACKEND_UNAVAILABLE_MESSAGE, normalizeErrorMessage } from "../api/errors.js";
import { useAuth } from "../auth/AuthProvider.jsx";
import { copyTextToClipboard } from "../controller/clipboard.js";
import { KnowFlowLogo } from "./KnowFlowLogo.jsx";

export function AuthScreen() {
  const { authenticated, loading, login, oauthProviders, register } = useAuth();
  const [mode, setMode] = useState("login");
  const [authMessages, setAuthMessages] = useState({ login: "", register: "" });
  const [submitting, setSubmitting] = useState("");
  const isLogin = mode === "login";
  const authRequired = !loading && !authenticated;
  const authScreenVisible = loading || authRequired;
  const authScreenClassName = authScreenVisible ? "auth-screen" : "auth-screen hidden";
  const github = oauthProviders?.github || {};
  const githubEnabled = Boolean(github.enabled);
  const callbackUrl = github.callbackUrl || `${typeof window !== "undefined" ? window.location.origin : ""}/api/auth/oauth/github/callback`;
  const backendUnavailableMessage = BACKEND_UNAVAILABLE_MESSAGE;

  const notifyLegacy = (eventName, detail = {}) => {
    window.dispatchEvent(new CustomEvent(eventName, { detail }));
  };

  const setAuthMessage = (target, message) => {
    setAuthMessages((current) => ({ ...current, [target]: message }));
  };

  const handleLogin = async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const formData = new FormData(form);
    setSubmitting("login");
    setAuthMessage("login", "");
    try {
      const data = await login({
        account: String(formData.get("account") || ""),
        password: String(formData.get("password") || ""),
      });
      notifyLegacy("knowflow:react-auth-success", { user: data?.user, message: "登录成功" });
      form.reset();
    } catch (error) {
      setAuthMessage("login", normalizeErrorMessage(error, "登录失败，请检查账号和密码。"));
    } finally {
      setSubmitting("");
    }
  };

  const handleRegister = async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const formData = new FormData(form);
    setSubmitting("register");
    setAuthMessage("register", "");
    try {
      const data = await register({
        username: String(formData.get("username") || ""),
        email: String(formData.get("email") || ""),
        displayName: String(formData.get("displayName") || ""),
        password: String(formData.get("password") || ""),
      });
      notifyLegacy("knowflow:react-auth-success", { user: data?.user, message: "账号已创建" });
      form.reset();
    } catch (error) {
      setAuthMessage("register", normalizeErrorMessage(error, "注册失败，请检查填写内容。"));
    } finally {
      setSubmitting("");
    }
  };

  const handleGithubLogin = () => {
    if (githubEnabled) {
      const returnTo = `${window.location.origin}/`;
      window.location.href = `/api/auth/oauth/github/start?returnTo=${encodeURIComponent(returnTo)}`;
      return;
    }
    notifyLegacy("knowflow:react-toast", { message: "GitHub OAuth 暂未配置。" });
  };

  const handleCopyGithubCallback = async () => {
    try {
      await copyTextToClipboard(callbackUrl);
      notifyLegacy("knowflow:react-toast", { message: "登录地址已复制" });
    } catch {
      notifyLegacy("knowflow:react-toast", { message: callbackUrl });
    }
  };

  useEffect(() => {
    if (authRequired) {
      setMode("login");
      setAuthMessages({ login: "", register: "" });
      setSubmitting("");
    }
  }, [authRequired]);

  useEffect(() => {
    document.body.classList.toggle("auth-required", authRequired);
    document.querySelector("#app-shell")?.classList.toggle("auth-locked", authRequired);
  }, [authRequired]);

  return (
    <section className={authScreenClassName} id="auth-screen" data-backend-error={backendUnavailableMessage}>
      {loading ? (
        <div className="auth-card auth-loading-card">
          <div className="auth-brand">
            <div className="brand-mark">
              <KnowFlowLogo />
            </div>
            <div>
              <span className="eyebrow">AGENTLENS</span>
              <h1>正在检查登录状态</h1>
            </div>
          </div>
        </div>
      ) : null}
      {!loading ? (
      <div className="auth-card">
        <div className="auth-brand">
          <div className="brand-mark">
            <KnowFlowLogo />
          </div>
          <div>
            <span className="eyebrow">AGENTLENS</span>
            <h1>登录AgentLens</h1>
          </div>
        </div>

        <div className="auth-tabs">
          <button className={isLogin ? "active" : ""} type="button" data-auth-mode="login" onClick={() => setMode("login")}>
            登录
          </button>
          <button className={!isLogin ? "active" : ""} type="button" data-auth-mode="register" onClick={() => setMode("register")}>
            注册
          </button>
        </div>

        <form className={isLogin ? "auth-form" : "auth-form hidden"} id="login-form" onSubmit={handleLogin}>
          <div className={authMessages.login ? "auth-message" : "auth-message hidden"} id="auth-login-message" role="alert">
            {authMessages.login}
          </div>
          <label>
            账号或邮箱<input name="account" autoComplete="username" placeholder="输入用户名或邮箱" required />
          </label>
          <label>
            密码<input name="password" type="password" autoComplete="current-password" placeholder="输入密码" required />
          </label>
          <button type="submit" disabled={submitting === "login"}>{submitting === "login" ? "正在登录..." : "登录"}</button>
        </form>

        <form className={isLogin ? "auth-form hidden" : "auth-form"} id="register-form" onSubmit={handleRegister}>
          <div className={authMessages.register ? "auth-message" : "auth-message hidden"} id="auth-register-message" role="alert">
            {authMessages.register}
          </div>
          <label>
            用户名<input name="username" autoComplete="username" placeholder="设置用户名" required />
          </label>
          <label>
            邮箱<input name="email" type="email" autoComplete="email" placeholder="name@example.com" required />
          </label>
          <label>
            显示名称<input name="displayName" autoComplete="name" placeholder="可选" />
          </label>
          <label>
            密码<input name="password" type="password" autoComplete="new-password" placeholder="至少 6 个字符" required />
          </label>
          <button type="submit" disabled={submitting === "register"}>{submitting === "register" ? "正在创建..." : "创建账号"}</button>
        </form>

        <div className="auth-divider">
          <span>或</span>
        </div>
        <button
          className={githubEnabled ? "auth-provider-button" : "auth-provider-button unavailable"}
          id="github-login-btn"
          type="button"
          disabled={!githubEnabled}
          onClick={handleGithubLogin}
          title={githubEnabled ? "使用 GitHub 继续" : "GitHub 登录未配置"}
        >
          <span className="auth-github-mark" aria-hidden="true">
            <svg viewBox="0 0 24 24" focusable="false">
              <path d="M12 2.8a9.2 9.2 0 0 0-2.9 17.9c.46.08.63-.2.63-.44v-1.55c-2.56.56-3.1-1.1-3.1-1.1-.42-1.06-1.02-1.34-1.02-1.34-.84-.58.06-.57.06-.57.92.06 1.4.95 1.4.95.82 1.4 2.16 1 2.68.76.08-.6.32-1 .58-1.23-2.04-.23-4.18-1.02-4.18-4.54 0-1 .36-1.82.94-2.47-.1-.23-.4-1.17.09-2.43 0 0 .77-.25 2.52.94A8.7 8.7 0 0 1 12 7.4c.78 0 1.55.1 2.28.31 1.75-1.19 2.52-.94 2.52-.94.5 1.26.19 2.2.1 2.43.58.65.93 1.47.93 2.47 0 3.53-2.15 4.3-4.2 4.53.33.29.62.84.62 1.7v2.36c0 .24.16.52.64.43A9.2 9.2 0 0 0 12 2.8Z" />
            </svg>
          </span>
          <strong>{githubEnabled ? "使用 GitHub 继续" : "GitHub 未配置"}</strong>
        </button>
        <details className={githubEnabled ? "oauth-callback-box hidden" : "oauth-callback-box"} id="oauth-callback-box">
          <summary>配置 GitHub 登录</summary>
          <div className="oauth-callback-row">
            <span>登录回调</span>
            <code id="github-callback-url">{callbackUrl}</code>
            <button id="copy-github-callback-btn" type="button" onClick={handleCopyGithubCallback}>
              复制
            </button>
          </div>
        </details>
      </div>
      ) : null}
    </section>
  );
}
