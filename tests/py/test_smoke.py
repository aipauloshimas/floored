def test_server_serves_sample_and_engine(tmp_path, server_factory):
    srv = server_factory(tmp_path)                       # conftest: floored.py serve on a free port
    takes = srv.get_json("/api/takes")
    assert takes[-1]["take"]["id"] == "sample"
    assert srv.get("/engine/engine.js").status == 200
    assert (tmp_path / "floored" / "takes").is_dir()


def test_sample_files_are_served_read_only(tmp_path, server_factory):
    srv = server_factory(tmp_path)
    assert srv.get("/takes/sample/person.webm").status == 200
    assert srv.get("/takes/sample/take.json").json()["id"] == "sample"
    assert srv.get("/takes/../x").status in (403, 404)
    assert srv.request("/takes/sample/take.json", "PUT", b"{}").status == 405


def test_paths_and_workspace(tmp_path, monkeypatch):
    from ft import paths
    monkeypatch.setenv("FLOORED_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("FLOORED_RVM_MODEL", str(tmp_path / "m.onnx"))
    assert paths.user_dir() == tmp_path / "home"
    assert paths.rvm_model_path() == tmp_path / "m.onnx"
    assert (paths.SAMPLE_DIR / "take.json").is_file() and (paths.WEB_DIR / "index.html").is_file()
    ws = paths.Workspace(tmp_path / "proj").ensure()
    assert ws.root == tmp_path / "proj" / "floored" and ws.takes.is_dir() and ws.exports.is_dir()


def test_proc_tool_lookup(tmp_path, monkeypatch):
    import sys
    import pytest
    from ft import proc
    monkeypatch.setenv("FLOORED_HOME", str(tmp_path))
    (tmp_path / "config.json").write_text('{"tools": {"mytool": "%s"}}' % sys.executable.replace("\\", "\\\\"))
    assert proc.tool("mytool") == sys.executable
    with pytest.raises(proc.MissingTool):
        proc.tool("definitely-not-a-program-xyz")
    code, out, _ = proc.run([sys.executable, "-c", "print(7)"])
    assert (code, out.strip()) == (0, "7")


def test_server_starts_in_a_workspace_with_spaces_and_accents(tmp_path, server_factory):
    # PYTHONUTF8 removed and output redirected to a file: Windows would use the ANSI code page for the startup line
    ws = tmp_path / "Área de Trabalho" / "meu reel ção ł日本"
    ws.mkdir(parents=True)
    srv = server_factory(ws, utf8=False)
    assert srv.get_json("/api/takes")[-1]["take"]["id"] == "sample"
    assert (ws / "floored" / "takes").is_dir()
    assert "meu reel" in srv.log_path.read_text(encoding="utf-8", errors="replace")
