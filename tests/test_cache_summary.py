from quantgres.experiments.cache_summary import summarize_plan


def test_summarize_plan_extracts_index_names_and_buffers():
    plan = [
        {
            "Plan": {
                "Node Type": "Index Scan",
                "Index Name": "market_onchain_summary_key_idx",
                "Shared Hit Blocks": 3,
                "Shared Read Blocks": 0,
                "Plans": [
                    {
                        "Node Type": "Bitmap Index Scan",
                        "Index Name": "swap_events_pair_block_idx",
                        "Shared Hit Blocks": 5,
                        "Shared Read Blocks": 2,
                    }
                ],
            },
            "Planning Time": 0.11,
            "Execution Time": 0.22,
        }
    ]

    summary = summarize_plan(plan)

    assert summary.root_node_type == "Index Scan"
    assert summary.index_names == (
        "market_onchain_summary_key_idx",
        "swap_events_pair_block_idx",
    )
    assert summary.planning_time_ms == 0.11
    assert summary.execution_time_ms == 0.22
    assert summary.shared_hit_blocks == 8
    assert summary.shared_read_blocks == 2
