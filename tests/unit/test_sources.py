from __future__ import annotations

from rl_agent_tutor import librarian
from rl_agent_tutor.services import resources as resources_service
from rl_agent_tutor.sources import planner
from rl_agent_tutor.sources import load_source_registry, source_config_path
from rl_agent_tutor.store import load_resources


def test_default_sources_are_available(workspace):
    registry = load_source_registry()

    ids = {source.id for source in registry.enabled_sources}

    assert {"arxiv", "github", "youtube", "website", "local-library"} <= ids
    assert "arxiv" in registry.enabled_types()


def test_sources_yaml_can_disable_defaults_and_add_custom_source(workspace):
    path = source_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """
defaults:
  enabled:
    - github
custom_sources:
  - id: hf-blog
    type: rss
    name: Hugging Face Blog
    url: https://huggingface.co/blog/feed.xml
    priority: high
""".strip(),
        encoding="utf-8",
    )

    registry = load_source_registry()
    enabled = {source.id: source for source in registry.enabled_sources}

    assert "github" in enabled
    assert "arxiv" not in enabled
    assert enabled["hf-blog"].type == "rss"
    assert enabled["hf-blog"].priority == "core"
    assert "url=https://huggingface.co/blog/feed.xml" in registry.prompt_hints()


def test_librarian_respects_disabled_source_types(sample_plan, monkeypatch):
    path = source_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """
defaults:
  enabled:
    - github
""".strip(),
        encoding="utf-8",
    )
    registry = load_source_registry()
    calls = {"arxiv": 0, "github": 0}

    monkeypatch.setattr(
        planner,
        "chat_json",
        lambda system, user: {
            "arxiv_queries": ["ppo"],
            "github_repos": ["openai/transformer-debugger"],
            "blog_urls": [],
            "youtube_videos": [],
        },
    )

    def fake_arxiv(*args, **kwargs):
        calls["arxiv"] += 1
        return None

    def fake_github(repo, node_id, code_dir):
        from rl_agent_tutor.models import Resource

        calls["github"] += 1
        return Resource(node_id=node_id, kind="code", title=repo)

    monkeypatch.setattr(librarian, "fetch_arxiv_paper", fake_arxiv)
    monkeypatch.setattr(librarian, "clone_github_repo", fake_github)

    resources = librarian.fetch_for_node(sample_plan.find_node("0.1"), registry=registry)

    assert calls == {"arxiv": 0, "github": 1}
    assert resources[0].source_id == "github"


def test_local_directory_provider_fetches_notes(sample_plan, workspace, monkeypatch):
    manual = workspace / "library" / "manual"
    manual.mkdir(parents=True)
    (manual / "ppo-note.md").write_text("PPO note", encoding="utf-8")
    path = source_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """
defaults:
  enabled:
    - local-library
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        planner,
        "chat_json",
        lambda system, user: {
            "arxiv_queries": [],
            "github_repos": [],
            "blog_urls": [],
            "youtube_videos": [],
        },
    )

    resources = librarian.fetch_for_node(sample_plan.find_node("0.1"))

    assert resources[0].kind == "note"
    assert resources[0].source_id == "local-library"
    assert load_resources("0.1")[0].local_path.endswith("ppo-note.md")
    source = next(item for item in resources_service.list_sources() if item["id"] == "local-library")
    assert source["health"]["last_fetched_at"]
    assert source["health"]["candidate_count"] == 1
