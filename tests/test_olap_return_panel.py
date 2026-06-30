from quantgres.experiments.olap_return_panel import summarize_plan


def test_summarize_plan_extracts_index_and_buffer_summary():
    plan = [
        {
            "Plan": {
                "Node Type": "Limit",
                "Shared Hit Blocks": 1,
                "Shared Read Blocks": 0,
                "Plans": [
                    {
                        "Node Type": "Index Scan",
                        "Index Name": "market_return_panel_symbol_ts_idx",
                        "Shared Hit Blocks": 4,
                        "Shared Read Blocks": 2,
                    }
                ],
            },
            "Planning Time": 0.3,
            "Execution Time": 0.5,
        }
    ]

    summary = summarize_plan(plan)

    assert summary.root_node_type == "Limit"
    assert summary.index_names == ("market_return_panel_symbol_ts_idx",)
    assert summary.planning_time_ms == 0.3
    assert summary.execution_time_ms == 0.5
    assert summary.shared_hit_blocks == 5
    assert summary.shared_read_blocks == 2
