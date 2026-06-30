from datetime import UTC, datetime

from quantgres.experiments.event_store import AgentEventDraft, build_event_id, summarize_plan


def test_build_event_id_is_stable_for_canonical_payload_order():
    left = AgentEventDraft(
        event_type="olap_return_panel_observed",
        subject_type="symbol",
        subject_id="BTCUSDT",
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        source="test",
        payload={"b": 2, "a": 1},
    )
    right = AgentEventDraft(
        event_type="olap_return_panel_observed",
        subject_type="symbol",
        subject_id="BTCUSDT",
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        source="test",
        payload={"a": 1, "b": 2},
    )

    assert build_event_id(left) == build_event_id(right)


def test_summarize_plan_extracts_event_store_indexes():
    plan = [
        {
            "Plan": {
                "Node Type": "Bitmap Heap Scan",
                "Shared Hit Blocks": 2,
                "Shared Read Blocks": 0,
                "Plans": [
                    {
                        "Node Type": "Bitmap Index Scan",
                        "Index Name": "agent_events_payload_gin_idx",
                        "Shared Hit Blocks": 3,
                        "Shared Read Blocks": 1,
                    }
                ],
            },
            "Planning Time": 0.4,
            "Execution Time": 0.7,
        }
    ]

    summary = summarize_plan(plan)

    assert summary.root_node_type == "Bitmap Heap Scan"
    assert summary.index_names == ("agent_events_payload_gin_idx",)
    assert summary.planning_time_ms == 0.4
    assert summary.execution_time_ms == 0.7
    assert summary.shared_hit_blocks == 5
    assert summary.shared_read_blocks == 1
