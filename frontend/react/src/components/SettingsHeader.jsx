import { Plus } from "lucide-react";

export function SettingsHeader({ onCreate, disabled = false, modelCount = 0 }) {
  return (
    <header className={"settings-header"}>
      <div className={"settings-heading"}>
        <h1>{"模型配置"}</h1>
        <span className={"settings-count"}>{`${modelCount}个配置`}</span>
      </div>
      <button
        type={"button"}
        disabled={disabled}
        onClick={onCreate}
      >
        <Plus size={16} strokeWidth={2} aria-hidden={"true"} />
        <span>{"新建配置"}</span>
      </button>
    </header>
  );
}
