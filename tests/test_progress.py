"""Resumability — an interrupted run must never lose or duplicate work (KE-004)."""

from pathlib import Path

from igarchive.progress import Progress


def test_commit_then_resume(tmp_path: Path) -> None:
    p1 = Progress(tmp_path)
    assert not p1.post_done("AAA")
    p1.mark_post("AAA")
    p1.mark_highlight("H1")

    # Simulate a relaunch: fresh instance reads the same file.
    p2 = Progress(tmp_path)
    assert p2.post_done("AAA")
    assert p2.highlight_done("H1")
    assert not p2.post_done("BBB")
    assert p2.completed_posts == {"AAA"}


def test_write_is_atomic_no_tmp_left_behind(tmp_path: Path) -> None:
    p = Progress(tmp_path)
    p.mark_post("AAA")
    assert (tmp_path / "progress.json").exists()
    assert not (tmp_path / "progress.json.tmp").exists()
