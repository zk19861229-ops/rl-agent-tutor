"""CLI entrypoint — typer-based, rich-formatted."""
from __future__ import annotations
import functools
import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt

from . import config as _cfg
from .config import ensure_workspace
from .store import (
    save_plan, load_plan, append_trajectory, load_trajectory,
    load_resources, append_exercise, load_exercises,
)
from .models import TrajectoryEntry, ExerciseSession
from . import planner, librarian, tutor, examiner, practice, orchestrator, archivist, workspaces
from .llm import provider_info


app = typer.Typer(help="RL Agent Tutor — autonomous learning agent for RL/LLM post-training.", no_args_is_help=True)
console = Console()


def _safe_llm(fn):
    """Convert LLM/network/JSON failures into a clean CLI error.

    Without this, `chat_json` reaching its retry cap would surface as a raw
    Python traceback at the user — opaque and scary. With it: one red line +
    typer.Exit(1)."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except typer.Exit:
            raise
        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted.[/yellow]")
            raise typer.Exit(130)
        except Exception as e:
            kind = type(e).__name__
            msg = str(e) or "(no message)"
            console.print(f"[red]✗ {fn.__name__} failed:[/red] {kind}: {msg}")
            hint = _classify_hint(e)
            if hint:
                console.print(f"[dim]  hint: {hint}[/dim]")
            raise typer.Exit(1)
    return wrapper


def _classify_hint(e: Exception) -> str:
    name = type(e).__name__.lower()
    s = str(e).lower()
    if "api key" in s or "auth" in s or "401" in s or "403" in s:
        return "check ANTHROPIC_API_KEY / OPENROUTER_API_KEY in .env"
    if "timeout" in name or "timeout" in s:
        return "network slow or LLM endpoint unreachable; try again"
    if "rate" in s or "429" in s:
        return "rate limited — wait a minute or switch provider"
    if "json" in s and ("parse" in s or "decode" in s):
        return "LLM returned malformed JSON repeatedly; try a smaller request"
    if "connection" in name or "remote" in name:
        return "network blip; rerun the command"
    return ""


def _require_plan():
    p = load_plan()
    if not p:
        console.print("[red]No plan found.[/red] Run `rl-agent plan \"<your goal>\"` first.")
        raise typer.Exit(1)
    return p


def _require_current_node():
    p = _require_plan()
    if not p.current_node_id:
        console.print("[red]No current node set.[/red]")
        raise typer.Exit(1)
    n = p.find_node(p.current_node_id)
    if not n:
        console.print(f"[red]Current node {p.current_node_id} not found in plan.[/red]")
        raise typer.Exit(1)
    s = p.stage_of(n.id)
    return p, n, s


@app.command()
@_safe_llm
def plan(
    goal: str = typer.Argument(..., help="Your learning goal, e.g. '掌握 PPO 并能用 TRL 跑通 RLHF'"),
    level: str = typer.Option("", "--level", "-l", help="Your current level"),
):
    """Generate a structured learning plan for a goal."""
    ensure_workspace()
    if load_plan():
        if not typer.confirm("⚠️ A plan already exists. Replace it?", default=False):
            raise typer.Exit()
    console.print(f"[cyan]Planning for:[/cyan] {goal}")
    with console.status("[bold]Calling planner agent...[/bold]"):
        new_plan = planner.make_plan(goal, level)
    save_plan(new_plan)
    append_trajectory(TrajectoryEntry(kind="plan", content=f"Goal: {goal}", meta={"level": level}))
    _print_plan(new_plan)
    console.print(f"\n[green]✔ Plan saved to {_cfg.WORKSPACE_DIR}/progress/plan.json[/green]")
    console.print(orchestrator.suggest_next_action(new_plan))


def _print_plan(p):
    table = Table(title=f"Plan: {p.goal}", show_lines=False, header_style="bold cyan")
    table.add_column("Node", width=8)
    table.add_column("Name")
    table.add_column("Hours", width=10)
    table.add_column("Status", width=12)
    for s in p.stages:
        table.add_row(f"[bold]Stage {s.id}[/bold]", f"[bold]{s.name}[/bold]", "", "")
        for n in s.nodes:
            mark = "→ " if n.id == p.current_node_id else "  "
            status_color = {"completed": "green", "in_progress": "yellow", "self_testing": "magenta", "pending": "dim"}.get(n.status, "white")
            table.add_row(
                mark + n.id,
                n.name,
                f"{n.estimated_hours[0]:.0f}–{n.estimated_hours[1]:.0f}h",
                f"[{status_color}]{n.status}[/{status_color}]",
            )
    console.print(table)


@app.command()
def status():
    """Show current plan, current node, and suggested next action."""
    p = _require_plan()
    _print_plan(p)
    console.print(Panel(orchestrator.suggest_next_action(p), title="Next action", border_style="cyan"))
    # quick stats
    total = len(p.all_nodes())
    done = sum(1 for n in p.all_nodes() if n.status == "completed")
    console.print(f"\nProgress: [bold]{done}/{total}[/bold] nodes completed ({done/total*100:.0f}%)")
    console.print(f"[dim]LLM: {provider_info()}[/dim]")


@app.command()
@_safe_llm
def fetch():
    """Fetch papers, code, and resource pointers for the current node."""
    p, n, s = _require_current_node()
    console.print(f"[cyan]Fetching resources for[/cyan] {n.id} {n.name}")
    with console.status("[bold]Querying librarian agent + arxiv + GitHub...[/bold]"):
        resources = librarian.fetch_for_node(n)
    if not resources:
        console.print("[yellow]No resources returned.[/yellow]")
        return
    table = Table(title=f"Resources for {n.id}", show_lines=False)
    table.add_column("Kind", width=8)
    table.add_column("Title")
    table.add_column("Local", width=40)
    for r in resources:
        local = r.local_path or "—"
        if len(local) > 38:
            local = "…" + local[-37:]
        table.add_row(r.kind, r.title[:60], local)
    console.print(table)
    append_trajectory(TrajectoryEntry(node_id=n.id, kind="fetch", content=f"fetched {len(resources)} resources"))


@app.command()
def resources(
    node_id: str = typer.Argument(None, help="Node id (default: current)"),
):
    """List resources fetched so far for a node."""
    p = _require_plan()
    nid = node_id or p.current_node_id
    rs = load_resources(node_id=nid)
    if not rs:
        console.print(f"[yellow]No resources for {nid}. Run `rl-agent fetch` first.[/yellow]")
        return
    for r in rs:
        console.print(f"[bold]{r.kind}[/bold] · {r.title}")
        if r.local_path:
            console.print(f"  📁 {r.local_path}")
        if r.url:
            console.print(f"  🔗 {r.url}")
        if r.summary:
            console.print(f"  [dim]{r.summary[:200]}[/dim]")
        console.print()


@app.command()
@_safe_llm
def ask(question: str = typer.Argument(..., help="Your question")):
    """Ask the tutor about the current node (RAG-enabled)."""
    p, n, s = _require_current_node()
    append_trajectory(TrajectoryEntry(node_id=n.id, kind="ask", content=question))
    with console.status("[bold]Tutor thinking (retrieving from local library)...[/bold]"):
        ans, citations = tutor.ask(n, s.name if s else "", question)
    append_trajectory(TrajectoryEntry(node_id=n.id, kind="answer", content=ans,
                                      meta={"citations": citations}))
    console.print(Panel(Markdown(ans), title=f"Tutor · node {n.id}", border_style="cyan"))
    if citations:
        console.print("\n[dim]Sources used:[/dim]")
        for c in citations:
            console.print(f"  [cyan][{c['doc_id']} · §{c['section']} · p.{c['page']}][/cyan]")


@app.command()
@_safe_llm
def practices():
    """Show industry best practices for the current node's topic."""
    p, n, s = _require_current_node()
    with console.status("[bold]Fetching industry insights...[/bold]"):
        text = practice.best_practices(n)
    console.print(Panel(Markdown(text), title=f"Best practices · {n.name}", border_style="green"))
    append_trajectory(TrajectoryEntry(node_id=n.id, kind="study", content=f"viewed practices: {n.name}"))


