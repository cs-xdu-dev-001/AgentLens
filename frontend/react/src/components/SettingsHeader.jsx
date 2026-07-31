export function SettingsHeader({ onCreate, disabled = false }) {
  return (
    <header className={"settings-header"}>
      <h1>{"模型配置"}</h1>
      <button
        type={"button"}
        disabled={disabled}
        onClick={onCreate}
      >
        {"新建配置"}
      </button>
    </header>
  );
}
