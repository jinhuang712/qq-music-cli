from __future__ import annotations

import json
import re

import pytest

from qq_music_cli import runs
from qq_music_cli.errors import UsageError
from qq_music_cli.runs import RunLog, list_runs, load_run, mark_undone

PL = {"dir_id": 301, "tid": 7001, "name": "Road Trip"}


def test_run_id_format_and_path(runs_path):
    run = RunLog("cmd", directory=runs_path)
    assert re.fullmatch(r"\d{8}T\d{6}-[0-9a-f]{6}", run.run_id)
    assert run.path == runs_path / f"{run.run_id}.json"
    assert not run.path.exists()  # nothing written until an op is recorded


def test_record_flushes_after_each_op(runs_path):
    run = RunLog("add x", directory=runs_path)
    run.record({"op": "add", "playlist": PL, "songs": [{"id": 1}]})
    on_disk = json.loads(run.path.read_text())
    assert len(on_disk["ops"]) == 1 and on_disk["command"] == "add x" and on_disk["run_id"] == run.run_id
    run.record({"op": "remove", "playlist": PL, "songs": [{"id": 1}]})
    assert [o["op"] for o in json.loads(run.path.read_text())["ops"]] == ["add", "remove"]
    assert run.has_ops is True
    assert not list(runs_path.glob("*.tmp"))


def test_dry_run_records_nothing(runs_path):
    run = RunLog("add x", directory=runs_path, dry_run=True)
    run.record({"op": "add", "playlist": PL, "songs": []})
    assert run.has_ops is False and run.data["ops"] == [] and list(runs_path.iterdir()) == []


def test_default_directory_uses_qqm_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("QQMUSIC_CLI_HOME", str(home))
    run = RunLog("x")
    run.record({"op": "create", "playlist": PL})
    assert run.path.parent == home / "runs" and run.path.exists()
    assert [r["run_id"] for r in list_runs()] == [run.run_id]


def write_run(directory, run_id, command, ops, created_at=1):
    (directory / f"{run_id}.json").write_text(
        json.dumps({"run_id": run_id, "created_at": created_at, "command": command, "ops": ops})
    )


def test_list_runs_newest_first_with_summaries(runs_path):
    write_run(runs_path, "20260101-000000-aaaaaa", "first", [{"op": "add", "playlist": PL, "songs": [{"id": 1}, {"id": 2}]}])
    write_run(runs_path, "20260102-000000-bbbbbb", "second", [{"op": "remove", "playlist": PL, "songs": [{"id": 1}]}, {"op": "delete", "playlist": PL, "songs": []}])
    write_run(runs_path, "20260103-000000-cccccc", "third", [{"op": "create", "playlist": PL}])
    out = list_runs(directory=runs_path)
    assert [r["command"] for r in out] == ["third", "second", "first"]
    assert out[2]["ops"] == ["add 2 song(s) to 'Road Trip'"]
    assert out[1]["ops"] == ["remove 1 song(s) from 'Road Trip'", "delete playlist 'Road Trip'"]
    assert out[0]["ops"] == ["create playlist 'Road Trip'"]
    assert out[0]["undone_by"] is None
    assert [r["command"] for r in list_runs(limit=2, directory=runs_path)] == ["third", "second"]


def test_list_runs_empty(runs_path):
    assert list_runs(directory=runs_path) == []


def test_load_run_and_missing(runs_path):
    run = RunLog("x", directory=runs_path)
    run.record({"op": "create", "playlist": PL})
    assert load_run(run.run_id, runs_path)["ops"][0]["op"] == "create"
    with pytest.raises(UsageError, match="no such run"):
        load_run("nope", runs_path)


def test_mark_undone(runs_path):
    run = RunLog("x", directory=runs_path)
    run.record({"op": "add", "playlist": PL, "songs": [{"id": 1}]})
    mark_undone(run.run_id, "undo-run-1", runs_path)
    data = load_run(run.run_id, runs_path)
    assert data["undone_by"] == "undo-run-1" and len(data["ops"]) == 1
    assert list_runs(directory=runs_path)[0]["undone_by"] == "undo-run-1"


def test_mark_undone_unknown_run_raises(runs_path):
    with pytest.raises(FileNotFoundError):
        mark_undone("missing", "u", runs_path)


def test_list_runs_orders_same_second_runs_by_creation(runs_path, monkeypatch):
    suffixes = iter([0xFFFFFF, 0x000000])
    frozen = runs.datetime(2026, 1, 1, 0, 0, 0)

    class FrozenClock:
        @staticmethod
        def now():
            return frozen

    monkeypatch.setattr(runs, "datetime", FrozenClock)
    monkeypatch.setattr(runs.secrets, "randbelow", lambda n: next(suffixes))
    first = RunLog("first", directory=runs_path)
    second = RunLog("second", directory=runs_path)
    first.record({"op": "create", "playlist": PL})
    second.record({"op": "create", "playlist": PL})
    assert [r["command"] for r in list_runs(directory=runs_path)] == ["second", "first"]