@app.command()
@_safe_llm
def test():
    """Generate a 5-question quiz for the current node, grade interactively."""
    p, n, s = _require_current_node()
    console.print(f"[cyan]Generating self-test for[/cyan] {n.id} {n.name}")
    with console.status("[bold]Examiner generating questions...[/bold]"):
        questions = examiner.generate_exercises(n)
    if not questions:
        console.print("[red]Failed to generate questions.[/red]")
        return

    session = ExerciseSession(node_id=n.id, questions=questions)
    p.state = "self_testing"
    save_plan(p)

    for i, q in enumerate(questions, 1):
        console.print(Panel(
            f"[bold]Q{i}[/bold] ({q.type})\n\n{q.question}",
            border_style="magenta",
        ))
        ans = Prompt.ask("[bold]Your answer[/bold] (multi-line: end with blank line)", default="")
        # allow multi-line: keep reading until blank
        if ans:
            extra = []
            while True:
                line = Prompt.ask("[dim]...[/dim]", default="")
                if not line:
                    break
                extra.append(line)
            if extra:
                ans = ans + "\n" + "\n".join(extra)
        with console.status("[bold]Grading...[/bold]"):
            attempt = examiner.grade_answer(q, ans)
        session.attempts.append(attempt)
        color = "green" if attempt.score >= 0.8 else "yellow" if attempt.score >= 0.6 else "red"
        console.print(Panel(
            f"[{color}]Score: {attempt.score:.2f}[/{color}]\n\n{attempt.feedback}",
            title="Feedback", border_style=color,
        ))

    avg, summary = examiner.summarize_session(session.attempts)
    session.overall_score = avg
    from datetime import datetime
    session.finished_at = datetime.now().isoformat()
    append_exercise(session)
    append_trajectory(TrajectoryEntry(node_id=n.id, kind="test", content=summary, meta={"score": avg}))
    console.print(Panel(summary, title=f"Session result · {n.id}", border_style="cyan"))

    if avg >= 0.8:
        console.print("[green]→ Strong score. You may run `rl-agent advance` to mark this node complete and move on.[/green]")
        p.state = "advancing"
    else:
        console.print("[yellow]→ Recommend more study + re-test. Use `rl-agent ask` to revisit weak points.[/yellow]")
        p.state = "studying"
    save_plan(p)


