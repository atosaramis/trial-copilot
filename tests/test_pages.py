from app.extract import find_schedule_pages, is_toc_page, text_payload

GRID = "Visit        V1  V2  V3\n" + "\n".join(f"Assessment {i}  X   X   X" for i in range(6))
TOC = "\n".join(f"{i}. Section {i} ................................ {i}" for i in range(1, 5)) + \
      "\n2. Schedule of Activities ......................... 7"


def test_toc_detection():
    assert is_toc_page(TOC)
    assert not is_toc_page(GRID)


def test_schedule_found_from_title_on_previous_page_and_toc_ignored():
    pages = [TOC, "Intro text", "2. Schedule of Activities", GRID, GRID, "Prose about dosing."]
    s = find_schedule_pages(pages)
    assert s["selected"] == [4, 5]
    assert s["found_by"] == "spec_regex"
    assert 1 not in s["title_hits_spec_regex"]


def test_cap_of_three_keeps_first_and_last_page():
    pages = ["Table 1 Study Plan\n" + GRID] + [GRID] * 5 + ["end"]
    s = find_schedule_pages(pages)
    assert len(s["selected"]) == 3
    assert 1 in s["selected"] and 6 in s["selected"]
    assert s["truncated"] is True
    assert s["all_schedule_pages"] == [1, 2, 3, 4, 5, 6]
    assert s["found_by"] == "extra_regex"


def test_small_grids_elsewhere_are_not_added():
    pages = ["Visit evaluation schedule\n" + GRID, "text", "adhere to the visit schedule x x x x x"]
    s = find_schedule_pages(pages)
    assert s["selected"] == [1]


def test_not_found():
    s = find_schedule_pages(["no tables here", "still none"])
    assert s["selected"] == [] and s["found_by"] == "not_found"


def test_payload_page_markers():
    t = text_payload(["a", "b"])
    assert t.startswith("=== PAGE 1 ===\na") and "=== PAGE 2 ===\nb" in t
