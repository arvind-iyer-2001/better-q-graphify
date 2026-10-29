from qverify.qdetect import looks_like_q


def test_q_code_detected(tmp_path):
    f = tmp_path / "a.q"
    f.write_text("\\d .x\nf:{select from t where a>1}\nt:([] a:1 2 3)\n")
    assert looks_like_q(f)


def test_word_list_and_random_data_rejected(tmp_path):
    a = tmp_path / "log.q"
    a.write_text("ymtg postterm 49 block centre tianjin be esperance\n" * 300)
    b = tmp_path / "fuzz.q"
    b.write_bytes(bytes(range(256)) * 50)
    assert not looks_like_q(a) and not looks_like_q(b)
