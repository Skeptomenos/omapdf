"""Unit tests for scratch page-preview state."""

from omepreview.page_preview import PagePreviewState
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
