"""Tests for hierarchy-aware task rendering across web and HTML report.

Covers: children follow parent section, deeply nested tasks, orphan children
(done parent), cycle protection, root-only counting in section headers.
"""

from __future__ import annotations

from datetime import datetime

from kanademinder.app.daemon.html_report import build_html_report
from kanademinder.models import Task, TaskStatus


NOW = datetime(2026, 3, 9, 14, 0)


def _overdue(**kw) -> Task:
    return Task(deadline=datetime(2026, 3, 8, 23, 59), **kw)


def _due_today(**kw) -> Task:
    return Task(deadline=datetime(2026, 3, 9, 23, 59), **kw)


def _upcoming(**kw) -> Task:
    return Task(deadline=datetime(2026, 3, 15, 9, 0), **kw)


# ── Children follow parent section ────────────────────────────────────────────


def test_child_without_deadline_appears_under_overdue_parent():
    """Child tasks with no deadline should render under their parent's section,
    not in the No Deadline section."""
    parent = _overdue(id=1, name="Write article")
    child1 = Task(id=2, name="Summarize text", parent_id=1)
    child2 = Task(id=3, name="Summarize images", parent_id=1)

    html = build_html_report([parent, child1, child2], "Focus.", NOW)

    # Children should appear in the OVERDUE section (after the parent)
    assert "OVERDUE" in html
    assert "Write article" in html
    assert "Summarize text" in html
    assert "Summarize images" in html
    # No Deadline section should NOT appear (no root tasks without deadlines)
    assert "NO DEADLINE" not in html


def test_child_without_deadline_not_in_no_deadline_section():
    """When a child's parent is in Overdue, the child must not also appear
    in No Deadline as a separate entry."""
    parent = _overdue(id=1, name="Parent task")
    child = Task(id=2, name="Child task", parent_id=1)
    standalone = Task(id=3, name="Standalone no deadline")

    html = build_html_report([parent, child, standalone], "Go.", NOW)

    assert "NO DEADLINE (1)" in html
    assert "Standalone no deadline" in html
    # Verify child is in OVERDUE, not in NO DEADLINE
    overdue_pos = html.index("OVERDUE")
    no_dl_pos = html.index("NO DEADLINE")
    child_pos = html.index("Child task")
    assert overdue_pos < child_pos < no_dl_pos


def test_child_with_own_deadline_follows_parent_section():
    """A child with a due-today deadline should render under its parent's
    overdue section, not in a separate Due Today section."""
    parent = _overdue(id=1, name="Parent")
    child = _due_today(id=2, name="Child with deadline", parent_id=1)

    html = build_html_report([parent, child], "Do it.", NOW)

    assert "OVERDUE" in html
    assert "DUE TODAY" not in html
    assert "Child with deadline" in html


def test_section_count_reflects_root_tasks_only():
    """Section header count should count root tasks only, not children."""
    parents = [
        _overdue(id=1, name="Overdue A"),
        _overdue(id=2, name="Overdue B"),
    ]
    children = [
        Task(id=3, name="Child 1", parent_id=1),
        Task(id=4, name="Child 2", parent_id=1),
        Task(id=5, name="Child 3", parent_id=2),
    ]

    html = build_html_report(parents + children, "Go.", NOW)

    # 2 root overdue tasks, 3 children rendered underneath
    assert "OVERDUE (2)" in html
    assert "NO DEADLINE" not in html


# ── Deep nesting ──────────────────────────────────────────────────────────────


def test_deeply_nested_tasks_all_follow_root():
    """Grandchildren and deeper should all render under the root's section."""
    root = _overdue(id=1, name="Root")
    child = Task(id=2, name="Child", parent_id=1)
    grandchild = Task(id=3, name="Grandchild", parent_id=2)

    html = build_html_report([root, child, grandchild], "Go.", NOW)

    assert "OVERDUE (1)" in html
    assert "Root" in html
    assert "Child" in html
    assert "Grandchild" in html
    assert "NO DEADLINE" not in html


def test_child_indentation_increases_with_depth():
    """Each nesting level should have increasing indentation."""
    root = Task(id=1, name="Root")
    child = Task(id=2, name="Child", parent_id=1)
    grandchild = Task(id=3, name="Grandchild", parent_id=2)

    html = build_html_report([root, child, grandchild], "Go.", NOW)

    assert "padding-left:18px" in html
    assert "padding-left:36px" in html


