from __future__ import annotations

import tempfile
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.services.agent_trace import AgentTraceRecorder
from knowflow.services.agent_loop import ToolRegistry
from knowflow.services.langgraph_agent_engine import LangGraphAgentEngine


class FakeGateway:
    def __init__(self):
        self.calls = []

    def complete(
        self,
        messages,
        config,
        *,
        tools=None,
        tool_choice=None,
        event_callback=None,
    ):
        self.calls.append([dict(message) for message in messages])
        return {"role": "assistant", "content": "基于知识库的回答"}


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        gateway = FakeGateway()
        engine = LangGraphAgentEngine(
            gateway=gateway,
            checkpoint_db_path=Path(directory) / "rag-checkpoint.sqlite3",
        )
        calls = []

        def retrieve():
            calls.append("retrieve")
            return {
                "chunks": [
                    {
                        "filename": "guide.md",
                        "chunk_text": "LangGraph将检索结果保存到checkpoint。",
                        "document_id": 1,
                        "chunk_id": 2,
                        "score": 0.91,
                    }
                ],
                "quality": {
                    "enabled": True,
                    "qualityLevel": "strong",
                    "hitCount": 1,
                },
                "retrievalRun": {"id": 7, "status": "success"},
            }

        base_messages = [
            {"role": "system", "content": "Answer with references."},
            {
                "role": "user",
                "content": "References:\nNo relevant references\n\nUser question: test",
            },
        ]
        first_trace = AgentTraceRecorder(run_id="run_rag_checkpoint")
        first = engine.run(
            user_id=17,
            run_id="run_rag_checkpoint",
            messages=base_messages,
            config={},
            registry=ToolRegistry(),
            trace=first_trace,
            retrieval_context=retrieve,
        )
        assert first.answer == "基于知识库的回答"
        assert first.retrieval_completed is True
        assert first.retrieval_chunks[0]["filename"] == "guide.md"
        assert first.retrieval_quality["qualityLevel"] == "strong"
        assert first.retrieval_run["id"] == 7
        assert calls == ["retrieve"]
        assert "guide.md" in gateway.calls[0][1]["content"]
        assert [step["name"] for step in first_trace.snapshot()] == [
            "retrieval_context",
            "model_completion",
        ]

        second = engine.run(
            user_id=17,
            run_id="run_rag_checkpoint",
            messages=base_messages,
            config={},
            registry=ToolRegistry(),
            retrieval_context=retrieve,
        )
        assert second.retrieval_completed is True
        assert second.retrieval_run["id"] == 7
        assert calls == ["retrieve"]
        assert "guide.md" in gateway.calls[1][1]["content"]

        failing_trace = AgentTraceRecorder(run_id="run_rag_degraded")

        def fail_retrieve():
            raise RuntimeError("temporary vector store outage")

        degraded = engine.run(
            user_id=17,
            run_id="run_rag_degraded",
            messages=base_messages,
            config={},
            registry=ToolRegistry(),
            trace=failing_trace,
            retrieval_context=fail_retrieve,
        )
        assert degraded.answer == "基于知识库的回答"
        assert degraded.retrieval_completed is True
        assert degraded.retrieval_quality["qualityLevel"] == "unavailable"
        assert [step["status"] for step in failing_trace.snapshot()] == [
            "failed",
            "success",
        ]

        retry = engine.run(
            user_id=17,
            run_id="run_rag_degraded",
            messages=base_messages,
            config={},
            registry=ToolRegistry(),
            retrieval_context=retrieve,
        )
        assert retry.retrieval_quality["qualityLevel"] == "strong"
        assert retry.retrieval_run["id"] == 7
        assert calls == ["retrieve", "retrieve"]

        recorded_failure_trace = AgentTraceRecorder(
            run_id="run_rag_recorded_failure"
        )
        recorded_failure = engine.run(
            user_id=17,
            run_id="run_rag_recorded_failure",
            messages=base_messages,
            config={},
            registry=ToolRegistry(),
            trace=recorded_failure_trace,
            retrieval_context=lambda: {
                "chunks": [],
                "quality": {
                    "enabled": True,
                    "qualityLevel": "unavailable",
                    "hitCount": 0,
                },
                "retrievalRun": {"id": 8, "status": "failed"},
            },
        )
        assert recorded_failure.answer == "基于知识库的回答"
        assert recorded_failure.retrieval_run["status"] == "failed"
        assert recorded_failure_trace.snapshot()[0]["status"] == "failed"
        assert (
            recorded_failure_trace.snapshot()[0]["errorCode"]
            == "retrieval_failed"
        )
    print("LangGraph RAG retrieval is checkpointed and not repeated")


if __name__ == "__main__":
    main()
