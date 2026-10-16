from autoswf.aqw.validate import validate_helm_swf
from autoswf.cli import main


def test_demo_helm_writes_valid_file(tmp_path, capsys):
    out = tmp_path / "demo.swf"
    assert main(["demo-helm", str(out)]) == 0
    assert validate_helm_swf(out.read_bytes(), "AutoSwfDemoMorph") == []
    assert "valid" in capsys.readouterr().out


def test_inspect_lists_classes(tmp_path, capsys):
    out = tmp_path / "demo.swf"; main(["demo-helm", str(out), "--link", "Kit"]); capsys.readouterr()
    assert main(["inspect", str(out)]) == 0
    assert "Kit_fla." in capsys.readouterr().out
