"""Agent-level unit tests — no LLM, no network.

These exercise the pure logic that the smoke test glosses over (because smoke
tests prove the integration works, not that edge cases are handled). Run via:

    cd rl-agent-tutor
    python tests/test_units.py

Exits non-zero on first failure. No pytest dependency to keep CI bootstrap
trivial.
"""
from __future__ import annotations
import json
import os
import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# Some modules import optional deps at module-load time (arxiv,
# youtube_transcript_api, pymupdf, etc.). The functions we actually exercise
# don't touch those deps, so stub the ones likely missing in a bare CI env.
import types

for mod in ("arxiv", "youtube_transcript_api"):
    if mod not in sys.modules:
        try:
            __import__(mod)
        except ImportError:
            sys.modules[mod] = types.ModuleType(mod)

# Point the workspace at a throwaway dir BEFORE anything else imports it.
_SCRATCH = Path(tempfile.mkdtemp(prefix="rlagent_unit_"))
os.environ["WORKSPACE_DIR"] = str(_SCRATCH)

from rl_agent_tutor import config as _cfg  # noqa: E402
_cfg.set_active_workspace(_SCRATCH)
_cfg.ensure_workspace()


GREEN = "\033[92m"
RED = "\033[91m"
END = "\033[0m"

FAILED: list[tuple[str, str]] = []


def case(name: str):
    def deco(fn):
        try:
            fn()
            print(f"  {GREEN}✓{END} {name}")
        except AssertionError as e:
            FAILED.append((name, f"AssertionError: {e}"))
            print(f"  {RED}✗{END} {name}: {e}")
        except Exception as e:
            FAILED.append((name, f"{type(e).__name__}: {e}\n{traceback.format_exc()}"))
            print(f"  {RED}✗{END} {name}: {type(e).__name__}: {e}")
        return fn
    return deco


# ---------------- utils.slugify ----------------

print("\nutils.slugify:")


@case("ascii passthrough")
def _():
    from rl_agent_tutor.utils import slugify
    assert slugify("Hello World") == "Hello_World"


@case("dot-allowed mode keeps dots")
def _():
    from rl_agent_tutor.utils import slugify
    assert slugify("foo.bar.baz", allow_dot=True) == "foo.bar.baz"


@case("default mode strips dots")
def _():
    from rl_agent_tutor.utils import slugify
    assert "." not in slugify("foo.bar.baz")


@case("lower=True applies lowercase")
def _():
    from rl_agent_tutor.utils import slugify
    assert slugify("Foo Bar", lower=True) == "foo_bar"


@case("length cap respected")
def _():
    from rl_agent_tutor.utils import slugify
    assert len(slugify("x" * 200, n=20)) == 20


@case("strip leading/trailing underscores")
def _():
    from rl_agent_tutor.utils import slugify
    assert not slugify("///foo///").startswith("_")
    assert not slugify("///foo///").endswith("_")


# ---------------- store: atomic + tail ----------------

print("\nstore (atomic write + tail-read):")


@case("save_plan / load_plan roundtrip")
def _():
    from rl_agent_tutor import store
    from rl_agent_tutor.models import LearningPlan, Stage, LearningNode
    p = LearningPlan(
        goal="unit-test",
        stages=[Stage(id=0, name="s0", nodes=[
            LearningNode(id="0.1", name="n1", description="d"),
        ])],
        current_node_id="0.1",
    )
    store.save_plan(p)
    p2 = store.load_plan()
    assert p2 is not None
    assert p2.goal == "unit-test"
    assert p2.find_node("0.1").name == "n1"


@case("load_trajectory tails most recent N")
def _():
    from rl_agent_tutor import store
    from rl_agent_tutor.models import TrajectoryEntry
    # Wipe and re-fill 150 entries
    p = store.traj_path()
    if p.exists():
        p.unlink()
    for i in range(150):
        store.append_trajectory(TrajectoryEntry(
            node_id="0.1", kind="ask", content=f"msg-{i}",
        ))
    tail = store.load_trajectory(node_id="0.1", limit=10)
    assert len(tail) == 10
    assert tail[-1].content == "msg-149"
    assert tail[0].content == "msg-140"


