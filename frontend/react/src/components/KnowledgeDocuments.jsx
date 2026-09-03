import { notifyError, notifyToast } from "./errorFeedback.js";
import { useCallback, useEffect, useRef, useState } from "react";
import { Database, FileText, Layers3, Plus, UploadCloud } from "lucide-react";
import { documentApi } from "../api/client.js";

const documentSteps = [
  { key: "uploading", label: "上传中" },
  { key: "parsing", label: "解析中" },
  { key: "chunking", label: "切分中" },
  { key: "embedding", label: "向量化" },
  { key: "success", label: "已入库" },
];

const documentStatusIndex = {
  uploading: 0,
  pending: 0,
  processing: 1,
  parsing: 1,
  chunking: 2,
  embedding: 3,
  success: 4,
  failed: 1,
};

const statusText = {
  pending: "等待中",
  processing: "处理中",
  uploading: "上传中",
  parsing: "解析中",
  chunking: "切分中",
  embedding: "向量化",
  success: "可用",
  failed: "失败",
};

const MAX_CLIENT_UPLOAD_SIZE = 25 * 1024 * 1024;
const CLIENT_ALLOWED_SUFFIXES = new Set([
  ".txt",
  ".md",
  ".markdown",
  ".log",
  ".yaml",
  ".yml",
  ".xml",
  ".json",
  ".csv",
  ".tsv",
  ".html",
  ".htm",
  ".rtf",
  ".pdf",
  ".docx",
  ".xlsx",
  ".xlsm",
  ".pptx",
  ".png",
  ".jpg",
  ".jpeg",
  ".webp",
  ".gif",
  ".bmp",
]);

