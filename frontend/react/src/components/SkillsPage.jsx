import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { skillApi } from "../api/client.js";
import { SkillDetailDrawer } from "./SkillDetailDrawer.jsx";
import { SkillInstallDialog } from "./SkillInstallDialog.jsx";

const statusOf = (skill) => {
  if (!skill?.available) return "unavailable";
  return skill.enabled ? "enabled" : "disabled";
};

const statusLabel = {
  unavailable: "依赖缺失",
  enabled: "已启用",
  disabled: "已停用",
};

const sourceLabel = (skill) => {
  if (skill?.sourceKind === "builtin" || skill?.owner === "builtin") return "内置";
  if (skill?.sourceKind === "github") return "GitHub";
  if (skill?.sourceKind === "upload") return "本地ZIP";
  return "个人";
};

const dependencyText = (skill) => {
  const missing = [
    ...(skill?.missingTools || []),
    ...(skill?.missingMcp || []),
  ];
  return missing.length ? `缺少：${missing.join("、")}` : "依赖完整";
};

const dispatchSkillsUpdated = (skill = null) => {
  window.dispatchEvent(
    new CustomEvent("knowflow:react-skills-updated", {
      detail: { skill },
    }),
  );
};

export function SkillsPage({ active = false }) {
  const [skills, setSkills] = useState([]);
  const [activeTab, setActiveTab] = useState("installed");
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [busySkillId, setBusySkillId] = useState(null);
  const [rowErrorById, setRowErrorById] = useState({});
  const [installOpen, setInstallOpen] = useState(false);
  const [selectedSkill, setSelectedSkill] = useState(null);
  const mountedRef = useRef(false);
  const activeRef = useRef(active);
  const requestGenerationRef = useRef(0);
  activeRef.current = active;

  const canCommitRequest = useCallback(
    (requestId) =>
      mountedRef.current &&
      activeRef.current &&
      requestId === requestGenerationRef.current,
    [],
  );

  const loadSkills = useCallback(async () => {
    const requestId = ++requestGenerationRef.current;
    if (!canCommitRequest(requestId)) return;
    setLoading(true);
    setLoadError("");
    try {
      const items = await skillApi.list();
      if (!canCommitRequest(requestId)) return;
      setSkills(Array.isArray(items) ? items : []);
    } catch (error) {
      if (!canCommitRequest(requestId)) return;
      setLoadError(error?.message || "无法加载Skills，请稍后重试。");
    } finally {
      if (!canCommitRequest(requestId)) return;
      setLoading(false);
    }
  }, [canCommitRequest]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      requestGenerationRef.current += 1;
    };
  }, []);

  useEffect(() => {
    activeRef.current = active;
    requestGenerationRef.current += 1;
    if (active) loadSkills();
  }, [active, loadSkills]);

  const filteredSkills = useMemo(() => {
    const keyword = query.trim().toLocaleLowerCase();
    return skills.filter((skill) => {
      const builtin =
        skill?.sourceKind === "builtin" || skill?.owner === "builtin";
      if (activeTab === "built-in" ? !builtin : builtin) return false;
      const status = statusOf(skill);
      if (statusFilter !== "all" && status !== statusFilter) return false;
      if (!keyword) return true;
      return [
        skill?.name,
        skill?.slug,
        skill?.description,
        skill?.version,
        sourceLabel(skill),
        ...(skill?.requiredTools || []),
        ...(skill?.requiredMcp || []),
      ]
        .filter(Boolean)
        .join(" ")
        .toLocaleLowerCase()
        .includes(keyword);
    });
  }, [activeTab, query, skills, statusFilter]);

  const replaceSkill = useCallback((updated) => {
    if (!updated?.id) return;
    setSkills((current) =>
      current.map((skill) => (skill.id === updated.id ? updated : skill)),
    );
    setSelectedSkill((current) =>
      current?.id === updated.id ? updated : current,
    );
  }, []);

  const handleEnabledChange = async (event, skill) => {
    event.stopPropagation();
    const enabled = !skill.enabled;
    setBusySkillId(skill.id);
    setRowErrorById((current) => ({ ...current, [skill.id]: "" }));
    try {
      const updated = await skillApi.setEnabled(skill.id, enabled);
      replaceSkill(updated);
      dispatchSkillsUpdated(updated);
    } catch (error) {
      setRowErrorById((current) => ({
        ...current,
        [skill.id]: error?.message || "更新状态失败。",
      }));
    } finally {
      setBusySkillId(null);
    }
  };

  const handleMutation = useCallback(
    async (updated) => {
      if (updated?.id) replaceSkill(updated);
      else await loadSkills();
      if (updated === null) setSelectedSkill(null);
    },
    [loadSkills, replaceSkill],
  );

  const handleInstalled = useCallback(async () => {
    setActiveTab("installed");
    await loadSkills();
  }, [loadSkills]);

  return (
    <section className={active ? "page active" : "page"} id={"page-skills"}>
      <div className={"workspace-page skills-workspace"}>
        <header className={"settings-header skills-header"}>
          <h1>{"Skills"}</h1>
          <button
            className={"skills-primary-button"}
            type={"button"}
            onClick={() => setInstallOpen(true)}
          >
            {"安装Skill"}
          </button>
        </header>

        <div className={"skills-content"}>
          <div className={"skills-tabs"} role={"tablist"} aria-label={"Skill来源"}>
            <button
              className={activeTab === "installed" ? "active" : ""}
              type={"button"}
              role={"tab"}
              aria-selected={activeTab === "installed"}
              onClick={() => setActiveTab("installed")}
            >
              {"已安装"}
            </button>
            <button
              className={activeTab === "built-in" ? "active" : ""}
              type={"button"}
              role={"tab"}
              aria-selected={activeTab === "built-in"}
              onClick={() => setActiveTab("built-in")}
            >
              {"内置"}
            </button>
          </div>

          <div className={"skills-toolbar"}>
            <label className={"skills-search"}>
              <span className={"visually-hidden"}>{"搜索Skills"}</span>
              <input
                value={query}
                type={"search"}
                placeholder={"搜索名称、依赖或来源"}
                onChange={(event) => setQuery(event.target.value)}
              />
            </label>
            <label className={"skills-filter"}>
              <span className={"visually-hidden"}>{"按状态筛选"}</span>
              <select
                value={statusFilter}
                aria-label={"按状态筛选"}
                onChange={(event) => setStatusFilter(event.target.value)}
              >
                <option value={"all"}>{"全部状态"}</option>
                <option value={"enabled"}>{"已启用"}</option>
                <option value={"disabled"}>{"已停用"}</option>
                <option value={"unavailable"}>{"依赖缺失"}</option>
              </select>
            </label>
          </div>

          <div className={"skills-list"} aria-live={"polite"}>
            {loading ? (
              <div className={"skills-list-state"}>{"正在加载Skills..."}</div>
            ) : null}
            {!loading && loadError ? (
              <div className={"skills-list-state error"}>
                <span>{loadError}</span>
                <button type={"button"} onClick={loadSkills}>{"重试"}</button>
              </div>
            ) : null}
            {!loading && !loadError && !filteredSkills.length ? (
              <div className={"skills-list-state"}>
                {query || statusFilter !== "all"
                  ? "没有符合筛选条件的Skill。"
                  : activeTab === "built-in"
                    ? "暂无内置Skill。"
                    : "尚未安装个人Skill。"}
              </div>
            ) : null}
            {!loading && !loadError
              ? filteredSkills.map((skill) => {
                  const status = statusOf(skill);
                  return (
                    <div
                      className={[
                        "skills-list-row",
                        selectedSkill?.id === skill.id ? "selected" : "",
                      ].filter(Boolean).join(" ")}
                      key={skill.id}
                      role={"button"}
                      tabIndex={0}
                      onClick={() => setSelectedSkill(skill)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          setSelectedSkill(skill);
                        }
                      }}
                    >
                      <div className={"skill-row-main"}>
                        <div className={"skill-row-title"}>
                          <strong>{skill.name || skill.slug || "未命名Skill"}</strong>
                          <span>{skill.version || "未标版本"}</span>
                        </div>
                        <p>{skill.description || "此Skill没有说明。"}</p>
                      </div>
                      <div className={"skill-row-source"}>
                        <span>{"来源"}</span>
                        <strong>{sourceLabel(skill)}</strong>
                      </div>
                      <div className={`skill-row-deps ${skill.available ? "" : "missing"}`}>
                        <span>{"依赖"}</span>
                        <strong title={dependencyText(skill)}>
                          {dependencyText(skill)}
                        </strong>
                      </div>
                      <div className={"skill-row-status"}>
                        <span className={`skill-status ${status}`}>
                          {statusLabel[status]}
                        </span>
                        <button
                          className={"skill-switch"}
                          type={"button"}
                          role={"switch"}
                          aria-checked={Boolean(skill.enabled)}
                          aria-label={`${skill.enabled ? "停用" : "启用"}${skill.name || skill.slug}`}
                          disabled={
                            Boolean(busySkillId) ||
                            (!skill.available && !skill.enabled)
                          }
                          onClick={(event) => handleEnabledChange(event, skill)}
                        >
                          <span aria-hidden={"true"} />
                        </button>
                      </div>
                      {rowErrorById[skill.id] ? (
                        <div className={"skill-row-error"} role={"alert"}>
                          {rowErrorById[skill.id]}
                        </div>
                      ) : null}
                    </div>
                  );
                })
              : null}
          </div>
        </div>
      </div>

      <SkillInstallDialog
        open={installOpen}
        onClose={() => setInstallOpen(false)}
        onInstalled={handleInstalled}
      />
      <SkillDetailDrawer
        skill={selectedSkill}
        onClose={() => setSelectedSkill(null)}
        onMutated={handleMutation}
      />
    </section>
  );
}
