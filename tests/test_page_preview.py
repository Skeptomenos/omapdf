"""Unit tests for scratch page-preview state."""

from omepreview.page_preview import PagePreviewState, index_after_move
from tests.data.make_docs import make_labeled_pdf


def test_preview_delete_and_insert_blank(tmp_path):
    pdf = make_labeled_pdf(tmp_path / "doc.pdf", page_count=5)
    state = PagePreviewState(pdf)
    state.add_delete_pages([2, 4])
    assert state.page_count() == 3
    state.add_insert_blank(0)
    assert state.page_count() == 4
    assert state.has_changes()
    state.clear()
    assert not state.has_changes()
    assert state.page_count() == 5


def test_preview_move_pages(tmp_path):
    pdf = make_labeled_pdf(tmp_path / "six.pdf", page_count=6)
    state = PagePreviewState(pdf)
    state.add_move_pages([5, 6], after=1)
    doc = state.open_view()
    labels = [doc[n].get_text("text").strip().split()[-1] for n in range(doc.page_count)]
    doc.close()
    assert labels == ["1", "5", "6", "2", "3", "4"]


def test_identities_match_engine_order_after_move(tmp_path):
    pdf = make_labeled_pdf(tmp_path / "six.pdf", page_count=6)
    state = PagePreviewState(pdf)
    state.add_move_pages([5, 6], after=1)
    assert state.identities() == [0, 4, 5, 1, 2, 3]


def test_preview_illegal_move_is_noop(tmp_path):
    pdf = make_labeled_pdf(tmp_path / "six.pdf", page_count=6)
    state = PagePreviewState(pdf)
    state.move_selection_to_after([3], after=3)
    assert not state.has_changes()
    state.move_selection_to_after([2, 3], after=2)
    assert not state.has_changes()
    state.move_selection_to_after([5, 6], after=1)
    assert state.has_changes()
    doc = state.open_view()
    labels = [doc[n].get_text("text").strip().split()[-1] for n in range(doc.page_count)]
    doc.close()
    assert labels == ["1", "5", "6", "2", "3", "4"]


def test_index_after_move_page_4_in_front_of_page_2(tmp_path):
    """Drop page 4 in front of page 2 → dest index 1; that page is PAGE 4."""
    assert index_after_move(4, [4], after=1) == 1
    assert index_after_move(4, [4], after=0) == 0
    assert index_after_move(4, [3, 4], after=1) == 1
    pdf = make_labeled_pdf(tmp_path / "four.pdf", page_count=4)
    state = PagePreviewState(pdf)
    n = state.page_count()
    pages = [4]
    after = 1
    dest = index_after_move(n, pages, after)
    state.add_move_pages(pages, after)
    doc = state.open_view()
    labels = [doc[i].get_text("text").strip().split()[-1] for i in range(doc.page_count)]
    doc.close()
    assert labels == ["1", "4", "2", "3"]
    assert dest == 1
    assert labels[dest] == "4"


def test_index_after_move_matches_engine_order():
    # Move [5, 6] after 1 → 1,5,6,2,3,4 — first moved page lands at index 1.
    assert index_after_move(6, [5, 6], after=1) == 1
    # Move [2] after last remaining page 6 → 1,3,4,5,6,2.
    assert index_after_move(6, [2], after=6) == 5
