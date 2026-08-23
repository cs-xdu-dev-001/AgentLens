import React, { Component } from "react";

export class AppErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
    this.handleRefreshPage = this.handleRefreshPage.bind(this);
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error("[AgentLens] React render failed", error, info);
  }

  handleRefreshPage() {
    window.location.reload();
  }

  render() {
    if (!this.state.error) return this.props.children;
    const message = this.state.error?.message || "页面加载失败。";
    return (
      <main className={"app-fatal-screen"} role={"alert"}>
        <section className={"app-fatal-card"}>
          <span className={"eyebrow"}>{"KNOWFLOW AI"}</span>
          <h1>{"页面暂时不可用"}</h1>
          <p>{"刷新后通常可以恢复。"}</p>
          <code>{message}</code>
          <button type={"button"} onClick={this.handleRefreshPage}>{"刷新页面"}</button>
        </section>
      </main>
    );
  }
}