function formatBytes(size) {
  const value = Number(size || 0);
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

const valueOf = (value) => (value === undefined || value === null ? "" : String(value));


function fileSuffix(filename) {
  const name = String(filename || "");
  const dotIndex = name.lastIndexOf(".");
  return dotIndex >= 0 ? name.slice(dotIndex).toLowerCase() : "";
}

function validateDocumentUploadFile(file) {
  if (!file?.name) throw new Error("请先选择文档");
  const suffix = fileSuffix(file.name);
  if (!CLIENT_ALLOWED_SUFFIXES.has(suffix)) {
    throw new Error(`暂不支持该文件类型：${suffix || "无扩展名"}`);
  }
  if (file.size > MAX_CLIENT_UPLOAD_SIZE) {
    throw new Error(`文件不能超过 ${formatBytes(MAX_CLIENT_UPLOAD_SIZE)}`);
  }
}

function optimisticDocument(file, tempId, knowledgeBaseId) {
  return {
    id: tempId,
    temporary: true,
    local_status: "queued-local",
    knowledge_base_id: Number(knowledgeBaseId || 0) || knowledgeBaseId || "",
    filename: file.name,
    file_type: file.name.split(".").pop() || "file",
    file_size: file.size || 0,
    parse_status: "uploading",
    chunk_count: 0,
    updated_at: "刚刚",
    latestTask: { stage: "uploading", status: "running", progress: 8 },
  };
}

function sameDocumentIdentity(left, right) {
  const leftServerId = Number(left.server_document_id || 0);
  const leftId = Number(left.id || 0);
  const rightId = Number(right.id || right.document_id || 0);
  if (leftServerId > 0 && rightId > 0) return leftServerId === rightId;
  if (leftId > 0 && rightId > 0) return leftId === rightId;

  const sameOriginalName = String(left.original_filename || left.filename || "") === String(right.original_filename || right.filename || "");
  const sameStoredName = String(left.filename || "") === String(right.filename || "");
  const sameSize = Number(left.file_size || 0) > 0 && Number(left.file_size || 0) === Number(right.file_size || 0);
  return (sameOriginalName || sameStoredName) && sameSize;
}

function mergePendingDocuments(documents, pendingDocuments, selectedKnowledgeBaseId) {
  const knowledgeBaseId = String(selectedKnowledgeBaseId || "");
  const serverDocuments = documents || [];
  const pending = pendingDocuments.filter((document) => {
    if (knowledgeBaseId && String(document.knowledge_base_id || "") !== knowledgeBaseId) return false;
    return !serverDocuments.some((serverDocument) => sameDocumentIdentity(document, serverDocument));
  });
  return [...pending, ...serverDocuments];
}

function markPendingDocumentProcessing(pendingDocuments, tempId, payload = {}) {
  return pendingDocuments.map((document) =>
    document.id === tempId
      ? {
          ...document,
          server_document_id: payload.documentId || payload.id || document.server_document_id,
          parse_status: payload.parseStatus || "processing",
          latestTask: { stage: payload.parseStatus || "processing", status: "running", progress: 35 },
    updated_at: "刚刚",
        }
      : document,
  );
}

function failPendingDocument(pendingDocuments, tempId, message) {
  return pendingDocuments.map((document) =>
    document.id === tempId
      ? {
          ...document,
          parse_status: "failed",
          error_message: message || "上传失败",
          latestTask: { stage: "failed", status: "failed", progress: 100 },
        }
      : document,
  );
}

function clearResolvedPendingDocuments(pendingDocuments, serverDocuments) {
  return pendingDocuments.filter(
    (document) => document.parse_status === "failed" || !serverDocuments.some((serverDocument) => sameDocumentIdentity(document, serverDocument)),
  );
}

function isDocumentProcessing(document) {
  const status = document.parse_status || document.latestTask?.stage || "";
  return ["pending", "uploading", "processing", "parsing", "chunking", "embedding"].includes(status);
}

function requestKnowledgeBaseStatsRefresh() {
  window.dispatchEvent(new CustomEvent("knowflow:react-knowledge-bases-refresh-request"));
}

function pickKnowledgeValue(knowledgeBases, currentValue) {
  const wanted = valueOf(currentValue);
  if (knowledgeBases.some((kb) => valueOf(kb.id) === wanted)) return wanted;
  return "";
}

function DocumentSteps({ document }) {
  const status = document.parse_status || "pending";
  const activeIndex = documentStatusIndex[status] ?? 0;
  return (
    <div className={"document-steps"}>
      {documentSteps.map((step, index) => {
        const done = status === "success" ? index <= activeIndex : index < activeIndex;
        const current = status !== "success" && status !== "failed" && index === activeIndex;
        const failed = status === "failed" && index === activeIndex;
        const className = ["document-step", done ? "done" : "", current ? "current" : "", failed ? "failed" : ""].filter(Boolean).join(" ");
        return (
          <span className={className} key={step.key}>
            <span></span>
            {step.label}
          </span>
        );
      })}
    </div>
  );
}

export function KnowledgeDocuments({ uploadModalOpen = false, setUploadModalOpen = () => {}, onCreateKnowledgeBase = () => {} }) {
  const [busyDocumentId, setBusyDocumentId] = useState(null);
  const [dragging, setDragging] = useState(false);
  const [documents, setDocuments] = useState([]);
  const [chunks, setChunks] = useState([]);
  const [chunksLoading, setChunksLoading] = useState(false);
  const [chunkModalOpen, setChunkModalOpen] = useState(false);
  const [knowledgeBases, setKnowledgeBases] = useState([]);
  const [pendingDocuments, setPendingDocuments] = useState([]);
  const [selectedKnowledgeBaseId, setSelectedKnowledgeBaseId] = useState("");
  const [selectedDocumentFile, setSelectedDocumentFile] = useState(null);
  const [uploadingDocument, setUploadingDocument] = useState(false);
  const fileInputRef = useRef(null);

  const loadDocuments = useCallback(async (knowledgeBaseId = selectedKnowledgeBaseId) => {
    if (!knowledgeBaseId) {
      setDocuments([]);
      setPendingDocuments((currentPendingDocuments) => clearResolvedPendingDocuments(currentPendingDocuments, []));
      return [];
    }

    try {
      const nextDocuments = await documentApi.list(knowledgeBaseId);
      const safeDocuments = Array.isArray(nextDocuments) ? nextDocuments : [];
      setDocuments(safeDocuments);
      setPendingDocuments((currentPendingDocuments) => clearResolvedPendingDocuments(currentPendingDocuments, safeDocuments));
      return safeDocuments;
    } catch (error) {
      notifyError(error, "刷新文档失败");
      return [];
    }
  }, [selectedKnowledgeBaseId]);

  useEffect(() => {
    loadDocuments(selectedKnowledgeBaseId);
  }, [selectedKnowledgeBaseId, loadDocuments]);

  useEffect(() => {
    if (!selectedKnowledgeBaseId || !documents.some(isDocumentProcessing)) return undefined;
    const timer = window.setTimeout(async () => {
      const nextDocuments = await loadDocuments(selectedKnowledgeBaseId);
      if (!nextDocuments.some(isDocumentProcessing)) requestKnowledgeBaseStatsRefresh();
    }, 1400);
    return () => window.clearTimeout(timer);
  }, [documents, selectedKnowledgeBaseId, loadDocuments]);

  useEffect(() => {
    const handleKnowledgeOptionsUpdated = (event) => {
      const nextKnowledgeBases = Array.isArray(event.detail?.knowledgeBases) ? event.detail.knowledgeBases : [];
      setKnowledgeBases(nextKnowledgeBases);
      setSelectedKnowledgeBaseId((current) =>
        pickKnowledgeValue(nextKnowledgeBases, event.detail?.selectedDocumentKnowledgeBaseId ?? current),
      );
    };
    const handleKnowledgeSelectionUpdated = (event) => {
      if (!Object.prototype.hasOwnProperty.call(event.detail || {}, "selectedDocumentKnowledgeBaseId")) return;
      setSelectedKnowledgeBaseId(valueOf(event.detail?.selectedDocumentKnowledgeBaseId));
    };
    window.addEventListener("knowflow:react-knowledge-options-updated", handleKnowledgeOptionsUpdated);
    window.addEventListener("knowflow:react-knowledge-selection-updated", handleKnowledgeSelectionUpdated);
    return () => {
      window.removeEventListener("knowflow:react-knowledge-options-updated", handleKnowledgeOptionsUpdated);
      window.removeEventListener("knowflow:react-knowledge-selection-updated", handleKnowledgeSelectionUpdated);
    };
  }, []);

  const handleOpenUploadModal = () => {
    setUploadModalOpen(true);
  };

  const handleCloseUploadModal = () => {
    setUploadModalOpen(false);
  };

  const handleUploadModalBackdrop = (event) => {
    if (event.target === event.currentTarget) {
      handleCloseUploadModal();
    }
  };

  const handleCloseChunkModal = () => {
    setChunkModalOpen(false);
  };

  useEffect(() => {
    if (!uploadModalOpen && !chunkModalOpen) return undefined;
    const handleModalKeyDown = (event) => {
      if (event.key === "Escape") {
        if (chunkModalOpen) handleCloseChunkModal();
        else handleCloseUploadModal();
      }
    };
    window.addEventListener("keydown", handleModalKeyDown);
    return () => window.removeEventListener("keydown", handleModalKeyDown);
  }, [chunkModalOpen, uploadModalOpen]);

  const handleChunkModalBackdrop = (event) => {
    if (event.target === event.currentTarget) {
      handleCloseChunkModal();
    }
  };

  const clearSelectedDocumentFile = () => {
    setSelectedDocumentFile(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const handleSelectedDocumentFile = (file) => {
    try {
      if (file) validateDocumentUploadFile(file);
      setSelectedDocumentFile(file || null);
    } catch (error) {
      notifyError(error, "文件不可用");
      clearSelectedDocumentFile();
    }
  };

  const handleDocumentFileChange = (event) => {
    handleSelectedDocumentFile(event.target.files?.[0] || null);
  };

  const handleDocumentDragStart = (event) => {
    event.preventDefault();
    event.stopPropagation();
    setDragging(true);
  };

  const handleDocumentDragEnd = (event) => {
    event.preventDefault();
    event.stopPropagation();
    setDragging(false);
  };

  const handleDocumentDrop = (event) => {
    event.preventDefault();
    event.stopPropagation();
    setDragging(false);
    handleSelectedDocumentFile(event.dataTransfer?.files?.[0] || null);
  };

  const handleDocumentKnowledgeBaseChange = (event) => {
    const value = event.target.value || "";
    setSelectedKnowledgeBaseId(value);
    window.dispatchEvent(new CustomEvent("knowflow:react-knowledge-selection-sync", { detail: { selectedKnowledgeBaseId: value } }));
  };

  const handleDocumentSubmit = async (event) => {
    event.preventDefault();
    if (!selectedKnowledgeBaseId) {
      notifyToast("请先创建知识库");
      return;
    }
    if (!selectedDocumentFile?.name) {
      notifyToast("请先选择文档");
      return;
    }

    try {
      validateDocumentUploadFile(selectedDocumentFile);
    } catch (error) {
      notifyError(error, "文件不可用");
      return;
    }

    const tempId = -Date.now();
    setUploadingDocument(true);
    setPendingDocuments((currentPendingDocuments) => [
      optimisticDocument(selectedDocumentFile, tempId, selectedKnowledgeBaseId),
      ...currentPendingDocuments.filter((document) => document.id !== tempId),
    ]);

    try {
      const result = await documentApi.upload(selectedKnowledgeBaseId, selectedDocumentFile);
      setPendingDocuments((currentPendingDocuments) => markPendingDocumentProcessing(currentPendingDocuments, tempId, result));
      notifyToast("文档已上传，开始索引");
      clearSelectedDocumentFile();
      setUploadModalOpen(false);
      const nextDocuments = await loadDocuments(selectedKnowledgeBaseId);
      if (!nextDocuments.some(isDocumentProcessing)) requestKnowledgeBaseStatsRefresh();
    } catch (error) {
      setPendingDocuments((currentPendingDocuments) => failPendingDocument(currentPendingDocuments, tempId, error.message || "上传失败"));
      notifyError(error, "上传失败");
    } finally {
      setUploadingDocument(false);
    }
  };

  const handleLoadDocumentChunks = async (documentId) => {
    setChunkModalOpen(true);
    setChunks([]);
    setChunksLoading(true);
    try {
      const nextChunks = await documentApi.chunks(documentId);
      setChunks(Array.isArray(nextChunks) ? nextChunks : []);
    } catch (error) {
      setChunks([]);
      notifyError(error, "加载分段失败");
    } finally {
      setChunksLoading(false);
    }
  };

  const handleReindexDocument = async (documentId) => {
    try {
      setBusyDocumentId(documentId);
      setDocuments((currentDocuments) =>
        currentDocuments.map((document) =>
          Number(document.id) === Number(documentId) ? { ...document, parse_status: "parsing", error_message: "", updated_at: "刚刚" } : document,
        ),
      );
      await documentApi.reindex(documentId);
      notifyToast("文档已开始重新索引");
      const nextDocuments = await loadDocuments(selectedKnowledgeBaseId);
      if (!nextDocuments.some(isDocumentProcessing)) requestKnowledgeBaseStatsRefresh();
    } catch (error) {
      notifyError(error, "重新索引失败");
    } finally {
      setBusyDocumentId(null);
    }
  };

  const handleDeleteDocument = async (documentId) => {
    try {
      setBusyDocumentId(documentId);
      await documentApi.delete(documentId);
      setDocuments((currentDocuments) => currentDocuments.filter((document) => Number(document.id) !== Number(documentId)));
      notifyToast("文档已删除");
      await loadDocuments(selectedKnowledgeBaseId);
      requestKnowledgeBaseStatsRefresh();
    } catch (error) {
      notifyError(error, "删除文档失败");
    } finally {
      setBusyDocumentId(null);
    }
  };

  const handlePendingDocumentRemove = (documentId) => {
    setPendingDocuments((currentPendingDocuments) => currentPendingDocuments.filter((document) => document.id !== documentId));
  };

  const visibleDocuments = mergePendingDocuments(documents, pendingDocuments, selectedKnowledgeBaseId);
  const dropZoneClassName = ["file-drop", dragging ? "dragging" : "", selectedDocumentFile ? "has-file" : ""]
    .filter(Boolean)
    .join(" ");

  return (
    <section className={"documents-tab-content"}>
      <div className={"document-toolbar compact-toolbar"}>
        <div>
          <span className={"eyebrow"}>{"文档"}</span>
          <h2>{"文档"}</h2>
        </div>
        <label className={"active-kb-select"}>
          <span>{"当前知识库"}</span>
          <select id={"doc-kb-select"} name={"knowledgeBaseId"} value={selectedKnowledgeBaseId} onChange={handleDocumentKnowledgeBaseChange}>
            {knowledgeBases.length ? (
              knowledgeBases.map((kb) => (
                <option value={valueOf(kb.id)} key={kb.id}>
                  {kb.name}
                </option>
              ))
            ) : (
              <option value={""}>{"暂无知识库"}</option>
            )}
          </select>
        </label>
        <button
          className={"upload-modal-trigger"}
          id={"upload-modal-trigger"}
          type={"button"}
          title={selectedKnowledgeBaseId ? "添加文档" : "请先创建知识库"}
          disabled={!selectedKnowledgeBaseId}
          onClick={handleOpenUploadModal}
        >
          {"添加文档"}
        </button>
      </div>
      <div className={uploadModalOpen ? "modal-backdrop upload-modal" : "modal-backdrop upload-modal hidden"} id={"upload-modal"} onClick={handleUploadModalBackdrop}>
        <section className={"modal-panel upload-modal-panel"} role={"dialog"} aria-modal={"true"} aria-labelledby={"upload-modal-title"}>
          <header className={"modal-head"}>
            <div>
              <span className={"eyebrow"}>{"上传"}</span>
              <h2 id={"upload-modal-title"}>{"上传到知识库"}</h2>
            </div>
            <button className={"icon-button"} type={"button"} onClick={handleCloseUploadModal} aria-label={"关闭上传窗口"}>
              <svg viewBox={"0 0 24 24"} aria-hidden={"true"} focusable={"false"}>
                <path d={"M6 6l12 12M18 6 6 18"} fill={"none"} stroke={"currentColor"} strokeWidth={"2"} strokeLinecap={"round"} />
              </svg>
            </button>
          </header>
          <div className={"upload-modal-body"}>
            <form className={"upload-zone upload-zone-compact"} id={"document-form"} onSubmit={handleDocumentSubmit}>
              <input name={"knowledgeBaseId"} id={"doc-kb-hidden"} type={"hidden"} value={selectedKnowledgeBaseId} readOnly />
              <label
                className={dropZoneClassName}
                id={"document-drop-zone"}
                onDragEnter={handleDocumentDragStart}
                onDragOver={handleDocumentDragStart}
                onDragLeave={handleDocumentDragEnd}
                onDragEnd={handleDocumentDragEnd}
                onDrop={handleDocumentDrop}
              >
                <input
                  name={"file"}
                  id={"document-file-input"}
                  ref={fileInputRef}
                  type={"file"}
                  accept={".txt,.md,.markdown,.pdf,.docx,.xlsx,.xlsm,.pptx,.html,.htm,.json,.csv,.tsv,.yaml,.yml,.xml,.log,.rtf"}
                  onChange={handleDocumentFileChange}
                />
                <span>{"拖入或选择文档"}</span>
                <small>{"支持常用文档格式"}</small>
                <small className={"file-selected-text"} id={"document-file-name"}>
                  {selectedDocumentFile ? `${selectedDocumentFile.name} - ${formatBytes(selectedDocumentFile.size || 0)}` : "尚未选择文档"}
                </small>
              </label>
              <button type={"submit"} disabled={uploadingDocument || !selectedDocumentFile}>
                {uploadingDocument ? "正在上传..." : "上传并索引"}
              </button>
            </form>
            <aside className={"upload-queue-summary"}>
              <strong>{"索引流程"}</strong>
              <span>{"上传中"}</span>
              <span>{"解析中"}</span>
              <span>{"切分中"}</span>
              <span>{"已入库"}</span>
            </aside>
          </div>
        </section>
      </div>
      <section className={"panel document-table-panel"}>
        <div className={"document-table"} id={"document-list"}>
          {visibleDocuments.length ? (
            visibleDocuments.map((document) => {
              const statusClass = document.parse_status === "success" ? "ok" : document.parse_status === "failed" ? "warn" : "progress";
              const retryLabel = document.parse_status === "failed" ? "重试" : "重新索引";
              const rowClassName = ["document-row", document.temporary ? "queued-local" : "", document.parse_status || ""].filter(Boolean).join(" ");
              return (
                <article className={rowClassName} key={document.id}>
                  <div className={"document-row-main"}>
                    <h3>{document.filename}</h3>
                    <p>{`${document.file_type || "file"} - ${formatBytes(document.file_size)} - 更新 ${document.updated_at || document.created_at || "刚刚"}`}</p>
                    {document.parse_status === "failed" && document.error_message ? (
                      <div className={"document-error"}>{`原因：${document.error_message}`}</div>
                    ) : null}
                  </div>
                  <div className={"document-row-status"}>
                    <span className={["badge", statusClass].filter(Boolean).join(" ")}>{statusText[document.parse_status] || document.parse_status || "未设置"}</span>
                    <DocumentSteps document={document} />
                  </div>
                  <div className={"document-row-meta"}>
                    <strong>{document.chunk_count || 0}</strong>
                    <span>{"分段"}</span>
                  </div>
                  <div className={"document-row-actions"}>
                    {Number(document.id) > 0 ? (
                      <>
                        <button type={"button"} disabled={busyDocumentId === document.id} onClick={() => handleLoadDocumentChunks(document.id)}>
                          {"分段"}
                        </button>
                        <button type={"button"} disabled={busyDocumentId === document.id} onClick={() => handleReindexDocument(document.id)}>
                          {retryLabel}
                        </button>
                        <button className={"danger"} type={"button"} disabled={busyDocumentId === document.id} onClick={() => handleDeleteDocument(document.id)}>
                          {"删除"}
                        </button>
                      </>
                    ) : document.parse_status === "failed" ? (
                      <button type={"button"} onClick={() => handlePendingDocumentRemove(document.id)}>
                        {"移除"}
                      </button>
                    ) : (
                      <button type={"button"} disabled>
                        {"等待中"}
                      </button>
                    )}
                  </div>
                </article>
              );
            })
          ) : (
            <div className={selectedKnowledgeBaseId ? "document-empty" : "document-empty unconfigured"}>
              <span className={"document-empty-icon"} aria-hidden={"true"}>
                {selectedKnowledgeBaseId ? <FileText size={24} strokeWidth={1.6} /> : <Database size={24} strokeWidth={1.6} />}
              </span>
              <h3>{selectedKnowledgeBaseId ? "这个空间还没有文档" : "先创建一个知识库"}</h3>
              <p>{selectedKnowledgeBaseId ? "上传资料后，Agent会自动解析、切分并建立可检索索引。" : "知识库是Agent检索和引用资料的工作空间。"}</p>
              <button type={"button"} onClick={selectedKnowledgeBaseId ? handleOpenUploadModal : onCreateKnowledgeBase}>
                {selectedKnowledgeBaseId ? <UploadCloud size={16} strokeWidth={1.8} aria-hidden={"true"} /> : <Plus size={16} strokeWidth={2} aria-hidden={"true"} />}
                {selectedKnowledgeBaseId ? "添加第一份文档" : "创建知识库"}
              </button>
              {selectedKnowledgeBaseId ? (
                <span className={"document-empty-hint"}>
                  <Layers3 size={14} strokeWidth={1.7} aria-hidden={"true"} />
                  {"支持PDF、Markdown、DOCX、CSV等常用格式"}
                </span>
              ) : null}
            </div>
          )}
        </div>
      </section>
      <div className={chunkModalOpen ? "modal-backdrop" : "modal-backdrop hidden"} id={"chunk-modal"} onClick={handleChunkModalBackdrop}>
        <div className={"modal-panel chunk-modal-panel"} role={"dialog"} aria-modal={"true"} aria-labelledby={"chunk-modal-title"}>
          <div className={"modal-head"}>
            <div>
              <span className={"eyebrow"}>{"分段"}</span>
              <h2 id={"chunk-modal-title"}>{"文档分段"}</h2>
            </div>
            <button type={"button"} className={"icon-button"} id={"close-chunk-modal-btn"} aria-label={"关闭分段窗口"} onClick={handleCloseChunkModal}>
              <svg viewBox={"0 0 24 24"} aria-hidden={"true"} focusable={"false"}>
                <path d={"M6 6l12 12M18 6 6 18"} fill={"none"} stroke={"currentColor"} strokeWidth={"2"} strokeLinecap={"round"} />
              </svg>
            </button>
          </div>
          <div className={"chunk-list"} id={"chunk-list"}>
            {chunksLoading ? <p className={"empty-state"}>{"正在加载分段..."}</p> : null}
            {!chunksLoading && !chunks.length ? <p className={"empty-state"}>{"暂无分段"}</p> : null}
            {!chunksLoading
              ? chunks.map((chunk, index) => (
                  <div className={"chunk"} key={`${chunk.id || chunk.chunk_index || index}`}>
                    <strong>{`#${chunk.chunk_index ?? index + 1}`}</strong>
                    {` ${chunk.chunk_text || chunk.content || ""}`}
                  </div>
                ))
              : null}
          </div>
        </div>
      </div>
    </section>
  );
}