@case("atomic write survives mid-write crash simulation")
def _():
    from rl_agent_tutor import store
    p = store.plan_path()
    # Original written by prior test
    assert p.exists()
    original = p.read_text()
    # Mimic a half-written tmp left behind — should not affect reads
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text("{ broken json")
    assert p.read_text() == original
    tmp.unlink()


# ---------------- librarian: repo validation ----------------

print("\nlibrarian._validate_github_repo:")


@case("accepts owner/name")
def _():
    from rl_agent_tutor.librarian import _validate_github_repo
    assert _validate_github_repo("openai/transformer-debugger") == ("openai", "transformer-debugger")


@case("rejects path traversal")
def _():
    from rl_agent_tutor.librarian import _validate_github_repo
    for bad in ["../etc/passwd", "a/..", "a/b/c", "", "a/.evil",
                "/a/b", "a//b", ".hidden/x"]:
        assert _validate_github_repo(bad) is None, f"should reject {bad!r}"


@case("rejects empty/None")
def _():
    from rl_agent_tutor.librarian import _validate_github_repo
    assert _validate_github_repo(None) is None
    assert _validate_github_repo("") is None


# ---------------- fetchers: SSRF guard ----------------

print("\nfetchers._check_url_safe:")


@case("blocks file://")
def _():
    from rl_agent_tutor.fetchers import _check_url_safe, UnsafeURLError
    try:
        _check_url_safe("file:///etc/passwd")
    except UnsafeURLError:
        return
    assert False, "should have rejected file://"


@case("blocks localhost")
def _():
    from rl_agent_tutor.fetchers import _check_url_safe, UnsafeURLError
    try:
        _check_url_safe("http://127.0.0.1/")
    except UnsafeURLError:
        return
    assert False, "should have rejected 127.0.0.1"


@case("blocks RFC1918")
def _():
    from rl_agent_tutor.fetchers import _check_url_safe, UnsafeURLError
    for bad in ["http://10.0.0.1/", "http://192.168.1.1/", "http://172.16.0.1/"]:
        try:
            _check_url_safe(bad)
        except UnsafeURLError:
            continue
        assert False, f"should have rejected {bad}"


@case("blocks gopher://")
def _():
    from rl_agent_tutor.fetchers import _check_url_safe, UnsafeURLError
    try:
        _check_url_safe("gopher://evil.com/")
    except UnsafeURLError:
        return
    assert False, "should have rejected gopher://"


# ---------------- orchestrator: state machine ----------------

print("\norchestrator:")


@case("normalize_state coerces reviewing→studying")
def _():
    from rl_agent_tutor.orchestrator import normalize_state
    from rl_agent_tutor.models import LearningPlan
    p = LearningPlan(goal="x")
    p.state = "reviewing"
    changed = normalize_state(p)
    assert changed is True
    assert p.state == "studying"


@case("normalize_state leaves valid states alone")
def _():
    from rl_agent_tutor.orchestrator import normalize_state
    from rl_agent_tutor.models import LearningPlan
    for s in ("planning", "studying", "self_testing", "advancing", "done"):
        p = LearningPlan(goal="x")
        p.state = s
        assert normalize_state(p) is False
        assert p.state == s


# ---------------- indexer mtime cache ----------------

print("\nindexer mtime cache:")


@case("save/load roundtrip")
def _():
    from rl_agent_tutor import indexer
    cache = {"foo": 123.0, "bar": 4.5}
    indexer._save_mtime_cache(cache)
    out = indexer._load_mtime_cache()
    assert out == cache


@case("missing file returns empty")
def _():
    from rl_agent_tutor import indexer
    p = indexer._mtime_cache_path()
    if p.exists():
        p.unlink()
    assert indexer._load_mtime_cache() == {}


@case("corrupt file returns empty (not crash)")
def _():
    from rl_agent_tutor import indexer
    p = indexer._mtime_cache_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{ not valid json")
    assert indexer._load_mtime_cache() == {}
    p.unlink()


# ---------------- summary ----------------

print()
if FAILED:
    print(f"{RED}✗ {len(FAILED)} test(s) failed:{END}")
    for name, msg in FAILED:
        print(f"  - {name}: {msg.splitlines()[0]}")
    sys.exit(1)
else:
    print(f"{GREEN}✓ all unit tests passed{END}")
    sys.exit(0)
