from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from qq_music_cli import cli
from qq_music_cli.cli import app
from qq_music_cli.errors import AuthError, UsageError
from qq_music_cli.auth import CredentialStore

IDS = list(range(100_000, 102_000))


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def patched_lib(monkeypatch, lib):
    monkeypatch.setattr(cli, "_library", lambda required=True: lib)
    return lib


def out_json(result):
    return json.loads(result.stdout)


def test_status_offline_logged_out(runner, tmp_path, monkeypatch):
    path = tmp_path / "none.json"
    monkeypatch.setenv("QQMUSIC_CLI_CREDENTIAL_FILE", str(path))
    result = runner.invoke(app, ["status", "--offline"])
    assert result.exit_code == 0
    data = out_json(result)
    assert data["logged_in"] is False and data["store"] == f"file:{path}"


def test_status_offline_logged_in_hides_secrets(runner, tmp_path, monkeypatch, cred):
    path = tmp_path / "c.json"
    CredentialStore(path=path).save(cred)
    monkeypatch.setenv("QQMUSIC_CLI_CREDENTIAL_FILE", str(path))
    result = runner.invoke(app, ["status", "--offline"])
    assert result.exit_code == 0
    data = out_json(result)
    assert data["logged_in"] is True and data["uin"] == cred.uin and data["login_type"] == "wechat"
    assert cred.musickey not in result.stdout


def test_delete_without_yes_is_usage_error(runner):
    result = runner.invoke(app, ["delete", "X"])
    assert result.exit_code != 0
    assert isinstance(result.exception, UsageError)
    assert "--yes" in result.exception.message


def test_delete_without_yes_never_touches_server(runner, patched_lib, server):
    runner.invoke(app, ["delete", "Anything"])
    assert server.calls == []


def test_main_maps_errors_to_exit_codes(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["qqmusic", "delete", "X"])
    with pytest.raises(SystemExit) as e:
        cli.main()
    assert e.value.code == 2
    assert json.loads(capsys.readouterr().err)["error"]["kind"] == "usage"


def test_commands_requiring_login_raise_auth_error(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("QQMUSIC_CLI_CREDENTIAL_FILE", str(tmp_path / "missing.json"))
    result = runner.invoke(app, ["playlists"])
    assert isinstance(result.exception, AuthError) and result.exception.exit_code == 3


def test_logout(runner, tmp_path, monkeypatch, cred):
    path = tmp_path / "c.json"
    CredentialStore(path=path).save(cred)
    monkeypatch.setenv("QQMUSIC_CLI_CREDENTIAL_FILE", str(path))
    assert out_json(runner.invoke(app, ["logout"]))["logged_out"] is True
    assert not path.exists()
    assert out_json(runner.invoke(app, ["logout"]))["logged_out"] is False


def test_version(runner):
    assert "version" in out_json(runner.invoke(app, ["--version"]))


def test_playlists_and_show(runner, patched_lib, server):
    server.add_playlist("Road Trip", IDS[:3])
    pls = out_json(runner.invoke(app, ["playlists"]))
    assert {p["name"] for p in pls} == {"我喜欢", "Road Trip"}
    shown = out_json(runner.invoke(app, ["show", "Road Trip", "--fields", "id,name"]))
    assert shown["complete"] is True and shown["songs"][0] == {"id": IDS[0], "name": f"Song {IDS[0]}"}


def test_add_dry_run_then_real_then_runs_and_undo(runner, patched_lib, server):
    server.add_playlist("Road Trip", IDS[:2])
    dry = out_json(runner.invoke(app, ["add", "Road Trip", str(IDS[5]), "--dry-run"]))
    assert dry["dry_run"] is True and "run_id" not in dry
    assert server.calls_to("AddSonglist") == []
    assert out_json(runner.invoke(app, ["runs"])) == []

    real = out_json(runner.invoke(app, ["add", "Road Trip", str(IDS[5]), f"{IDS[6]}:0"]))
    assert len(real["added"]) == 2 and real["run_id"]
    assert server.by_name("Road Trip")["songs"] == IDS[:2] + [IDS[5], IDS[6]]
    listed = out_json(runner.invoke(app, ["runs"]))
    assert listed[0]["run_id"] == real["run_id"] and listed[0]["ops"] == ["add 2 song(s) to 'Road Trip'"]

    undone = out_json(runner.invoke(app, ["undo", real["run_id"]]))
    assert undone["undone"] == real["run_id"]
    assert server.by_name("Road Trip")["songs"] == IDS[:2]
    again = runner.invoke(app, ["undo", real["run_id"]])
    assert isinstance(again.exception, UsageError)  # already undone


def test_add_from_stdin_show_document(runner, patched_lib, server):
    server.add_playlist("Src", IDS[10:13])
    server.add_playlist("Dst")
    doc = runner.invoke(app, ["show", "Src"]).stdout
    res = runner.invoke(app, ["add", "Dst", "--stdin"], input=doc)
    assert res.exit_code == 0, res.output
    assert server.by_name("Dst")["songs"] == IDS[10:13]


def test_add_without_songs_is_usage_error(runner, patched_lib):
    result = runner.invoke(app, ["add", "liked"])
    assert isinstance(result.exception, UsageError)


def test_delete_yes_and_undo(runner, patched_lib, server):
    server.add_playlist("Old", IDS[:3])
    res = out_json(runner.invoke(app, ["delete", "Old", "--yes"]))
    assert res["deleted"] is True and res["song_count"] == 3
    undone = out_json(runner.invoke(app, ["undo", res["run_id"]]))
    assert undone["results"][0]["added"] == 3 and server.by_name("Old")["songs"] == IDS[:3]


def test_delete_liked_refused(runner, patched_lib, server):
    result = runner.invoke(app, ["delete", "liked", "--yes"])
    assert isinstance(result.exception, UsageError) and server.calls_to("DelPlaylist") == []


def test_compact_output(runner, patched_lib):
    result = runner.invoke(app, ["--compact", "playlists"])
    assert result.stdout.count("\n") == 1
