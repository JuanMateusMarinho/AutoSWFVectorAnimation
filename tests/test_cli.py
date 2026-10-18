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


import numpy as np
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

def test_convert_rejects_an_alignment_that_is_not_finite(tmp_path, capsys, qapp):
    write_psd(tmp_path / "line.psd", 40, 40, [LayerSpec("Line", rect(40, 40, (0, 0, 0, 255), 10, 10, 30, 30))])
    assert main(["convert", str(tmp_path / "line.psd"), "--align", "nan,0,0"]) == 1
    assert "Alignment must look like SCALE,X,Y or SCALE,X,Y,DEGREES" in capsys.readouterr().out
    assert not (tmp_path / "line.swf").exists()

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


def _parts_psd(tmp_path, size=720):
    from drawings import synthetic_parts_helm
    t = synthetic_parts_helm(size)
    write_psd(tmp_path / "helm.psd", t.width, t.height, t.layers)
    return t

def test_convert_finds_parts_and_wires_color_custom(tmp_path, capsys, qapp):
    t = _parts_psd(tmp_path)
    assert main(["convert", str(tmp_path / "helm.psd"), "--align", str(t.alignment),
                 "--parts-image", str(tmp_path / "parts.png")]) == 0
    out = capsys.readouterr().out
    assert "Parts (17):" in out and "Lock 6" in out and "Eye L" in out and "Helm" in out
    assert "Color custom: Skin None, Skin Dark, Hair None, Hair Light, Hair Darker, Eye None (16 clips)" in out
    assert "its own fixed tones" in out and "— valid" in out
    from PIL import Image
    assert Image.open(tmp_path / "parts.png").size == (t.width, t.height)

def test_convert_reads_the_corrections_file_and_color_options(tmp_path, capsys, qapp):
    import json
    t = _parts_psd(tmp_path)
    s, (ox, oy) = t.alignment.scale, t.alignment.origin
    (tmp_path / "helm.parts.json").write_text(json.dumps({"assign": [{"at": [ox - 9 * s, oy - 17.5 * s], "part": "Helm"}]}))
    assert main(["convert", str(tmp_path / "helm.psd"), "--align", str(t.alignment), "--color", "Helm=Base"]) == 0
    out = capsys.readouterr().out
    assert "Using part corrections from helm.parts.json" in out and "Accessory 1" not in out
    assert "Base" in next(line for line in out.splitlines() if line.strip().startswith("Helm"))

def test_convert_rejects_bad_corrections_and_colors(tmp_path, capsys, qapp):
    t = _parts_psd(tmp_path, 240)
    (tmp_path / "bad.json").write_text('{"assign": [{"at": [1, 2], "part": "Lok 2"}]}')
    assert main(["convert", str(tmp_path / "helm.psd"), "--parts", str(tmp_path / "bad.json")]) == 1
    assert "bad.json: entry 1 of \"assign\": Unknown part 'Lok 2'" in capsys.readouterr().out
    assert main(["convert", str(tmp_path / "helm.psd"), "--color", "Helm=Gold"]) == 1
    assert "Unknown color 'Gold'" in capsys.readouterr().out
    assert not (tmp_path / "helm.swf").exists()

def test_convert_without_parts_keeps_the_static_output(tmp_path, capsys, qapp):
    t = _parts_psd(tmp_path, 240)
    assert main(["convert", str(tmp_path / "helm.psd"), "--align", str(t.alignment), "--no-parts"]) == 0
    out = capsys.readouterr().out
    assert "Parts (" not in out and "Fills:" in out and "— valid" in out

def test_convert_without_parts_refuses_part_options(tmp_path, capsys, qapp):
    t = _parts_psd(tmp_path, 240)
    convert = ["convert", str(tmp_path / "helm.psd"), "--align", str(t.alignment), "--no-parts"]
    (tmp_path / "fix.json").write_text('{"assign": []}')
    assert main(convert + ["--color", "Helm=Base", "--parts-image", str(tmp_path / "parts.png")]) == 1
    assert "--color and --parts-image need parts; they cannot be used with --no-parts" in capsys.readouterr().out
    assert main(convert + ["--parts", str(tmp_path / "fix.json")]) == 1
    assert "--parts needs parts; it cannot be used with --no-parts" in capsys.readouterr().out
    assert not (tmp_path / "helm.swf").exists() and not (tmp_path / "parts.png").exists()
    (tmp_path / "helm.parts.json").write_text('{"assign": []}')       # found next to the drawing: not used
    assert main(convert) == 0
    assert "Using part corrections" not in capsys.readouterr().out

