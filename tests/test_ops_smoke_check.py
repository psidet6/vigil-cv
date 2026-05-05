from __future__ import annotations


def test_synthetic_task_queue_smoke_uses_isolated_db(tmp_path):
    from ops import smoke_check

    db_path = tmp_path / "queue.sqlite3"
    result = smoke_check.check_synthetic_task_queue(db_path)

    assert result.ok is True
    assert db_path.exists()


def test_smoke_check_queue_only_main_returns_success(tmp_path, capsys):
    from ops import smoke_check

    code = smoke_check.main(["--queue-only", "--queue-db", str(tmp_path / "queue.sqlite3")])
    output = capsys.readouterr().out

    assert code == 0
    assert "[OK] synthetic task queue" in output
