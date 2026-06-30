from quantgres.experiments.jsonb_index_benchmark import summarize_plan


def test_summarize_plan_extracts_nested_index_names_and_buffers():
    plan = [
        {
            "Plan": {
                "Node Type": "Aggregate",
                "Shared Hit Blocks": 1,
                "Shared Read Blocks": 0,
                "Plans": [
                    {
                        "Node Type": "Bitmap Heap Scan",
                        "Shared Hit Blocks": 2,
                        "Shared Read Blocks": 3,
                        "Plans": [
                            {
                                "Node Type": "Bitmap Index Scan",
                                "Index Name": "jsonb_path_ops_benchmark_payload_gin_idx",
                                "Shared Hit Blocks": 4,
                                "Shared Read Blocks": 5,
                            }
                        ],
                    }
                ],
            },
            "Planning Time": 0.12,
            "Execution Time": 0.34,
        }
    ]

    summary = summarize_plan(plan)

    assert summary.root_node_type == "Aggregate"
    assert summary.index_names == ("jsonb_path_ops_benchmark_payload_gin_idx",)
    assert summary.planning_time_ms == 0.12
    assert summary.execution_time_ms == 0.34
    assert summary.shared_hit_blocks == 7
    assert summary.shared_read_blocks == 8
