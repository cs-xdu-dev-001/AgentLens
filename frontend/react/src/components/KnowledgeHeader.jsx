import { Database, Plus, Search } from "lucide-react";

export function KnowledgeHeader({ onOpenRetrievalDrawer = () => {}, onOpenKnowledgeBaseModal = () => {} }) {
  const handleOpenRetrievalDrawer = () => {
    onOpenRetrievalDrawer();
  };
  const handleOpenKnowledgeBaseModal = () => {
    onOpenKnowledgeBaseModal();
  };

  return (
    <header className={"knowledge-hero"}>
      <div className={"knowledge-hero-copy"}>
        <span className={"knowledge-hero-icon"} aria-hidden={"true"}>
          <Database size={18} strokeWidth={1.8} />
        </span>
        <div>
          <span className={"eyebrow"}>{"Agent知识"}</span>
          <h1>{"知识库"}</h1>
        </div>
      </div>
      <div className={"hero-actions"}>
        <button id={"open-retrieval-drawer-btn"} type={"button"} aria-label={"检索知识库"} onClick={handleOpenRetrievalDrawer}>
          <Search size={16} strokeWidth={1.9} aria-hidden={"true"} />
          <span>{"检索"}</span>
        </button>
        <button id={"open-kb-modal-btn"} type={"button"} aria-label={"新建知识库"} onClick={handleOpenKnowledgeBaseModal}>
          <Plus size={16} strokeWidth={2} aria-hidden={"true"} />
          <span>{"新建知识库"}</span>
        </button>
      </div>
    </header>
  );
}
