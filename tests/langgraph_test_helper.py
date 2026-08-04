from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

from knowflow.services.langgraph_agent_engine import LangGraphAgentEngine


def run_langgraph_agent(
    *,
    gateway,
    messages,
    config,
    registry,
    trace=None,
    parent_step_id=None,
    skill_snapshot=None,
    execution_callback=None,
    model_event_callback=None,
    max_tool_rounds=3,
    user_id=17,
    run_id=None,
    skill_restore=None,
    memory_recall=None,
    memory_enabled=False,
    retrieval_context=None,
):
    with tempfile.TemporaryDirectory() as temp_dir:
        engine = LangGraphAgentEngine(
            gateway=gateway,
            max_tool_rounds=max_tool_rounds,
            checkpoint_db_path=(
                Path(temp_dir) / "langgraph-checkpoints.sqlite3"
            ),
        )
        return engine.run(
            user_id=user_id,
            run_id=run_id or f"run_test_{uuid.uuid4().hex}",
            messages=messages,
            config=config,
            registry=registry,
            trace=trace,
            parent_step_id=parent_step_id,
            skill_snapshot=skill_snapshot,
            execution_callback=execution_callback,
            model_event_callback=model_event_callback,
            skill_restore=(skill_restore or (lambda snapshot: None)),
            memory_recall=memory_recall,
            memory_enabled=memory_enabled,
            retrieval_context=retrieval_context,
        )
