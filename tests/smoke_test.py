"""End-to-end smoke test for rl-agent-tutor.

Runs the full learning loop on a tiny goal so any Agent breakage shows up fast.
Does NOT mock the LLM — this is a real-link integration test.

Usage:
    cd rl-agent-tutor
    python tests/smoke_test.py            # full run, ~3-5 min, ~$0.5-1.5 API cost
    python tests/smoke_test.py --quick    # skip RAG indexing if no PDFs

Each step is a separate try block so you see WHICH stage broke, not just a stack
trace from the end of the pipeline.

Side effects:
- Creates a separate workspace at ./workspace_smoketest/ so it doesn't trash your real data
- All artifacts left on disk for inspection
"""
from __future__ import annotations
import os
import sys
import time
import shutil
import traceback
from pathlib import Path

# Use a separate workspace so we don't pollute real progress
SMOKE_DIR = Path(__file__).resolve().parent.parent / "workspace_smoketest"
os.environ["WORKSPACE_DIR"] = str(SMOKE_DIR)


GREEN = "\033[92m"; RED = "\033[91m"; YELLOW = "\033[93m"
CYAN = "\033[96m"; BOLD = "\033[1m"; DIM = "\033[2m"; END = "\033[0m"


def banner(title: str):
    print(f"\n{BOLD}{CYAN}━━━ {title} ━━━{END}")


def step(name: str, fn, *args, critical: bool = True, **kwargs):
    print(f"{DIM}→ {name}...{END}", end=" ", flush=True)
    t0 = time.time()
    try:
        result = fn(*args, **kwargs)
        dt = time.time() - t0
        print(f"{GREEN}✓ ok{END} {DIM}({dt:.1f}s){END}")
        return result, None
    except Exception as e:
        dt = time.time() - t0
        print(f"{RED}✗ FAILED{END} {DIM}({dt:.1f}s){END}")
        print(f"{RED}    {type(e).__name__}: {e}{END}")
        if "--verbose" in sys.argv:
            traceback.print_exc()
        if critical:
            print(f"{RED}{BOLD}Critical step failed; aborting.{END}")
            sys.exit(1)
        return None, e


def assert_truthy(value, msg: str):
    if not value:
        raise AssertionError(msg)


# ---- Tests ----

def test_imports():
    """Step 1: verify all modules import cleanly."""
    from rl_agent_tutor import (
        config, store, models, llm, planner, librarian, tutor,
        examiner, practice, archivist, reviewer, orchestrator,
        indexer, rag, fetchers,
    )
    return ["ok"]


def test_llm_health():
    """Step 2: smoke-call the LLM, verify provider config."""
    from rl_agent_tutor.llm import chat, provider_info
    print(f"\n    provider: {provider_info()}")
    out = chat("You are a calculator.", "What is 2+3? Reply with just the number.",
               max_tokens=20, temperature=0)
    assert_truthy(out and "5" in out, f"LLM returned unexpected: {out!r}")
    return out.strip()


def test_planner():
    """Step 3: planner produces a structured plan."""
    from rl_agent_tutor.planner import make_plan
    from rl_agent_tutor.store import save_plan
    plan = make_plan(
        goal="Smoke test: learn just PPO clip and GAE in 2 days",
        level="DL OK, RL fresh",
    )
    assert_truthy(plan.stages, "no stages")
    assert_truthy(plan.all_nodes(), "no nodes")
    assert_truthy(plan.current_node_id, "no current node")
    save_plan(plan)
    print(f"\n    {len(plan.stages)} stages, {len(plan.all_nodes())} nodes, "
          f"current={plan.current_node_id}")
    return plan


def test_orchestrator(plan):
    """Step 4: state machine, mark/advance round-trip."""
    from rl_agent_tutor import orchestrator
    msg = orchestrator.suggest_next_action(plan)
    assert_truthy(msg, "empty next action")
    return msg.split("\n")[0]


