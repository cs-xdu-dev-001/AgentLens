import { notifyError, notifyToast } from "./errorFeedback.js";
import { useCallback, useEffect, useRef, useState } from "react";
import { Database, FileText, MoreHorizontal, Plus, Search } from "lucide-react";
import { knowledgeApi } from "../api/client.js";
import { useAuth } from "../auth/AuthProvider.jsx";


function sameId(left, right) {
  return String(left ?? "") === String(right ?? "");
}

function pickSelectedKnowledgeBaseId(knowledgeBases, preferredId) {
  if (!knowledgeBases.length) return null;
  const preferred = knowledgeBases.find((kb) => sameId(kb.id, preferredId));
  return preferred?.id || knowledgeBases[0].id;
}

function syncKnowledgeBases(knowledgeBases, selectedKnowledgeBaseId) {
  window.dispatchEvent(
    new CustomEvent("knowflow:react-knowledge-bases-sync", {
      detail: { knowledgeBases, selectedKnowledgeBaseId },
    }),
  );
}

function syncKnowledgeSelection(selectedKnowledgeBaseId) {
  window.dispatchEvent(
    new CustomEvent("knowflow:react-knowledge-selection-sync", {
      detail: { selectedKnowledgeBaseId },
    }),
  );
}

export function KnowledgeRail({ onOpenRetrievalDrawer = () => {}, onCreateKnowledgeBase = () => {} }) {
  const { authenticated } = useAuth();
  const [knowledgeBases, setKnowledgeBases] = useState([]);
  const [selectedKnowledgeBaseId, setSelectedKnowledgeBaseId] = useState(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [openMenuKnowledgeBaseId, setOpenMenuKnowledgeBaseId] = useState(null);
  const selectedKnowledgeBaseIdRef = useRef(null);
  const railRef = useRef(null);

  useEffect(() => {
    selectedKnowledgeBaseIdRef.current = selectedKnowledgeBaseId;
  }, [selectedKnowledgeBaseId]);

  const loadKnowledgeBases = useCallback(async () => {
    if (!authenticated) {
      setKnowledgeBases([]);
      setSelectedKnowledgeBaseId(null);
      syncKnowledgeBases([], null);
      return [];
    }

    try {
      const response = await knowledgeApi.list();
      const nextKnowledgeBases = Array.isArray(response) ? response : [];
      const nextSelectedKnowledgeBaseId = pickSelectedKnowledgeBaseId(nextKnowledgeBases, selectedKnowledgeBaseIdRef.current);
      setKnowledgeBases(nextKnowledgeBases);
      setSelectedKnowledgeBaseId(nextSelectedKnowledgeBaseId);
      syncKnowledgeBases(nextKnowledgeBases, nextSelectedKnowledgeBaseId);
      return nextKnowledgeBases;
    } catch (error) {
      notifyError(error, "刷新知识库失败");
      return [];
    }
  }, [authenticated]);

  useEffect(() => {
    const handleKnowledgeOptionsUpdated = (event) => {
      const nextKnowledgeBases = Array.isArray(event.detail?.knowledgeBases)
        ? event.detail.knowledgeBases
        : [];
      const nextSelectedKnowledgeBaseId = pickSelectedKnowledgeBaseId(
        nextKnowledgeBases,
        event.detail?.selectedKnowledgeBaseId,
      );
      setKnowledgeBases(nextKnowledgeBases);
      setSelectedKnowledgeBaseId(nextSelectedKnowledgeBaseId);
    };
    window.addEventListener(
      "knowflow:react-knowledge-options-updated",
      handleKnowledgeOptionsUpdated,
    );
    return () => window.removeEventListener(
      "knowflow:react-knowledge-options-updated",
      handleKnowledgeOptionsUpdated,
    );
  }, []);

  useEffect(() => {
    window.addEventListener("knowflow:react-knowledge-bases-refresh-request", loadKnowledgeBases);
    return () => window.removeEventListener("knowflow:react-knowledge-bases-refresh-request", loadKnowledgeBases);
  }, [loadKnowledgeBases]);

  useEffect(() => {
    const closeMenu = (event) => {
      if (!railRef.current?.contains(event.target)) {
        setOpenMenuKnowledgeBaseId(null);
      }
    };
    document.addEventListener("click", closeMenu);
    return () => document.removeEventListener("click", closeMenu);
  }, []);

  const handleKnowledgeSearch = (event) => {
    setSearchQuery(event.target.value || "");
  };

  const handleKnowledgeMenuToggle = (event, knowledgeBaseId) => {
    event.stopPropagation();
    setOpenMenuKnowledgeBaseId((current) => (sameId(current, knowledgeBaseId) ? null : knowledgeBaseId));
  };

  const handleKnowledgeBaseSelect = (knowledgeBaseId) => {
    setOpenMenuKnowledgeBaseId(null);
    setSelectedKnowledgeBaseId(knowledgeBaseId || null);
    syncKnowledgeSelection(knowledgeBaseId || null);
  };

  const handleOpenRetrievalDrawer = (knowledgeBaseId) => {
    handleKnowledgeBaseSelect(knowledgeBaseId);
    onOpenRetrievalDrawer(knowledgeBaseId);
  };

  const handleKnowledgeBaseDelete = async (knowledgeBaseId) => {
    try {
      await knowledgeApi.delete(knowledgeBaseId);
      const nextKnowledgeBases = knowledgeBases.filter((kb) => !sameId(kb.id, knowledgeBaseId));
      const nextPreferredId = sameId(selectedKnowledgeBaseId, knowledgeBaseId) ? null : selectedKnowledgeBaseId;
      const nextSelectedKnowledgeBaseId = pickSelectedKnowledgeBaseId(nextKnowledgeBases, nextPreferredId);
      setOpenMenuKnowledgeBaseId(null);
      setKnowledgeBases(nextKnowledgeBases);
      setSelectedKnowledgeBaseId(nextSelectedKnowledgeBaseId);
      syncKnowledgeBases(nextKnowledgeBases, nextSelectedKnowledgeBaseId);
      notifyToast("知识库已删除");
    } catch (error) {
      notifyError(error, "删除知识库失败");
    }
  };

  const keyword = searchQuery.trim().toLowerCase();
  const filteredKnowledgeBases = keyword
    ? knowledgeBases.filter((kb) => `${kb.name || ""} ${kb.description || ""}`.toLowerCase().includes(keyword))
    : knowledgeBases;

  return (
    <aside className={"knowledge-rail"} ref={railRef}>
      <div className={"kb-list-header"}>
        <div className={"kb-list-heading"}>
          <span className={"kb-list-icon"} aria-hidden={"true"}>
            <Database size={16} strokeWidth={1.9} />
          </span>
          <div>
            <span className={"section-label"}>{"空间"}</span>
            <h2>{"知识库"}</h2>
          </div>
        </div>
        <button className={"kb-create-button"} type={"button"} onClick={onCreateKnowledgeBase} aria-label={"新建知识库"}>
          <Plus size={16} strokeWidth={2} aria-hidden={"true"} />
        </button>
      </div>
      <label className={"kb-search-box"}>
        <Search size={15} strokeWidth={1.9} aria-hidden={"true"} />
        <span className={"visually-hidden"}>{"搜索知识库"}</span>
        <input id={"kb-search-input"} type={"search"} placeholder={"按名称或描述搜索"} value={searchQuery} onChange={handleKnowledgeSearch} />
      </label>
      <div className={"list kb-card-list"} id={"kb-list"}>
        {filteredKnowledgeBases.length ? (
          filteredKnowledgeBases.map((kb) => {
            const isActive = sameId(kb.id, selectedKnowledgeBaseId);
            const isOpen = sameId(openMenuKnowledgeBaseId, kb.id);
            return (
              <article className={["kb-row", isActive ? "active" : "", isOpen ? "menu-open" : ""].filter(Boolean).join(" ")} data-kb-row={kb.id} key={kb.id}>
                <button className={"kb-row-main"} type={"button"} onClick={() => handleKnowledgeBaseSelect(kb.id)}>
                  <span className={"kb-row-icon"} aria-hidden={"true"}>
                    <FileText size={15} strokeWidth={1.8} />
                  </span>
                  <span className={"kb-row-copy"}>
                    <span className={"kb-row-title"}>{kb.name}</span>
                    <span className={"kb-row-desc"}>{kb.description || "暂无描述"}</span>
                    <span className={"kb-row-meta"}>{`${kb.document_count || 0} 个文档 · ${kb.chunk_count || 0} 个分段`}</span>
                  </span>
                </button>
                <button className={"session-menu-button"} type={"button"} onClick={(event) => handleKnowledgeMenuToggle(event, kb.id)} aria-label={"知识库操作"}>
                  <MoreHorizontal size={17} strokeWidth={1.9} aria-hidden={"true"} />
                </button>
                <div className={"session-popover kb-popover"}>
                  <button type={"button"} onClick={() => handleKnowledgeBaseSelect(kb.id)}>
                    {"打开"}
                  </button>
                  <button type={"button"} onClick={() => handleOpenRetrievalDrawer(kb.id)}>
                    {"检索"}
                  </button>
                  <button className={"danger"} type={"button"} onClick={() => handleKnowledgeBaseDelete(kb.id)}>
                    {"删除"}
                  </button>
                </div>
              </article>
            );
          })
        ) : (
          <div className={"kb-empty"}>
            <span className={"kb-empty-icon"} aria-hidden={"true"}>
              <Database size={20} strokeWidth={1.7} />
            </span>
            <strong>{keyword ? "没有匹配的空间" : "还没有知识库"}</strong>
            <span>{keyword ? "换个关键词试试" : "创建一个空间，把文档交给Agent检索"}</span>
            {!keyword ? (
              <button type={"button"} onClick={onCreateKnowledgeBase}>
                <Plus size={15} strokeWidth={2} aria-hidden={"true"} />
                {"创建知识库"}
              </button>
            ) : null}
          </div>
        )}
      </div>
    </aside>
  );
}
