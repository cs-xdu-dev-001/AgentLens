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
    return (
      <main className={"app-fatal-screen"}>
        <section
          className={"app-fatal-card"}
          role={"alert"}
          aria-labelledby={"app-fatal-title"}
          aria-describedby={"app-fatal-description"}
        >
          <h1 id={"app-fatal-title"}>{"界面暂时无法显示"}</h1>
          <p id={"app-fatal-description"}>
            {"AgentLens遇到了界面错误。请刷新页面；如果问题仍然存在，请关闭此页面后重新打开AgentLens。"}
          </p>
          <button type={"button"} onClick={this.handleRefreshPage}>{"刷新页面"}</button>
        </section>
      </main>
    );
  }
}