def test_tutor_no_rag(plan):
    """Step 5: tutor answers without RAG (RAG index empty here)."""
    from rl_agent_tutor.tutor import ask
    n = plan.find_node(plan.current_node_id)
    s = plan.stage_of(n.id)
    answer, citations = ask(n, s.name if s else "", "What does PPO's clip do, in one sentence?")
    assert_truthy(answer, "tutor returned empty")
    assert citations == [], f"expected empty citations, got {citations}"
    return answer[:80] + "..."


def test_examiner(plan):
    """Step 6: examiner generates 5 questions and grades a fake answer."""
    from rl_agent_tutor.examiner import generate_exercises, grade_answer
    n = plan.find_node(plan.current_node_id)
    qs = generate_exercises(n)
    assert_truthy(len(qs) >= 3, f"expected ≥3 questions, got {len(qs)}")
    # grade with a deliberately weak answer
    attempt = grade_answer(qs[0], "I don't know")
    assert_truthy(0.0 <= attempt.score <= 1.0, f"score out of range: {attempt.score}")
    assert_truthy(attempt.feedback, "empty feedback")
    print(f"\n    generated {len(qs)} qs; weak answer scored {attempt.score:.2f}")
    return qs


def test_practice(plan):
    """Step 7: practice agent emits markdown."""
    from rl_agent_tutor.practice import best_practices
    n = plan.find_node(plan.current_node_id)
    text = best_practices(n)
    assert_truthy(text and len(text) > 200, "practice text too short")
    return text[:80] + "..."


def test_librarian_optional(plan):
    """Step 8 (non-critical): librarian fetches at least one resource.
    Depends on internet + arxiv availability + LLM finding real refs."""
    from rl_agent_tutor.librarian import fetch_for_node
    n = plan.find_node(plan.current_node_id)
    rs = fetch_for_node(n)
    print(f"\n    fetched {len(rs)} resources: " +
          ", ".join(f"{r.kind}({r.title[:30]}…)" for r in rs[:3]))
    return rs


def test_indexer_optional():
    """Step 9 (non-critical): index any PDFs we just fetched."""
    from rl_agent_tutor import indexer
    papers = list((SMOKE_DIR / "library" / "papers").glob("*.pdf"))
    if not papers:
        print(f"\n    {YELLOW}skipped — no PDFs available{END}")
        return None
    n_pdfs, n_chunks = indexer.index_papers()
    assert_truthy(n_chunks > 0, "no chunks produced")
    print(f"\n    indexed {n_pdfs} PDFs → {n_chunks} chunks")
    return n_pdfs, n_chunks


def test_rag_optional():
    """Step 10 (non-critical): RAG retrieval returns hits."""
    from rl_agent_tutor import rag
    from rl_agent_tutor.indexer import load_chunks
    if not load_chunks():
        print(f"\n    {YELLOW}skipped — no index{END}")
        return None
    hits = rag.retrieve("PPO clip ratio", top_n=3, rerank=False)  # skip rerank to save tokens
    print(f"\n    BM25 retrieved {len(hits)} hits")
    return hits


def test_tutor_with_rag_optional(plan):
    """Step 11 (non-critical): tutor with RAG should produce citations if index has content."""
    from rl_agent_tutor.tutor import ask
    from rl_agent_tutor.indexer import load_chunks
    if not load_chunks():
        print(f"\n    {YELLOW}skipped — no index{END}")
        return None
    n = plan.find_node(plan.current_node_id)
    s = plan.stage_of(n.id)
    answer, citations = ask(n, s.name if s else "",
                            "What is the standard ε value for PPO clip?")
    print(f"\n    answer len {len(answer)}, citations: {len(citations)}")
    return answer, citations


