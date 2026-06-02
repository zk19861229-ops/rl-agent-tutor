from __future__ import annotations

from rl_agent_tutor.models import Resource
from rl_agent_tutor.services import evidence
from rl_agent_tutor.store import append_resource, load_resources


def test_mark_node_resources_updates_status_and_used_by(workspace):
    append_resource(Resource(node_id="0.1", kind="paper", title="Paper", local_path="/tmp/p.pdf"))
    append_resource(Resource(node_id="0.2", kind="blog", title="Other"))

    touched = evidence.mark_node_resources(
        "0.1",
        status="read",
        used_by="courseware:path",
        only_with_local_content=True,
    )

    assert len(touched) == 1
    resources = load_resources()
    assert resources[0].status == "read"
    assert resources[0].used_by == ["courseware:path"]
    assert resources[1].status == "fetched"


def test_mark_node_resources_does_not_downgrade_status(workspace):
    append_resource(
        Resource(
            node_id="0.1",
            kind="paper",
            title="Paper",
            status="tested",
            used_by=["test:one"],
        )
    )

    evidence.mark_node_resources("0.1", status="read", used_by="courseware:two")

    resource = load_resources("0.1")[0]
    assert resource.status == "tested"
    assert resource.used_by == ["test:one", "courseware:two"]


def test_evidence_summary_counts_status_priority_and_usage(workspace):
    append_resource(
        Resource(
            node_id="0.1",
            kind="paper",
            title="Core",
            priority="core",
            status="cited",
            used_by=["tutor:ask"],
        )
    )
    append_resource(Resource(node_id="0.1", kind="blog", title="Extra"))

    summary = evidence.summarize_node("0.1")

    assert summary.total == 2
    assert summary.by_status == {"cited": 1, "fetched": 1}
    assert summary.by_priority == {"core": 1, "normal": 1}
    assert summary.used == 1
