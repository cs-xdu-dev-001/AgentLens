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
  if (!selectedKnowledgeBase) return null;

  return (
    <section className={"knowledge-summary panel"} id={"kb-detail"}>
      <div className={"knowledge-summary-name"}>
        <span>{"当前知识库"}</span>
        <strong>{selectedKnowledgeBase.name}</strong>
      </div>
      <div className={"knowledge-metrics"}>
        <div><span>{"文档"}</span><strong>{selectedKnowledgeBase.document_count || 0}</strong></div>
        <div><span>{"分段"}</span><strong>{selectedKnowledgeBase.chunk_count || 0}</strong></div>
        <div><span>{"向量模型"}</span><strong>{embeddingModel?.name || "未绑定"}</strong></div>
      </div>
    </section>
  );
}
