from audio_assembler.cli import main
from audio_assembler.core import Settings, find_lesson_sets, run_batch
from audio_assembler.core.naming import label_from_filename, shared_base_name, suggest_labels
from audiogen import make_track, write_order, write_wav

RATE = 16000


def make_set(folder, base, broken=False):
    lv = make_track([2, 3, 2], 4.0, 0.3, rate=RATE, seed=41)
    en = make_track([3, 2], 4.0, 0.3, rate=RATE, seed=42)
    write_wav(folder / f"{base}_LV.wav", lv.samples, RATE)
    write_wav(folder / f"{base}_EN.wav", en.samples, RATE)
    seg = 9 if broken else 2
    write_order(folder / f"{base}_ORDER.csv", [(1, "LV", 1, 1), (2, "EN", seg, 1), (3, "LV", 3, 0)])


def test_naming():
    assert label_from_filename("C:/x/TEST_LV.mp3") == "LV"
    assert label_from_filename("lesson 3 - EN.wav") == "EN"
    assert label_from_filename("single.wav") is None
    assert suggest_labels("a_LV.wav", "a_EN.wav") == ("LV", "EN")
    assert suggest_labels("one.wav", "two.wav") == ("A", "B")
    assert shared_base_name("TEST_LV.wav", "TEST_EN.wav") == "TEST"
    assert shared_base_name("Lesson1_LV.wav", "Lesson1_LT.wav") == "Lesson1"
    assert shared_base_name("abc.wav", "xyz.wav") == "abc"


def test_batch_one_failure_does_not_stop_others(tmp_path):
    make_set(tmp_path, "L1")
    make_set(tmp_path, "L2", broken=True)
    make_set(tmp_path, "L3")
    (tmp_path / "L4_LV.wav").write_bytes((tmp_path / "L1_LV.wav").read_bytes())  # incomplete set
    s = Settings(output_format="wav")
    sets = find_lesson_sets(str(tmp_path), s)
    assert [x.base for x in sets] == ["L1", "L2", "L3", "L4"]
    results = {r.base: r for r in run_batch(str(tmp_path), s)}
    assert results["L1"].status == "warning"   # LV segment 2 and EN segment 1 unused
    assert results["L3"].status == "warning"
    assert results["L2"].status == "error" and "EN segment 9" in results["L2"].message
    assert results["L4"].status == "error" and "Missing" in results["L4"].message
    assert (tmp_path / "L1_FINAL.wav").is_file() and (tmp_path / "L3_FINAL.wav").is_file()
    assert not (tmp_path / "L2_FINAL.wav").exists()
    assert (tmp_path / "_batch_summary.txt").is_file()


def test_batch_skip_warnings(tmp_path):
    make_set(tmp_path, "L1")
    s = Settings(output_format="wav", batch_export_with_warnings=False)
    (r,) = run_batch(str(tmp_path), s)
    assert r.status == "skipped" and not (tmp_path / "L1_FINAL.wav").exists()


def test_cli_lesson_and_errors(tmp_path, capsys):
    make_set(tmp_path, "C")
    args = [str(tmp_path / "C_LV.wav"), str(tmp_path / "C_EN.wav"), str(tmp_path / "C_ORDER.csv"),
            "--format", "wav", "-q"]
    assert main(["lesson", *args]) == 2            # warnings, not confirmed (no terminal)
    assert main(["lesson", *args, "--yes"]) == 0
    assert (tmp_path / "C_FINAL.wav").is_file()
    assert main(["lesson", *args, "--yes", "--labels", "LV", "DE"]) == 1
    assert "What to do" in capsys.readouterr().err
    assert main(["analyze", str(tmp_path / "C_LV.wav")]) == 0
    assert main(["folder", str(tmp_path), "--format", "wav", "-q"]) == 0
