import { notifyError, notifyToast } from "./errorFeedback.js";
import { useEffect, useRef, useState } from "react";
import { knowledgeApi } from "../api/client.js";

const valueOf = (value) => (value === undefined || value === null ? "" : String(value));

const modelLabel = (model) => `${model.name || "未命名模型"} / ${model.modelName || "未知"}`;


function pickEmbeddingValue(models, currentValue) {
  const wanted = valueOf(currentValue);
  if (models.some((model) => valueOf(model.id) === wanted)) return wanted;
  return models.length ? valueOf(models[0].id) : "0";
}

export function KnowledgeModals({ knowledgeModalOpen = false, setKnowledgeModalOpen = () => {} }) {
  const [embeddingModels, setEmbeddingModels] = useState([]);
  const [selectedEmbeddingModelId, setSelectedEmbeddingModelId] = useState("0");
  const [creatingKnowledgeBase, setCreatingKnowledgeBase] = useState(false);
  const nameInputRef = useRef(null);
  const returnFocusRef = useRef(null);

  useEffect(() => {
    const handleModelOptionsUpdated = (event) => {
      const models = Array.isArray(event.detail?.models) ? event.detail.models : [];
      const nextEmbeddingModels = models.filter((model) => model.modelType === "embedding");
      const usableModels = nextEmbeddingModels.length ? nextEmbeddingModels : models;
      setEmbeddingModels(usableModels);
      setSelectedEmbeddingModelId((current) => pickEmbeddingValue(usableModels, event.detail?.selectedEmbeddingModelId ?? current));
    };
    window.addEventListener("knowflow:react-model-options-updated", handleModelOptionsUpdated);
    return () => window.removeEventListener("knowflow:react-model-options-updated", handleModelOptionsUpdated);
  }, []);

  useEffect(() => {
    if (!knowledgeModalOpen) return undefined;
    returnFocusRef.current = document.activeElement;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const timer = window.setTimeout(() => nameInputRef.current?.focus(), 30);
    return () => {
      window.clearTimeout(timer);
      document.body.style.overflow = previousOverflow;
      const previous = returnFocusRef.current;
      window.requestAnimationFrame(() => {
        if (previous && previous.isConnected && typeof previous.focus === "function") {
          previous.focus();
        }
      });
    };
  }, [knowledgeModalOpen]);

  const handleKnowledgeModalBackdrop = (event) => {
    if (event.target === event.currentTarget) {
      setKnowledgeModalOpen(false);
    }
  };

  const handleCloseKnowledgeModal = () => {
    setKnowledgeModalOpen(false);
  };

  useEffect(() => {
    if (!knowledgeModalOpen) return undefined;
    const handleModalKeyDown = (event) => {
      if (event.key === "Escape") handleCloseKnowledgeModal();
    };
    window.addEventListener("keydown", handleModalKeyDown);
    return () => window.removeEventListener("keydown", handleModalKeyDown);
  }, [knowledgeModalOpen]);

  const handleKnowledgeBaseSubmit = async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = Object.fromEntries(new FormData(form).entries());
    if (data.embeddingModelConfigId) data.embeddingModelConfigId = Number(data.embeddingModelConfigId);

    setCreatingKnowledgeBase(true);
    try {
      await knowledgeApi.create(data);
      form.reset();
      setSelectedEmbeddingModelId((current) => pickEmbeddingValue(embeddingModels, current));
      notifyToast("知识库已创建");
      handleCloseKnowledgeModal();
      window.dispatchEvent(new CustomEvent("knowflow:react-knowledge-bases-refresh-request"));
    } catch (error) {
      notifyError(error, "创建知识库失败");
    } finally {
      setCreatingKnowledgeBase(false);
    }
  };

  return (
    <>
      <div className={knowledgeModalOpen ? "modal-backdrop" : "modal-backdrop hidden"} id={"kb-modal"} onClick={handleKnowledgeModalBackdrop}>
        <div className={"modal-panel kb-modal-panel"} role={"dialog"} aria-modal={"true"} aria-labelledby={"kb-modal-title"}>
          <div className={"modal-head"}>
            <div>
              <span className={"eyebrow"}>{"新建空间"}</span>
              <h2 id={"kb-modal-title"}>{"新建知识库"}</h2>
            </div>
            <button type={"button"} className={"icon-button"} id={"close-kb-modal-btn"} aria-label={"关闭知识库窗口"} onClick={handleCloseKnowledgeModal}>
              <svg viewBox={"0 0 24 24"} aria-hidden={"true"} focusable={"false"}>
                <path d={"M6 6l12 12M18 6 6 18"} fill={"none"} stroke={"currentColor"} strokeWidth={"2"} strokeLinecap={"round"} />
              </svg>
            </button>
          </div>
          <form id={"kb-form"} className={"stack-form modal-form"} onSubmit={handleKnowledgeBaseSubmit}>
            <label>
              {"名称"}
              <input name={"name"} ref={nameInputRef} placeholder={"例如：研究笔记"} required />
            </label>
            <label>
              {"描述"}
              <textarea name={"description"} placeholder={"可选"} />
            </label>
            <label>
              {"向量模型"}
              <select name={"embeddingModelConfigId"} id={"kb-embedding-select"} value={selectedEmbeddingModelId} onChange={(event) => setSelectedEmbeddingModelId(event.target.value || "0")}>
                {embeddingModels.length ? (
                  embeddingModels.map((model) => (
                    <option value={valueOf(model.id)} key={model.id}>
                      {modelLabel(model)}
                    </option>
                  ))
                ) : (
                  <option value={"0"}>{"本地哈希向量"}</option>
                )}
              </select>
            </label>
            <div className={"modal-actions"}>
              <button type={"button"} id={"cancel-kb-modal-btn"} onClick={handleCloseKnowledgeModal}>
                {"取消"}
              </button>
              <button type={"submit"} className={"primary"} disabled={creatingKnowledgeBase}>
                {creatingKnowledgeBase ? "正在创建..." : "创建知识库"}
              </button>
            </div>
          </form>
        </div>
      </div>
    </>
  );
}
