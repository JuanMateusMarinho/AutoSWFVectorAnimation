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


import pytest
from drawings import synthetic_helm, rect
from autoswf.drawing.writers import LayerSpec, write_clip, write_psd

def test_convert_synthetic_helm(tmp_path, capsys, qapp):
    t = synthetic_helm(240)
    write_psd(tmp_path / "helm.psd", t.width, t.height, t.layers)
    assert main(["convert", str(tmp_path / "helm.psd"), "--align", str(t.alignment), "--report"]) == 0
    out = capsys.readouterr().out
    assert (tmp_path / "helm.swf").exists() and validate_helm_swf((tmp_path / "helm.swf").read_bytes(), "helm") == []
    assert "Shadow  shadow" in out and "Alignment: set with --align" in out and "— valid" in out and "Edges" in out

def test_convert_help_says_which_way_align_rotates(capsys):
    with pytest.raises(SystemExit):
        main(["convert", "--help"])
    help_text = " ".join(capsys.readouterr().out.split())
    assert "turns the drawing clockwise onto the head (a drawing that is turned clockwise needs a negative DEG)" in help_text

def test_convert_without_role_names_and_errors(tmp_path, capsys, qapp):
    write_clip(tmp_path / "sketch.clip", 80, 60, [LayerSpec("Layer 1", rect(80, 60, (20, 20, 20, 255), 10, 10, 70, 50))])
    assert main(["convert", str(tmp_path / "sketch.clip"), "-o", str(tmp_path / "s.swf")]) == 0
    out = capsys.readouterr().out
    assert 'Layer 1  not used  (no role in its name; pass --role "Layer 1=line")' in out
    assert "vectorized as flat colors" in out and "fitted to the AQW head" in out
    assert main(["convert", str(tmp_path / "sketch.clip"), "--role", "Layer 1=shiny"]) == 1
    assert "Unknown role 'shiny'" in capsys.readouterr().out
    write_psd(tmp_path / "empty.psd", 20, 20, [LayerSpec("Line", rect(20, 20, (0, 0, 0, 255), 0, 0, 5, 5), visible=False)])
    assert main(["convert", str(tmp_path / "empty.psd")]) == 1
    assert "Nothing to vectorize" in capsys.readouterr().out

def test_template_command(tmp_path, capsys, monkeypatch, qapp):
    from aqw_fakes import write_mini_cache
    monkeypatch.setenv("AUTOSWF_CACHE", str(tmp_path / "empty"))
    assert main(["template", str(tmp_path / "t.psd")]) == 1
    assert "python -m autoswf download-aqw" in capsys.readouterr().out
    write_mini_cache(tmp_path / "cache"); monkeypatch.setenv("AUTOSWF_CACHE", str(tmp_path / "cache"))
    assert main(["template", str(tmp_path / "t.psd")]) == 0 and (tmp_path / "t.psd").exists()

@pytest.mark.real
def test_convert_the_users_real_clip_file(real_drawing, tmp_path, capsys, qapp):
    assert main(["convert", str(real_drawing), "-o", str(tmp_path / "real.swf")]) == 0
    assert "Paper  not used  (ignored: background)" in capsys.readouterr().out

def test_convert_refuses_transparent_drawings_and_overwriting_the_drawing(tmp_path, capsys, qapp):
    write_psd(tmp_path / "ghost.psd", 40, 40, [LayerSpec("Flats", rect(40, 40, (200, 0, 0, 255), 5, 5, 30, 30), opacity=0.0)])
    assert main(["convert", str(tmp_path / "ghost.psd")]) == 1
    assert "Nothing to vectorize" in capsys.readouterr().out
    write_psd(tmp_path / "helm.psd", 40, 40, [LayerSpec("Flats", rect(40, 40, (200, 0, 0, 255), 5, 5, 30, 30))])
    before = (tmp_path / "helm.psd").read_bytes()
    assert main(["convert", str(tmp_path / "helm.psd"), "-o", str(tmp_path / "helm.psd")]) == 1
    assert main(["convert", str(tmp_path / "helm.psd"), "-o", str(tmp_path / "helm.png")]) == 1
    out = capsys.readouterr().out
    assert "would overwrite the drawing" in out and "must be a .swf file" in out
    assert (tmp_path / "helm.psd").read_bytes() == before and not (tmp_path / "helm.png").exists()
