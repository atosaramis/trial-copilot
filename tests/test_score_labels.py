"""The blind-label scorer: agreement, per-field figures, confusion tables, and input checks."""
import csv

import pytest
from openpyxl import Workbook

from scripts.score_labels import kappa, read_key, read_sheet, report, score

HEAD = ["Row", "Trial no.", "Trial", "What is compared", "Protocol says", "Your label", "Note (optional)"]
KEY = [  # row_id, nct, field, auto_category, auto_reason, agent_verdict, in_v2_set
    ("R01", "NCT00000001", "sites", "never_changed", "registry kept its 2017 value", "real_discrepancy", "True"),
    ("R02", "NCT00000002", "sites", "caught_up", "registry reached the protocol value", "registry_lagging", "True"),
    ("R03", "NCT00000003", "enrollment", "ambiguous", "our protocol reading is doubtful (upper_bound)",
     "extraction_error", "False"),
    ("R04", "NCT00000004", "phase", "never_changed", "registry kept its 2017 value", "ambiguous", "False"),
    ("R05", "NCT00000005", "sites", "caught_up", "registry reached the protocol value", "real_discrepancy", "False"),
]
FIELD = {"sites": "Number of sites", "enrollment": "Planned enrollment", "phase": "Phase"}


def _files(tmp_path, labels):
    k = tmp_path / "key.csv"
    with open(k, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["row_id", "nct_id", "field", "auto_category", "auto_reason", "agent_verdict", "in_v2_set"])
        w.writerows(KEY)
    wb = Workbook()
    ws = wb.active
    ws.title = "Label"
    ws.append(HEAD)
    for (rid, nct, field, *_), lab in zip(KEY, labels):
        ws.append([rid, 1, nct, FIELD[field], "x", lab, None])
    s = tmp_path / "filled.xlsx"
    wb.save(s)
    return s, k


def test_agreement_with_agent_and_auto_grade(tmp_path):
    s, k = _files(tmp_path, ["Real difference", "Registry lagging", "Our reading wrong", "Real difference", None])
    res = score(read_sheet(s), read_key(k))
    assert res["labelled"] == 4 and res["rows_in_sheet"] == 5
    o = res["overall"]
    assert (o["agent"]["agree"], o["agent"]["n"]) == (3, 4)          # R04: agent said can't tell
    assert (o["auto_grade_settled"]["agree"], o["auto_grade_settled"]["n"]) == (3, 3)   # R03 is not settled
    assert res["by_field"]["sites"]["agent"]["agree"] == 2
    assert res["auto_ambiguous"]["doubtful_reading"] == {"n": 1, "labels": {"Our reading wrong": 1}}
    assert res["confusion_vs_agent"]["Real difference"]["Can't tell"] == 1
    assert res["confusion_vs_auto_category"]["Real difference"]["never_changed"] == 2
    assert (res["v2_comparable_rows"]["agent"]["agree"], res["v2_comparable_rows"]["agent"]["n"]) == (2, 2)
    md = report(res)
    assert "| Agreement | 3/4 (75%) | 3/3 (100%) |" in md and "R04 NCT00000004 phase" in md


def test_cant_tell_is_left_out_of_the_decided_rate(tmp_path):
    s, k = _files(tmp_path, ["Can't tell", "Registry lagging", None, None, "Registry lagging"])
    o = score(read_sheet(s), read_key(k))["overall"]
    assert (o["agent"]["agree"], o["agent"]["n"]) == (1, 3)
    assert (o["agent"]["excluding_cant_tell"]["agree"], o["agent"]["excluding_cant_tell"]["n"]) == (1, 2)
    assert (o["auto_grade_settled"]["excluding_cant_tell"]["agree"], o["auto_grade_settled"]["excluding_cant_tell"]["n"]) == (2, 2)


def test_rejects_unknown_labels_and_mismatched_rows(tmp_path):
    s, k = _files(tmp_path, ["Maybe", None, None, None, None])
    with pytest.raises(SystemExit, match="unknown label"):
        read_sheet(s)
    s, k = _files(tmp_path, [None] * 5)
    rows = read_sheet(s)
    rows[0]["field"] = "phase"
    with pytest.raises(SystemExit, match="key says"):
        score(rows, read_key(k))


def test_kappa():
    assert kappa([("a", "a"), ("b", "b")]) == 1.0
    assert kappa([("a", "b"), ("b", "a")]) == -1.0
    assert kappa([]) is None
