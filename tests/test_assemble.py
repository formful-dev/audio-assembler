"""End-to-end assembly on generated audio, including synthetic versions of acceptance tests 1 and 2."""

import hashlib

import numpy as np
import pytest

from audio_assembler.core import AssemblerError, Job, OrderListError, Settings, assemble, export, prepare
from audio_assembler.core.audio_io import decode
from audiogen import make_track, read_wav, write_order, write_wav

RATE = 16000
Q = 2.5 / 32767  # 16-bit rounding tolerance


def natural(r):
    return r.uniform(0.2, 0.9)


def lesson(tmp_path, lv_words=(3, 5, 2, 4, 6, 1, 3, 4, 2), en_words=(4, 2, 5, 3, 3, 6, 2), **kw):
    """Like the production files: LV ends with a cut silence, EN starts with one. 15 s cuts."""
    lv = make_track(list(lv_words), 15.0, natural, rate=RATE, lead=0.4, trail=15.0, seed=21, **kw)
    en = make_track(list(en_words), 15.0, natural, rate=RATE, lead=15.0, trail=0.4, seed=22)
    a = write_wav(tmp_path / "TEST_LV.wav", lv.samples, RATE)
    b = write_wav(tmp_path / "TEST_EN.wav", en.samples, RATE)
    rows, n = [], 1
    for i in range(1, 8):
        rows += [(n, "LV", i, 2), (n + 1, "EN", i, 2)]
        n += 2
    rows += [(15, "LV", 8, 2), (16, "LV", 9, 0)]
    order = write_order(tmp_path / "TEST_ORDER.csv", rows)
    return lv, en, a, b, order, rows


def job_for(a, b, order, **settings):
    return Job(str(a), str(b), str(order), "LV", "EN", Settings(output_format="wav", **settings))


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test1_synthetic_full_lesson(tmp_path):
    lv, en, a, b, order, rows = lesson(tmp_path)
    before = {p: sha(p) for p in (a, b, order)}
    plan = prepare(job_for(a, b, order))
    assert [len(t.detection.segments) for t in plan.tracks] == [9, 7]
    assert plan.tracks[0].detection.trailing_silence > 14.5   # LV trailing silence ignored
    assert plan.tracks[1].detection.leading_silence > 14.5    # EN leading silence ignored
    assert plan.warnings == []
    assert plan.order.total_gap == pytest.approx(30.0)

    result = export(plan)
    assert result.output_path.name == "TEST_FINAL.wav"
    assert (tmp_path / "TEST_FINAL_report.txt").is_file()
    out, rate = read_wav(result.output_path)
    assert rate == RATE

    truth = {"LV": lv, "EN": en}
    pos = 0
    for r in plan.order.rows:
        t = plan.track(r.label)
        seg = t.detection.segments[r.segment - 1]
        length = seg.end - seg.start
        piece = out[pos:pos + length, 0]
        # No clicks: every piece starts and ends at silence.
        assert abs(piece[0]) <= Q and abs(piece[-1]) <= Q
        # No speech clipped: the true sound is present, unchanged.
        ta, tb = truth[r.label].segments[r.segment - 1]
        src = truth[r.label].samples[ta:tb, 0]
        np.testing.assert_allclose(piece[ta - seg.start:tb - seg.start], np.clip(src, -1, 1), atol=Q)
        # Exact gap of silence after the segment.
        gap = round(r.gap * RATE)
        assert np.all(np.abs(out[pos + length:pos + length + gap, 0]) <= Q)
        pos += length + gap
    assert pos == out.shape[0]   # 16 segments + gaps, nothing else
    assert len(plan.order.rows) == 16

    report = result.report_path.read_text(encoding="utf-8")
    assert "Segments found: 9" in report and "Segments found: 7" in report
    assert "Inserted gaps total: 30.00 s" in report
    assert before == {p: sha(p) for p in (a, b, order)}   # inputs never modified


