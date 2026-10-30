from pathlib import Path

from qverify.extractor_q import extract_q


def edges(tmp_path: Path, code: str) -> set[tuple[str, str, str]]:
    f = tmp_path / "t.q"
    f.write_text(code)
    r = extract_q(f)
    lab = {n["id"]: n["label"] for n in r["nodes"]}
    return {(lab[e["source"]], e["relation"], lab[e["target"]])
            for e in r["edges"] if e["relation"] in ("calls", "reads", "uses", "writes")}


def test_builtins_are_not_references(tmp_path):
    assert edges(tmp_path, "f:{count string x}\n") == set()


def test_params_and_implicit_args_shadow_globals(tmp_path):
    e = edges(tmp_path, "t:1\nf:{[t] t+1}\ng:{x+y}\n")
    assert not any(src in ("f", "g") for src, _, _ in e)


def test_locals_shadow_globals(tmp_path):
    e = edges(tmp_path, "v:1\nf:{v:2; v+1}\n")
    assert ("f", "reads", "v") not in e


def test_global_variable_read_is_an_edge(tmp_path):
    assert ("f", "reads", "dbdir") in edges(tmp_path, "dbdir:`:hdb\nf:{x,dbdir}\n")


def test_calls_vs_reads(tmp_path):
    e = edges(tmp_path, "h:{x}\nk:1\nf:{h each k}\n")
    assert ("f", "calls", "h") in e and ("f", "reads", "k") in e


def test_namespace_qualification_and_absolute_names(tmp_path):
    e = edges(tmp_path, "\\d .an\nh:{x}\nf:{h x}\ng:{.util.mean x}\n")
    assert (".an.f", "calls", ".an.h") in e and (".an.g", "calls", ".util.mean") in e


def test_nested_lambda_does_not_see_parent_locals(tmp_path):
    e = edges(tmp_path, "a:1\nf:{[a] {x+a} 1}\n")
    assert ("f", "reads", "a") in e  # inner lambda has no parameter a: it reads the global


def test_qsql_from_param_is_not_a_table_use_but_global_table_is(tmp_path):
    e = edges(tmp_path, "trade:1\nf:{[t] select from t}\ng:{select from trade}\n")
    assert not any(s == "f" for s, _, _ in e) and ("g", "uses", "trade") in e


def test_qsql_columns_are_not_globals_unless_defined_here(tmp_path):
    e = edges(tmp_path, "lim:1\nf:{select from trade where px>lim, sym=`a}\n")
    assert ("f", "reads", "lim") in e and ("f", "reads", "px") not in e


def test_self_reference_ignored(tmp_path):
    assert ("f", "calls", ".z.s") not in edges(tmp_path, "f:{.z.s x}\n")


def test_global_writes(tmp_path):
    e = edges(tmp_path, "g:0\nt:([]a:1 2)\nf:{g::1}\nh:{g+::1}\nk:{.ns.v:1}\nm:{t[0]:5}\nn:{g:1; g}\n")
    assert ("f", "writes", "g") in e and ("h", "writes", "g") in e
    assert ("k", "writes", ".ns.v") in e and ("m", "writes", "t") in e
    assert not any(s == "n" for s, _, _ in e)  # `g:1` inside a lambda is a local


def test_self_recursion_kept(tmp_path):
    assert ("f", "calls", "f") in edges(tmp_path, "f:{$[x>0;f x-1;0]}\n")


def test_system_d_switches_namespace(tmp_path):
    e = edges(tmp_path, 'system "d .perm";\nh:{x}\nf:{h x}\n')
    assert (".perm.f", "calls", ".perm.h") in e


def test_glued_assignment_name_and_module_namespace(tmp_path):
    e = edges(tmp_path, "f:{.z.m.log:1; .z.m.other x}\n")
    assert not any(t.startswith(".z.m") or ":" in t for _, _, t in e)


def test_chained_assignment_defines_both_names(tmp_path):
    e = edges(tmp_path, "g:1\n.t.a:.t.b:{g}\n")
    assert (".t.a", "writes", ".t.b") not in e and (".t.a", "reads", "g") in e and (".t.b", "reads", "g") in e


def test_typed_null_suffix_not_an_identifier(tmp_path):
    assert edges(tmp_path, "f:{(1f;0nf;0wu;0Nj)}\n") == set()


def test_column_update_inside_qsql_is_not_a_global_write(tmp_path):
    e = edges(tmp_path, "t:1\nf:{update c-:1 from t}\n")
    assert not any(r == "writes" for _, r, _ in e)


def test_relative_dotted_name_is_namespace_relative(tmp_path):
    e = edges(tmp_path, "\\d .ml\ni.g:{x}\nf:{i.g x}\n")
    assert (".ml.f", "calls", ".ml.i.g") in e


def test_names_differing_only_by_case_stay_distinct(tmp_path):
    e = edges(tmp_path, "l:1\nL:2\nf:{l}\ng:{L}\n")
    assert ("f", "reads", "l") in e and ("g", "reads", "L") in e
    assert ("f", "reads", "L") not in e and ("g", "reads", "l") not in e


def test_parse_error_does_not_swallow_later_definitions(tmp_path):
    code = ("h:{x}\nbad:{\n update s:2000.01.01D0^s,r:2000.01.01D0^r from `t where c=x;\n"
            " h exec q from t where c=x;}\ng:{h x}\nk:{g x}\n")
    e = edges(tmp_path, code)
    assert ("g", "calls", "h") in e and ("k", "calls", "g") in e
