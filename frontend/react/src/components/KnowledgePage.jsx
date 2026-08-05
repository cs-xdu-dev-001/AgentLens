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
  return (
    <div className={"knowledge-tabbar"} id={"knowledge-tabbar"}>
      {knowledgeTabs.map((tab) => (
        <button className={activeTab === tab.key ? "knowledge-tab active" : "knowledge-tab"} key={tab.key} type={"button"} data-kb-tab={tab.key} onClick={() => onTabChange(tab.key)}>
          {tab.label}
        </button>
      ))}
    </div>
  );
}

function KnowledgeSettingsPanel({ active, onTabChange, onOpenKnowledgeBaseModal }) {
  return (
    <section className={active ? "knowledge-tab-panel knowledge-settings-panel active" : "knowledge-tab-panel knowledge-settings-panel"} id={"knowledge-settings-panel"} data-kb-tab-panel={"settings"}>
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
          <KnowledgeRail onOpenRetrievalDrawer={handleOpenRetrievalDrawer} />
          <div className={"knowledge-primary"}>
            <KnowledgeTabBar activeTab={activeTab} onTabChange={setActiveTab} />
            <div className={activeTab === "documents" ? "knowledge-tab-panel documents-tab-panel active" : "knowledge-tab-panel documents-tab-panel"} data-kb-tab-panel={"documents"}>
              <KnowledgeDocuments uploadModalOpen={uploadModalOpen} setUploadModalOpen={setUploadModalOpen} />
            </div>
            <div className={activeTab === "retrieval" ? "knowledge-tab-panel retrieval-tab-panel active" : "knowledge-tab-panel retrieval-tab-panel"} data-kb-tab-panel={"retrieval"}>
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
