"""Scheduler daemon — proactive nudges and weekly reviews.

Default jobs:
- Every Sunday 18:00 local time: generate weekly_review.md
- Every day 09:00: if last activity > N days ago, write a nudge to library/notes/nudges/
- Every Monday 08:00: surface "next focus" — pick the current node's KB excerpt

These are local-only. The daemon writes Markdown files (and optionally OS notifications
on macOS via osascript / Linux via notify-send if available).

Run: rl-agent daemon [--idle-days 3]
"""
from __future__ import annotations
import shutil
import subprocess
import platform
from datetime import datetime, timedelta
from pathlib import Path
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import workspace_path, ensure_workspace
from .store import load_plan, load_trajectory
from . import reviewer, archivist


def _notify(title: str, message: str) -> None:
    """Best-effort OS notification. Silent fallback on unsupported platforms."""
    try:
        sys = platform.system()
        if sys == "Darwin" and shutil.which("osascript"):
            esc_t = title.replace('"', '\\"')
            esc_m = message.replace('"', '\\"')
            subprocess.run(
                ["osascript", "-e", f'display notification "{esc_m}" with title "{esc_t}"'],
                check=False, timeout=5,
            )
        elif sys == "Linux" and shutil.which("notify-send"):
            subprocess.run(["notify-send", title, message], check=False, timeout=5)
    except Exception:
        pass


def _last_activity_days() -> int | None:
    entries = load_trajectory(limit=10)
    if not entries:
        return None
    last = max(e.ts for e in entries)
    last_dt = datetime.fromisoformat(last)
    return (datetime.now() - last_dt).days


def job_weekly_review() -> None:
    plan = load_plan()
    if not plan:
        return
    try:
        target = reviewer.weekly_review(plan)
        _notify("RL Agent · Weekly review ready", str(target.name))
        print(f"[scheduler] weekly review → {target}")
    except Exception as e:
        print(f"[scheduler] weekly_review failed: {e}")


def job_idle_nudge(idle_days: int) -> None:
    plan = load_plan()
    if not plan:
        return
    days = _last_activity_days()
    if days is None or days < idle_days:
        return
    nudges_dir = workspace_path("library", "notes", "nudges")
    nudges_dir.mkdir(parents=True, exist_ok=True)
    cur = plan.find_node(plan.current_node_id) if plan.current_node_id else None
    msg = (
        f"# Nudge — {datetime.now().date().isoformat()}\n\n"
        f"It's been **{days} days** since your last activity.\n\n"
        f"Current focus: **{cur.id} {cur.name}**" if cur else "No current node set.\n"
    )
    target = nudges_dir / f"nudge_{datetime.now().date().isoformat()}.md"
    target.write_text(msg, encoding="utf-8")
    _notify("RL Agent · Time to study?", f"{days} days since last activity")
    print(f"[scheduler] nudge written → {target}")


def job_monday_focus() -> None:
    plan = load_plan()
    if not plan or not plan.current_node_id:
        return
    cur = plan.find_node(plan.current_node_id)
    s = plan.stage_of(cur.id)
    try:
        archivist.archive_node(cur, stage_name=s.name if s else "")
        archivist.build_index(plan)
        _notify("RL Agent · Monday focus", f"This week: {cur.id} {cur.name}")
        print(f"[scheduler] monday focus refreshed for {cur.id}")
    except Exception as e:
        print(f"[scheduler] monday_focus failed: {e}")


def run_daemon(idle_days: int = 3) -> None:
    ensure_workspace()
    sched = BlockingScheduler(timezone="local")
    # Sunday 18:00 — weekly review
    sched.add_job(job_weekly_review, CronTrigger(day_of_week="sun", hour=18, minute=0),
                  id="weekly_review")
    # Every day 09:00 — idle nudge
    sched.add_job(lambda: job_idle_nudge(idle_days),
                  CronTrigger(hour=9, minute=0), id="idle_nudge")
    # Monday 08:00 — focus reminder
    sched.add_job(job_monday_focus, CronTrigger(day_of_week="mon", hour=8, minute=0),
                  id="monday_focus")

    print("[scheduler] daemon started.")
    print("  · weekly_review  → Sun 18:00")
    print("  · idle_nudge     → daily 09:00 (if idle > %d days)" % idle_days)
    print("  · monday_focus   → Mon 08:00")
    print("  Ctrl+C to stop.")
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        print("\n[scheduler] stopped.")