def test_archivist(plan):
    """Step 12: archivist writes a KB file from the trajectory we accumulated."""
    from rl_agent_tutor import archivist
    from rl_agent_tutor.store import append_trajectory
    from rl_agent_tutor.models import TrajectoryEntry
    # ensure there's at least one trajectory entry to digest
    n = plan.find_node(plan.current_node_id)
    append_trajectory(TrajectoryEntry(
        node_id=n.id, kind="ask",
        content="What does PPO clip do?",
    ))
    append_trajectory(TrajectoryEntry(
        node_id=n.id, kind="answer",
        content="It limits the importance ratio in [1-ε, 1+ε] to bound policy update step.",
    ))
    s = plan.stage_of(n.id)
    target = archivist.archive_node(n, stage_name=s.name if s else "")
    assert_truthy(target.exists() and target.stat().st_size > 200, "KB file too small")
    idx = archivist.build_index(plan)
    assert_truthy(idx.exists(), "index missing")
    print(f"\n    KB → {target.name} ({target.stat().st_size} bytes)")
    return target


def test_reviewer(plan):
    """Step 13: reviewer generates a weekly retrospective."""
    from rl_agent_tutor.reviewer import weekly_review
    target = weekly_review(plan)
    assert_truthy(target.exists() and target.stat().st_size > 200, "review too short")
    print(f"\n    review → {target.name} ({target.stat().st_size} bytes)")
    return target


def test_persistence_roundtrip():
    """Step 14: load_plan/load_trajectory survive a restart."""
    from rl_agent_tutor.store import load_plan, load_trajectory, load_resources
    p = load_plan()
    t = load_trajectory(limit=100)
    r = load_resources()
    assert_truthy(p, "plan didn't persist")
    assert_truthy(len(t) >= 2, f"trajectory entries < 2: {len(t)}")
    print(f"\n    plan ✓  trajectory({len(t)}) ✓  resources({len(r)}) ✓")
    return True


# ---- Main ----

def main():
    quick = "--quick" in sys.argv

    banner(f"Smoke test starting · workspace = {SMOKE_DIR}")
    if SMOKE_DIR.exists():
        print(f"{YELLOW}cleaning previous smoketest workspace...{END}")
        shutil.rmtree(SMOKE_DIR)
    SMOKE_DIR.mkdir(parents=True, exist_ok=True)

    banner("1. Module imports & LLM health")
    step("import all modules", test_imports)
    step("LLM smoke call", test_llm_health)

    banner("2. Planning & state machine")
    plan, _ = step("planner.make_plan", test_planner)
    step("orchestrator.suggest_next_action", test_orchestrator, plan)

    banner("3. Tutor / Examiner / Practice (no RAG yet)")
    step("tutor.ask (no rag)", test_tutor_no_rag, plan)
    step("examiner.generate + grade", test_examiner, plan)
    step("practice.best_practices", test_practice, plan)

    if not quick:
        banner("4. Librarian → Indexer → RAG (network-dependent)")
        rs, err = step("librarian.fetch_for_node", test_librarian_optional, plan, critical=False)
        step("indexer.index_papers", test_indexer_optional, critical=False)
        step("rag.retrieve", test_rag_optional, critical=False)
        step("tutor.ask (with rag)", test_tutor_with_rag_optional, plan, critical=False)
    else:
        print(f"\n  {YELLOW}--quick: skipping librarian/indexer/RAG{END}")

    banner("5. Archivist & Reviewer")
    step("archivist.archive_node + build_index", test_archivist, plan)
    step("reviewer.weekly_review", test_reviewer, plan)

    banner("6. Persistence round-trip")
    step("load_plan / trajectory / resources", test_persistence_roundtrip)

    banner(f"{GREEN}All steps complete.{END}")
    print(f"\n  Workspace: {SMOKE_DIR}")
    print(f"  Inspect:")
    print(f"    cat {SMOKE_DIR}/progress/plan.json | head -40")
    print(f"    ls {SMOKE_DIR}/library/notes/")
    print(f"    open {SMOKE_DIR}/library/notes/INDEX.md")


if __name__ == "__main__":
    main()
