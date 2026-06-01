from __future__ import annotations

from rl_agent_tutor.models import Resource
from rl_agent_tutor.services import resources
from rl_agent_tutor.store import load_resources, load_trajectory


def test_fetch_for_current_node_records_trajectory(sample_plan, monkeypatch):
    monkeypatch.setattr(
        resources.librarian,
        "fetch_for_node",
        lambda node: [Resource(node_id=node.id, kind="blog", title="Blog")],
    )

    result = resources.fetch_for_current_node()

    assert result.node_id == "0.1"
    assert result.resources[0].title == "Blog"
    assert load_trajectory("0.1")[-1].content == "fetched 1 resources"


def test_fetch_blog_for_current_node_appends_resource(sample_plan, monkeypatch):
    monkeypatch.setattr(
        resources.librarian,
        "fetch_blog_resource",
        lambda url, why, node_id, blogs_dir: Resource(
            node_id=node_id, kind="blog", title="Blog", url=url
        ),
    )

    resource = resources.fetch_blog_for_current_node("https://example.com")

    assert resource.title == "Blog"
    assert load_resources("0.1")[0].url == "https://example.com"
