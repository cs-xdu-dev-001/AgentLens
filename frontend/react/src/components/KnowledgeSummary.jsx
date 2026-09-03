import { Database, FileText, Layers3, ScanSearch } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

const valueOf = (value) => (value === undefined || value === null ? "" : String(value));

export function KnowledgeSummary() {
  const [knowledgeBases, setKnowledgeBases] = useState([]);
  const [models, setModels] = useState([]);
  const [selectedKnowledgeBaseId, setSelectedKnowledgeBaseId] = useState(null);
  useEffect(() => {
    const handleKnowledgeOptionsUpdated = (event) => { setKnowledgeBases(Array.isArray(event.detail?.knowledgeBases) ? event.detail.knowledgeBases : []); setSelectedKnowledgeBaseId(event.detail?.selectedKnowledgeBaseId || null); };
    const handleKnowledgeSelectionUpdated = (event) => { if (Object.prototype.hasOwnProperty.call(event.detail || {}, "selectedKnowledgeBaseId")) setSelectedKnowledgeBaseId(event.detail?.selectedKnowledgeBaseId || null); };
    const handleModelOptionsUpdated = (event) => setModels(Array.isArray(event.detail?.models) ? event.detail.models : []);
    window.addEventListener("knowflow:react-knowledge-options-updated", handleKnowledgeOptionsUpdated);
    window.addEventListener("knowflow:react-knowledge-selection-updated", handleKnowledgeSelectionUpdated);
    window.addEventListener("knowflow:react-model-options-updated", handleModelOptionsUpdated);
    return () => { window.removeEventListener("knowflow:react-knowledge-options-updated", handleKnowledgeOptionsUpdated); window.removeEventListener("knowflow:react-knowledge-selection-updated", handleKnowledgeSelectionUpdated); window.removeEventListener("knowflow:react-model-options-updated", handleModelOptionsUpdated); };
  }, []);
  const selectedKnowledgeBase = useMemo(() => knowledgeBases.find((kb) => valueOf(kb.id) === valueOf(selectedKnowledgeBaseId)) || null, [knowledgeBases, selectedKnowledgeBaseId]);
  const embeddingModel = useMemo(() => models.find((model) => valueOf(model.id) === valueOf(selectedKnowledgeBase?.embeddingModelConfigId || selectedKnowledgeBase?.embedding_model_config_id)) || null, [models, selectedKnowledgeBase]);
  return (
    <section className={selectedKnowledgeBase ? "knowledge-summary panel" : "knowledge-summary panel is-empty"} id={"kb-detail"}>
      <div className={"knowledge-summary-name"}>
        <span className={"knowledge-summary-icon"} aria-hidden={"true"}>
          <Database size={16} strokeWidth={1.8} />
        </span>
        <div>
          <span>{"当前空间"}</span>
          <strong>{selectedKnowledgeBase?.name || "尚未创建知识库"}</strong>
        </div>
      </div>
      <div className={"knowledge-metrics"}>
        <div><FileText size={15} strokeWidth={1.8} aria-hidden={"true"} /><span>{"文档"}</span><strong>{selectedKnowledgeBase?.document_count || 0}</strong></div>
        <div><Layers3 size={15} strokeWidth={1.8} aria-hidden={"true"} /><span>{"分段"}</span><strong>{selectedKnowledgeBase?.chunk_count || 0}</strong></div>
        <div><ScanSearch size={15} strokeWidth={1.8} aria-hidden={"true"} /><span>{"向量模型"}</span><strong>{embeddingModel?.name || "未绑定"}</strong></div>
      </div>
    </section>
  );
}