@app.command()
def advance():
    """Mark current node complete and move to the next pending node."""
    p, n, s = _require_current_node()
    if not typer.confirm(f"Mark node {n.id} ({n.name}) as completed?", default=True):
        raise typer.Exit()
    orchestrator.mark_node_completed(p, n.id)
    new_id = orchestrator.advance_to_next(p)
    append_trajectory(TrajectoryEntry(node_id=n.id, kind="advance", content=f"completed; next={new_id}"))
    if new_id:
        nxt = p.find_node(new_id)
        console.print(f"[green]✔ {n.id} completed.[/green] [cyan]→ Next: {nxt.id} {nxt.name}[/cyan]")
    else:
        console.print("[green]🎉 All nodes complete! Run `rl-agent review` for a final retrospective.[/green]")


@app.command()
def trajectory(
    node_id: str = typer.Argument(None, help="Filter by node id (optional)"),
    limit: int = typer.Option(20, "--limit", "-n"),
):
    """Show recent learning trajectory."""
    entries = load_trajectory(node_id=node_id, limit=limit)
    if not entries:
        console.print("[yellow]No trajectory entries yet.[/yellow]")
        return
    for e in entries:
        ts = e.ts[:19].replace("T", " ")
        nid = e.node_id or "—"
        console.print(f"[dim]{ts}[/dim] [cyan]{e.kind:8}[/cyan] [magenta]{nid:6}[/magenta] {e.content[:120]}")