def test2_synthetic_broken_order_list(tmp_path):
    _, _, a, b, _, rows = lesson(tmp_path)
    rows[3] = (4, "EN", 8, 2)
    broken = write_order(tmp_path / "TEST_ORDER_BROKEN.csv", rows)
    with pytest.raises(OrderListError) as e:
        assemble(job_for(a, b, broken))
    text = e.value.text()
    assert "Row 4 (order 4): EN segment 8 does not exist. EN has only 7 segments." in text
    assert not list(tmp_path.glob("*_FINAL*"))   # nothing exported


def test_different_rate_and_channels(tmp_path):
    a_tr = make_track([3, 2], 3.0, 0.3, rate=22050, seed=31)
    b_tr = make_track([2, 4], 3.0, 0.3, rate=44100, channels=2, seed=32)
    a = write_wav(tmp_path / "x_A.wav", a_tr.samples, 22050)
    b = write_wav(tmp_path / "x_B.wav", b_tr.samples, 44100)
    order = write_order(tmp_path / "x.csv", [(1, "A", 1, 1), (2, "B", 2, 0.5), (3, "A", 2, 0), (4, "B", 1, 0)])
    job = Job(str(a), str(b), str(order), "A", "B", Settings(output_format="wav"))
    res = assemble(job)
    out, rate = read_wav(res.output_path)
    assert rate == 44100 and out.shape[1] == 2
    assert res.output_path.name == "x_FINAL.wav"


def test_mp3_output(tmp_path):
    _, _, a, b, order, _ = lesson(tmp_path, lv_words=(2,) * 9)
    res = assemble(Job(str(a), str(b), str(order), "LV", "EN"))
    assert res.output_path.suffix == ".mp3"
    samples, rate, _ = decode(str(res.output_path))
    assert abs(samples.shape[0] / rate - res.duration) < 0.2
    assert "MP3, 160 kbps, 16000 Hz" in res.format_description   # highest bitrate valid at 16 kHz


def test_reused_and_unused_segments(tmp_path):
    _, _, a, b, _, _ = lesson(tmp_path)
    order = write_order(tmp_path / "o.csv", [(1, "LV", 1, 1), (2, "EN", 1, 1), (3, "LV", 1, 0), (4, "lv", 9, 0)])
    plan = prepare(job_for(a, b, order))
    assert any("LV: 7 segment(s) are never used" in w and "2-8" in w for w in plan.warnings)
    assert any("EN: 6 segment(s)" in w for w in plan.warnings)
    calls = []
    assert assemble(job_for(a, b, order), lambda w: calls.append(w) or False) is None
    assert calls and not list(tmp_path.glob("*_FINAL*"))


def test_unknown_label(tmp_path):
    _, _, a, b, _, _ = lesson(tmp_path, lv_words=(2,) * 9)
    order = write_order(tmp_path / "o.csv", [(1, "LV", 1, 1), (2, "DE", 1, 1)])
    with pytest.raises(OrderListError) as e:
        prepare(job_for(a, b, order))
    assert "'DE'" in e.value.text() and "Row 2" in e.value.text()


def test_same_labels_and_missing_file(tmp_path):
    _, _, a, b, order, _ = lesson(tmp_path, lv_words=(2,) * 9)
    with pytest.raises(AssemblerError, match="same label"):
        prepare(Job(str(a), str(b), str(order), "LV", "lv"))
    with pytest.raises(AssemblerError, match="not found"):
        prepare(Job(str(tmp_path / "missing.wav"), str(b), str(order), "LV", "EN"))


def test_output_cannot_overwrite_input(tmp_path):
    _, _, a, b, order, _ = lesson(tmp_path, lv_words=(2,) * 9)
    job = job_for(a, b, order)
    job.output_name = "TEST_LV"
    with pytest.raises(AssemblerError, match="overwrite"):
        prepare(job)


def test_loudness_matching(tmp_path):
    lv, en, a, b, order, _ = lesson(tmp_path, lv_words=(3,) * 9)
    loud = make_track([3] * 7, 15.0, natural, rate=RATE, lead=15.0, trail=0.4, seed=22, level=2.0)
    write_wav(b, loud.samples, RATE)
    plan = prepare(job_for(a, b, order, match_loudness=True))
    lv_t, en_t = plan.tracks
    assert lv_t.gain_db == 0
    assert en_t.gain_db < -1.0   # the louder track is turned down, never up