def test_convert_morph_check_needs_the_aqw_files(tmp_path, capsys, monkeypatch, qapp):
    monkeypatch.setenv("AUTOSWF_CACHE", str(tmp_path / "empty"))
    t = _parts_psd(tmp_path, 240)
    assert main(["convert", str(tmp_path / "helm.psd"), "--align", str(t.alignment), "--morph"]) == 0
    assert "Morph check skipped: AQW reference files are missing" in capsys.readouterr().out

def test_preview_snapshot_with_player_colors(tmp_path, capsys, monkeypatch, qapp):
    from aqw_fakes import write_mini_cache
    write_mini_cache(tmp_path / "cache"); monkeypatch.setenv("AUTOSWF_CACHE", str(tmp_path / "cache"))
    main(["demo-helm", str(tmp_path / "demo.swf")]); capsys.readouterr()
    assert main(["preview", str(tmp_path / "demo.swf"), "--armor", "TestArmor", "--snapshot", str(tmp_path / "s.png"),
                 "--player-color", "Hair=FF0000", "--player-color", "skin=#00ff00"]) == 0
    from PIL import Image
    pixels = [tuple(p) for p in np.asarray(Image.open(tmp_path / "s.png").convert("RGB")).reshape(-1, 3)]
    assert pixels.count((255, 0, 0)) > 20 and pixels.count((0, 255, 0)) > 20     # the demo helm's hair and face
    assert main(["preview", str(tmp_path / "demo.swf"), "--armor", "TestArmor", "--snapshot", str(tmp_path / "s.png"),
                 "--player-color", "Hair=red"]) == 1
    assert "Player colors look like Hair=FF0000" in capsys.readouterr().out


def test_convert_line_art_only_with_parts_on(tmp_path, capsys, qapp):
    from drawings import ring
    write_psd(tmp_path / "ring.psd", 200, 200, [LayerSpec("Line", ring(200, 200, (20, 20, 20, 255), 100, 100, 60, 57))])
    assert main(["convert", str(tmp_path / "ring.psd"), "--align", "2,100,100"]) == 0
    out = capsys.readouterr().out
    assert "no flat colors to find parts in" in out and "— valid" in out


def _sprite_frame_counts(path):
    from autoswf.swf.decode import MovieData, SpriteDef
    movie = MovieData(path.read_bytes())
    return [movie.character(c).frame_count for c in movie.character_ids()
            if isinstance(movie.character(c), SpriteDef)]


def test_convert_animates_eyes_and_locks(tmp_path, capsys, qapp):
    import re
    t = _parts_psd(tmp_path)
    assert main(["convert", str(tmp_path / "helm.psd"), "--align", str(t.alignment), "--report"]) == 0
    out = capsys.readouterr().out
    assert "Animation (8 clips):" in out and re.search(r"Eye L\s+Blink\s+87 frames, blinks at frame 11", out)
    assert re.search(r"Lock 6\s+Sway\s+48 frames, 6 links", out)
    assert "Meets the quality bar." in out and "— valid" in out
    counts = _sprite_frame_counts(tmp_path / "helm.swf")
    assert 87 in counts and 48 in counts


def test_convert_animation_options_and_file(tmp_path, capsys, qapp):
    import json
    t = _parts_psd(tmp_path)
    (tmp_path / "helm.anim.json").write_text(json.dumps({"parts": {"Lock 2": "none"},
                                                         "keys": [{"part": "Lock 3", "frame": 12, "rotation": 6}]}))
    assert main(["convert", str(tmp_path / "helm.psd"), "--align", str(t.alignment), "--animate", "Ear L=Twitch",
                 "--sway", "amplitude=20", "--blink", "double=on"]) == 0
    out = capsys.readouterr().out
    assert "Using animation settings from helm.anim.json" in out and "Animation (8 clips):" in out
    assert "twitches at frame 30" in out and "blinks at frames 11 and 19" in out
    assert not any(line.strip().startswith("Lock 2 ") for line in out.split("Animation (")[1].splitlines())