@app.command()
def goto(node_id: str = typer.Argument(..., help="Node id to switch to, e.g. 1.2")):
    """Jump current focus to a different node (skip / go back)."""
    p = _require_plan()
    n = p.find_node(node_id)
    if not n:
        console.print(f"[red]Node {node_id} not found.[/red]")
        raise typer.Exit(1)
    p.current_node_id = n.id
    if n.status == "pending":
        n.status = "in_progress"
    p.state = "studying"
    save_plan(p)
    console.print(f"[green]✔ Switched to {n.id} {n.name}[/green]")


@app.command()
@_safe_llm
def archive(
    node_id: str = typer.Argument(None, help="Node id to archive (default: current)"),
    all_completed: bool = typer.Option(False, "--all-completed", help="Archive every completed node"),
    all_active: bool = typer.Option(False, "--all-active", help="Archive every node with any activity"),
):
    """Distill a node's trajectory + exercises + resources into a Markdown KB entry."""
    p = _require_plan()
    targets: list = []
    if all_completed:
        targets = archivist.archive_all(p, only_completed=True)
    elif all_active:
        targets = archivist.archive_all(p, only_completed=False)
    else:
        nid = node_id or p.current_node_id
        n = p.find_node(nid) if nid else None
        if not n:
            console.print(f"[red]Node {nid} not found.[/red]")
            raise typer.Exit(1)
        s = p.stage_of(n.id)
        with console.status(f"[bold]Archivist curating {n.id}...[/bold]"):
            target = archivist.archive_node(n, stage_name=s.name if s else "")
        targets = [target]
    # always rebuild the index
    idx = archivist.build_index(p)
    targets.append(idx)
    append_trajectory(TrajectoryEntry(
        node_id=node_id, kind="review",
        content=f"archived {len(targets)} files",
    ))
    console.print(f"[green]✔ Wrote {len(targets)} files:[/green]")
    for t in targets:
        console.print(f"  📝 {t}")
    console.print(f"[dim]→ Open {idx} for the index.[/dim]")


@app.command()
def kb(
    node_id: str = typer.Argument(None, help="Node id (default: current)"),
):
    """Print the knowledge-base entry for a node, or the index if no node given."""
    p = _require_plan()
    from .config import workspace_path
    from .archivist import _slugify
    notes_dir = workspace_path("library", "notes")
    if node_id is None:
        idx = notes_dir / "INDEX.md"
        if not idx.exists():
            console.print("[yellow]No KB index yet. Run `rl-agent archive` first.[/yellow]")
            return
        console.print(Markdown(idx.read_text(encoding="utf-8")))
        return
    n = p.find_node(node_id)
    if not n:
        console.print(f"[red]Node {node_id} not found.[/red]")
        raise typer.Exit(1)
    target = notes_dir / f"{n.id}_{_slugify(n.name)}.md"
    if not target.exists():
        console.print(f"[yellow]No KB entry for {node_id}. Run `rl-agent archive {node_id}` first.[/yellow]")
        return
    console.print(Markdown(target.read_text(encoding="utf-8")))


@app.command("fetch-blog")
@_safe_llm
def fetch_blog_cmd(url: str = typer.Argument(..., help="Blog/article URL")):
    """Fetch and store a single blog post into the current node's library."""
    p, n, s = _require_current_node()
    from .config import workspace_path
    blogs_dir = workspace_path("library", "notes", "blogs")
    with console.status(f"[bold]Fetching {url}...[/bold]"):
        r = librarian.fetch_blog_resource(url, why="", node_id=n.id, blogs_dir=blogs_dir)
    if r is None:
        console.print("[red]Failed.[/red]"); return
    from .store import append_resource
    append_resource(r)
    console.print(f"[green]✔ {r.title}[/green]")
    if r.local_path:
        console.print(f"  📁 {r.local_path}")
    if r.summary:
        console.print(f"  [dim]{r.summary[:200]}[/dim]")


