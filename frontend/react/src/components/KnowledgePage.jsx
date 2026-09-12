import { useState } from "react";
import { KnowledgeDocuments } from "./KnowledgeDocuments.jsx";
import { KnowledgeHeader } from "./KnowledgeHeader.jsx";
import { KnowledgeModals } from "./KnowledgeModals.jsx";
import { KnowledgeRail } from "./KnowledgeRail.jsx";
import { KnowledgeRetrievalDrawer } from "./KnowledgeRetrievalDrawer.jsx";
import { KnowledgeSummary } from "./KnowledgeSummary.jsx";

const knowledgeTabs = [
  { key: "documents", label: "文档" },
  { key: "retrieval", label: "检索" },
  { key: "settings", label: "空间设置" },
];

function KnowledgeTabBar({ activeTab, onTabChange }) {
  const handleKeyDown = (event, index) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const nextIndex = event.key === "Home"
      ? 0
      : event.key === "End"
        ? knowledgeTabs.length - 1
        : (index + (event.key === "ArrowRight" ? 1 : -1) + knowledgeTabs.length) % knowledgeTabs.length;
    const nextTab = knowledgeTabs[nextIndex];
    onTabChange(nextTab.key);
    window.requestAnimationFrame(() => document.getElementById(`knowledge-tab-${nextTab.key}`)?.focus());
  };

  return (
    <div className={"knowledge-tabbar"} id={"knowledge-tabbar"} role={"tablist"} aria-label={"知识库视图"}>
      {knowledgeTabs.map((tab) => (
        <button
          aria-controls={`knowledge-${tab.key}-panel`}
          aria-selected={activeTab === tab.key}
          className={activeTab === tab.key ? "knowledge-tab active" : "knowledge-tab"}
          id={`knowledge-tab-${tab.key}`}
          key={tab.key}
          role={"tab"}
          tabIndex={activeTab === tab.key ? 0 : -1}
          type={"button"}
          data-kb-tab={tab.key}
          onKeyDown={(event) => handleKeyDown(event, knowledgeTabs.indexOf(tab))}
          onClick={() => onTabChange(tab.key)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

function KnowledgeSettingsPanel({ active, onTabChange, onOpenKnowledgeBaseModal }) {
  return (
    <section aria-labelledby={"knowledge-tab-settings"} className={active ? "knowledge-tab-panel knowledge-settings-panel active" : "knowledge-tab-panel knowledge-settings-panel"} id={"knowledge-settings-panel"} role={"tabpanel"} data-kb-tab-panel={"settings"}>
      <div className={"settings-panel-card"}>
        <h2>{"知识库设置"}</h2>
        <div className={"knowledge-settings-actions"}>
          <button type={"button"} onClick={onOpenKnowledgeBaseModal}>{"新建知识库"}</button>
          <button type={"button"} onClick={() => onTabChange("retrieval")}>{"检索"}</button>
        </div>
      </div>
    </section>
  );
}

export function KnowledgePage({ active = false }) {
  const [activeTab, setActiveTab] = useState("documents");
  const [uploadModalOpen, setUploadModalOpen] = useState(false);
  const [knowledgeModalOpen, setKnowledgeModalOpen] = useState(false);
  const handleOpenKnowledgeBaseModal = () => setKnowledgeModalOpen(true);
  const handleOpenRetrievalDrawer = () => setActiveTab("retrieval");
  const handleCloseRetrievalDrawer = () => setActiveTab("documents");

  return (
    <section className={active ? "page active" : "page"} id={"page-knowledge"}>
      <div className={"workspace-page knowledge-workspace"}>
        <KnowledgeHeader onOpenRetrievalDrawer={handleOpenRetrievalDrawer} onOpenKnowledgeBaseModal={handleOpenKnowledgeBaseModal} />
        <KnowledgeSummary />
        <div className={"knowledge-shell"}>
          <KnowledgeRail
            onOpenRetrievalDrawer={handleOpenRetrievalDrawer}
            onCreateKnowledgeBase={handleOpenKnowledgeBaseModal}
          />
          <div className={"knowledge-primary"}>
            <KnowledgeTabBar activeTab={activeTab} onTabChange={setActiveTab} />
            <div aria-labelledby={"knowledge-tab-documents"} className={activeTab === "documents" ? "knowledge-tab-panel documents-tab-panel active" : "knowledge-tab-panel documents-tab-panel"} id={"knowledge-documents-panel"} role={"tabpanel"} data-kb-tab-panel={"documents"}>
              <KnowledgeDocuments
                uploadModalOpen={uploadModalOpen}
                setUploadModalOpen={setUploadModalOpen}
                onCreateKnowledgeBase={handleOpenKnowledgeBaseModal}
              />
            </div>
            <div aria-labelledby={"knowledge-tab-retrieval"} className={activeTab === "retrieval" ? "knowledge-tab-panel retrieval-tab-panel active" : "knowledge-tab-panel retrieval-tab-panel"} id={"knowledge-retrieval-panel"} role={"tabpanel"} data-kb-tab-panel={"retrieval"}>
              <KnowledgeRetrievalDrawer active={activeTab === "retrieval"} panel={true} onClose={handleCloseRetrievalDrawer} />
            </div>
            <KnowledgeSettingsPanel active={activeTab === "settings"} onTabChange={setActiveTab} onOpenKnowledgeBaseModal={handleOpenKnowledgeBaseModal} />
          </div>
        </div>
        <KnowledgeModals knowledgeModalOpen={knowledgeModalOpen} setKnowledgeModalOpen={setKnowledgeModalOpen} />
      </div>
    </section>
  );
}