# ── Orphan children (done parent) ────────────────────────────────────────────


def test_orphan_child_promoted_to_root_when_parent_not_in_list():
    """When parent_id points to a task not in the list (e.g. done parent
    filtered out), child should appear as a root in its own section."""
    # parent_id=99 doesn't exist in the list
    orphan = _due_today(id=1, name="Orphan child", parent_id=99)

    html = build_html_report([orphan], "Go.", NOW)

    assert "DUE TODAY (1)" in html
    assert "Orphan child" in html


def test_orphan_child_no_deadline_promoted_to_root():
    """Orphan child with no deadline should appear in No Deadline as root."""
    orphan = Task(id=1, name="Orphan no dl", parent_id=99)

    html = build_html_report([orphan], "Go.", NOW)

    assert "NO DEADLINE (1)" in html
    assert "Orphan no dl" in html


# ── Cycle protection ─────────────────────────────────────────────────────────


def test_cycle_does_not_cause_infinite_recursion():
    """Two tasks pointing to each other should not crash."""
    a = Task(id=1, name="Task A", parent_id=2)
    b = Task(id=2, name="Task B", parent_id=1)

    # Should complete without RecursionError
    html = build_html_report([a, b], "Go.", NOW)

    assert "Task A" in html
    assert "Task B" in html


def test_self_referencing_task_does_not_crash():
    """A task whose parent_id points to itself should render normally."""
    t = Task(id=1, name="Self ref", parent_id=1)

    html = build_html_report([t], "Go.", NOW)

    assert "Self ref" in html


def test_three_way_cycle_renders_all_tasks():
    """A cycle of 3 tasks should still render all of them."""
    a = Task(id=1, name="Cycle A", parent_id=3)
    b = Task(id=2, name="Cycle B", parent_id=1)
    c = Task(id=3, name="Cycle C", parent_id=2)

    html = build_html_report([a, b, c], "Go.", NOW)

    assert "Cycle A" in html
    assert "Cycle B" in html
    assert "Cycle C" in html


# ── Mixed sections with hierarchy ────────────────────────────────────────────


def test_multiple_sections_with_children():
    """Multiple sections each with their own children should render correctly."""
    overdue_parent = _overdue(id=1, name="Overdue parent")
    overdue_child = Task(id=2, name="Overdue child", parent_id=1)
    today_parent = _due_today(id=3, name="Today parent")
    today_child = Task(id=4, name="Today child", parent_id=3)
    standalone = Task(id=5, name="Standalone")

    tasks = [overdue_parent, overdue_child, today_parent, today_child, standalone]
    html = build_html_report(tasks, "Go.", NOW)

    assert "OVERDUE (1)" in html
    assert "DUE TODAY (1)" in html
    assert "NO DEADLINE (1)" in html
    # Children should be in their parent's section
    overdue_pos = html.index("OVERDUE")
    today_pos = html.index("DUE TODAY")
    no_dl_pos = html.index("NO DEADLINE")
    assert overdue_pos < html.index("Overdue child") < today_pos
    assert today_pos < html.index("Today child") < no_dl_pos


# ── Empty and single task ────────────────────────────────────────────────────


def test_empty_task_list():
    """No tasks should produce no section headers."""
    html = build_html_report([], "Nothing.", NOW)

    assert "OVERDUE" not in html
    assert "DUE TODAY" not in html
    assert "UPCOMING" not in html
    assert "NO DEADLINE" not in html


def test_single_root_task_no_children():
    """A single task without children should render normally."""
    html = build_html_report([Task(id=1, name="Solo")], "Go.", NOW)

    assert "NO DEADLINE (1)" in html
    assert "Solo" in html


# ── Child background styling ─────────────────────────────────────────────────


def test_child_rows_have_background_styling():
    """Child task rows in HTML report should have the subtle background."""
    parent = Task(id=1, name="Parent")
    child = Task(id=2, name="Child", parent_id=1)

    html = build_html_report([parent, child], "Go.", NOW)

    assert 'background:#fafafa' in html