@app.command("fetch-youtube")
@_safe_llm
def fetch_youtube_cmd(
    url_or_id: str = typer.Argument(..., help="YouTube URL or 11-char video ID"),
    title: str = typer.Option("", "--title", "-t"),
):
    """Fetch a YouTube transcript into the current node's library."""
    p, n, s = _require_current_node()
    from .config import workspace_path
    transcripts_dir = workspace_path("library", "notes", "transcripts")
    with console.status(f"[bold]Fetching transcript for {url_or_id}...[/bold]"):
        r = librarian.fetch_youtube_resource(url_or_id, title=title, why="",
                                             node_id=n.id, transcripts_dir=transcripts_dir)
    if r is None:
        console.print("[red]Failed.[/red]"); return
    from .store import append_resource
    append_resource(r)
    console.print(f"[green]✔ {r.title}[/green]")
    if r.local_path:
        console.print(f"  📁 {r.local_path}")
    if r.summary:
        console.print(f"  [dim]{r.summary[:200]}[/dim]")


@app.command("review-weekly")
@_safe_llm
def review_weekly_cmd():
    """Generate a weekly retrospective (last 7 days)."""
    from . import reviewer
    p = _require_plan()
    with console.status("[bold]Reviewer reflecting on your week...[/bold]"):
        target = reviewer.weekly_review(p)
    console.print(f"[green]✔ Weekly review → {target}[/green]")
    console.print(Markdown(target.read_text(encoding="utf-8")))


@app.command("review-stage")
@_safe_llm
def review_stage_cmd(stage_id: int = typer.Argument(..., help="Stage id, e.g. 0")):
    """Generate a stage retrospective."""
    from . import reviewer
    p = _require_plan()
    with console.status(f"[bold]Reviewer reflecting on stage {stage_id}...[/bold]"):
        target = reviewer.stage_review(p, stage_id)
    console.print(f"[green]✔ Stage review → {target}[/green]")
    console.print(Markdown(target.read_text(encoding="utf-8")))


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8765, "--port", "-p"),
):
    """Launch the local web UI on http://127.0.0.1:8765."""
    import uvicorn
    console.print(f"[cyan]→ Open http://{host}:{port} in your browser[/cyan]")
    uvicorn.run("rl_agent_tutor.server:app", host=host, port=port, reload=False)


# ---------- workspace ----------

workspace_app = typer.Typer(help="Manage learning workspaces (archive & switch).")
app.add_typer(workspace_app, name="workspace")


@workspace_app.command("list")
def ws_list_cmd():
    """List all workspaces, mark the active one."""
    items = workspaces.list_workspaces()
    if not items:
        console.print("[yellow]No workspaces yet.[/yellow] Create one with `rl-agent workspace create <name>`.")
        return
    table = Table(show_lines=False, header_style="bold cyan")
    table.add_column("", width=2)
    table.add_column("Name", width=18)
    table.add_column("Goal", width=44)
    table.add_column("Progress", width=10)
    table.add_column("Last", width=12)
    for w in items:
        marker = "[green]●[/green]" if w.active else " "
        prog = f"{w.progress[0]}/{w.progress[1]}" if w.progress[1] else "—"
        table.add_row(marker, w.name, w.goal or "[dim](no plan)[/dim]", prog, w.last_activity or "—")
    console.print(table)
    console.print(f"\n[dim]Active workspace: {(workspaces.get_active() or '(none)').name if workspaces.get_active() else '(none)'}[/dim]")


@workspace_app.command("create")
def ws_create_cmd(
    name: str = typer.Argument(..., help="Workspace name (lowercase, _/-, ≤40 chars)"),
    no_switch: bool = typer.Option(False, "--no-switch", help="Don't make it active"),
):
    """Create a new empty workspace."""
    w = workspaces.create(name, switch=not no_switch)
    if not no_switch:
        console.print(f"[green]✔ Created and switched to[/green] {w.name}")
    else:
        console.print(f"[green]✔ Created[/green] {w.name} (not active)")


