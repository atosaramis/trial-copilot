from app.extract import fix_mojibake, normalise_text, strip_change_history


def test_unnumbered_summary_of_changes_ends_at_first_section():
    pages = ["Title page\nSummary of Changes\nInclusion 3 was loosened\nAge raised to 80",
             "1. INTRODUCTION\nBackground text"]
    out, removed = strip_change_history(pages)
    assert len(out) == 2
    assert "loosened" not in out[0] and "Age raised" not in out[0]
    assert "Title page" in out[0]
    assert "INTRODUCTION" in out[1]
    assert removed[0]["first_page"] == 1 and removed[0]["last_page"] == 1


def test_numbered_rationale_for_amendment_ends_at_next_section():
    pages = ["3.3. Benefit/Risk\nkeep me\n3.4. Rationale for Study Amendment (a)\nchanged criteria",
             "more changed text\n3.5. Study Objectives\nkeep objectives"]
    out, removed = strip_change_history(pages)
    assert "keep me" in out[0] and "changed criteria" not in out[0]
    assert "more changed text" not in out[1] and "keep objectives" in out[1]


def test_appendix_amendment_runs_to_end_even_past_quoted_appendix_1():
    pages = ["5. Methods\nkeep",
             "Appendix 7. Protocol Amendment ABC(a)\nSummary\nrevised section 3",
             "Appendix 1 Abbreviations and Definitions (revised text)\nquoted"]
    out, removed = strip_change_history(pages)
    assert "keep" in out[0]
    assert "revised section" not in out[1] and "quoted" not in out[2]
    assert removed[0]["last_page"] == 3


def test_toc_pages_and_unrelated_summaries_are_kept():
    toc = "\n".join(f"{i}. Section {i} ........................ {i * 3}" for i in range(1, 6))
    toc += "\nAppendix 7. Protocol Amendment ABC(a) Summary ............ 62"
    pages = [toc, "Appendix 4. Summary of Radiation Dose\n2 scans"]
    out, removed = strip_change_history(pages)
    assert removed == []
    assert out == pages


def test_page_count_is_preserved():
    pages = ["a", "Revision History\nv1 to v2", "b", "1. Intro\nc"]
    out, _ = strip_change_history(pages)
    assert len(out) == 4


def test_junk_word_unicode_and_mojibake():
    assert "5HGDFWHG" not in normalise_text("Name 5HGDFWHG here")
    assert fix_mojibake("ECOG \u00e2\u2030\u00a4 1") == "ECOG \u2264 1"
    assert normalise_text("\ufb01rst dose") == "first dose"  # ligature fi
    assert fix_mojibake("plain text") == "plain text"