def test_convert_rejects_bad_animation_options(tmp_path, capsys, qapp):
    t = _parts_psd(tmp_path, 240)
    for args, message in [(["--sway", "amp=3"], "Unknown Sway setting 'amp'"),
                          (["--animate", "Lock1"], 'Animations look like "PART=PRESET"'),
                          (["--animate", "Lock 1=Wave"], "Unknown preset 'Wave'"),
                          (["--blink", "double"], "Preset settings look like KEY=VALUE")]:
        assert main(["convert", str(tmp_path / "helm.psd"), *args]) == 1
        assert message in capsys.readouterr().out
    assert not (tmp_path / "helm.swf").exists()


def test_convert_refuses_to_sway_the_hair_base(tmp_path, capsys, qapp):
    t = _parts_psd(tmp_path)
    assert main(["convert", str(tmp_path / "helm.psd"), "--align", str(t.alignment), "--animate", "Hair=Sway"]) == 1
    assert "('Hair' is not one of them)" in capsys.readouterr().out and not (tmp_path / "helm.swf").exists()


def test_convert_without_animation(tmp_path, capsys, qapp):
    t = _parts_psd(tmp_path, 480)
    assert main(["convert", str(tmp_path / "helm.psd"), "--align", str(t.alignment), "--no-animate"]) == 0
    assert "Animation" not in capsys.readouterr().out
    assert set(_sprite_frame_counts(tmp_path / "helm.swf")) == {1}
    assert main(["convert", str(tmp_path / "helm.psd"), "--no-parts", "--sway", "amplitude=20"]) == 1
    assert "--sway needs parts; it cannot be used with --no-parts" in capsys.readouterr().out


def test_convert_without_animation_refuses_animation_options(tmp_path, capsys, qapp):
    t = _parts_psd(tmp_path, 240)
    convert = ["convert", str(tmp_path / "helm.psd"), "--align", str(t.alignment), "--no-animate"]
    (tmp_path / "moves.json").write_text('{"parts": {}}')
    assert main(convert + ["--anim", str(tmp_path / "moves.json"), "--blink", "double=on"]) == 1
    assert "--anim and --blink need animation; they cannot be used with --no-animate" in capsys.readouterr().out
    for option, value in [("--animate", "Ear L=Twitch"), ("--sway", "amplitude=20"), ("--twitch", "angle=5"),
                          ("--pulse", "length=24")]:
        assert main(convert + [option, value]) == 1
        assert "%s needs animation; it cannot be used with --no-animate" % option in capsys.readouterr().out
    assert not (tmp_path / "helm.swf").exists()
    assert main(convert + ["--color", "Helm=Base"]) == 0                  # part options still work without animation
    assert "Animation" not in capsys.readouterr().out


def test_convert_refuses_bad_animation_input_before_reading_the_drawing(tmp_path, capsys, qapp):
    t = _parts_psd(tmp_path, 240)
    for args, message in [(["--anim", str(tmp_path / "missing.json")], "Could not read missing.json"),
                          (["--animate", "Lok 2=Sway"], "Unknown part 'Lok 2'"),
                          (["--blink", "interval=20", "--blink", "double=on"],
                           "Blink needs a loop of at least 24 frames with these settings (got 20)")]:
        assert main(["convert", str(tmp_path / "helm.psd"), *args]) == 1
        out = capsys.readouterr().out
        assert message in out and "Opened" not in out, args
    assert not (tmp_path / "helm.swf").exists()


def test_convert_reads_part_names_like_color(tmp_path, capsys, qapp):
    t = _parts_psd(tmp_path)
    assert main(["convert", str(tmp_path / "helm.psd"), "--align", str(t.alignment), "--animate", "ear l=twitch"]) == 0
    assert "twitches at frame 30" in capsys.readouterr().out