@workspace_app.command("switch")
def ws_switch_cmd(name: str = typer.Argument(..., help="Workspace name to activate")):
    """Switch the active workspace. Restart `serve` for the change to take effect there."""
    w = workspaces.switch_to(name)
    console.print(f"[green]✔ Active workspace →[/green] {w.name}")
    console.print("[dim]Note: a running `rl-agent serve` keeps its old workspace until restarted.[/dim]")


@workspace_app.command("current")
def ws_current_cmd():
    """Show the currently active workspace."""
    w = workspaces.get_active()
    if not w:
        console.print("[yellow]No active workspace.[/yellow]")
        return
    console.print(f"[bold]{w.name}[/bold]  →  {w.path}")
    if w.has_plan:
        console.print(f"  goal:     {w.goal}")
        console.print(f"  progress: {w.progress[0]}/{w.progress[1]}")
        console.print(f"  last:     {w.last_activity or '—'}")


@workspace_app.command("rename")
def ws_rename_cmd(old: str = typer.Argument(...), new: str = typer.Argument(...)):
    """Rename a workspace."""
    w = workspaces.rename(old, new)
    console.print(f"[green]✔ Renamed[/green] {old} → {w.name}")


@workspace_app.command("delete")
def ws_delete_cmd(
    name: str = typer.Argument(...),
    force: bool = typer.Option(False, "--force", help="Delete even if active"),
):
    """Delete a workspace permanently (irreversible)."""
    if not typer.confirm(f"Permanently delete workspace {name!r}? This cannot be undone.", default=False):
        raise typer.Exit()
    workspaces.delete(name, force=force)
    console.print(f"[green]✔ Deleted[/green] {name}")


@app.command()
def daemon(
    idle_days: int = typer.Option(3, "--idle-days",
                                  help="Send a nudge if no activity for N days"),
):
    """Run the scheduled-jobs daemon (weekly review / idle nudge / monday focus)."""
    from . import scheduler as sched_mod
    sched_mod.run_daemon(idle_days=idle_days)


@app.command("index")
@_safe_llm
def index_cmd():
    """(Re)index every PDF under workspace/library/papers/ for RAG."""
    from . import indexer
    def progress(name): console.print(f"  · indexing {name}")
    with console.status("[bold]Indexer parsing PDFs...[/bold]"):
        n_pdfs, n_chunks = indexer.index_papers(progress=progress)
    console.print(f"[green]✔ Indexed {n_pdfs} PDFs → {n_chunks} chunks[/green]")
    stats = indexer.index_stats()
    if stats["documents"]:
        console.print("\n[dim]Documents:[/dim]")
        for d in stats["documents"][:30]:
            console.print(f"  · {d}")


@app.command("query")
@_safe_llm
def query_cmd(
    q: str = typer.Argument(..., help="Search query"),
    n: int = typer.Option(5, "--top", help="Top N results"),
    no_rerank: bool = typer.Option(False, "--no-rerank", help="Skip LLM rerank"),
):
    """Search the local PDF index. Useful to verify retrieval quality."""
    from . import rag
    with console.status("[bold]Searching local library...[/bold]"):
        hits = rag.retrieve(q, top_n=n, rerank=not no_rerank)
    if not hits:
        console.print("[yellow]No matches. Did you `rl-agent index` first?[/yellow]"); return
    for h in hits:
        c = h.chunk
        console.print(f"\n[cyan][{c.doc_id} · §{c.section} · p.{c.page}][/cyan] [dim](score {h.score:.2f})[/dim]")
        console.print(f"[bold]{c.title}[/bold]")
        preview = c.text[:500].replace("\n", " ")
        console.print(f"  {preview}...")


if __name__ == "__main__":
    app()
