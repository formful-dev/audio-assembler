import pytest

from audio_assembler.core.errors import OrderListError
from audio_assembler.core.orderlist import parse_order_list, read_order_list
from audiogen import write_order

ROWS = [(1, "LV", 1, 2), (2, "EN", 1, 1.5), (3, "LV", 2, 0), (4, "EN", 1, 3)]


def test_comma_with_header(tmp_path):
    ol = read_order_list(str(write_order(tmp_path / "o.csv", ROWS)))
    assert [(r.label, r.segment, r.gap) for r in ol.rows] == [("LV", 1, 2), ("EN", 1, 1.5), ("LV", 2, 0), ("EN", 1, 3)]
    assert ol.has_header and ol.separator == ","
    assert ol.total_gap == pytest.approx(6.5)
    assert ol.max_segment("en") == 1   # labels are matched regardless of case


def test_semicolon_decimal_comma_bom(tmp_path):
    p = write_order(tmp_path / "o.csv", ROWS, header="order;language;segment;gap_seconds",
                    sep=";", bom=True, decimal_comma=True)
    ol = read_order_list(str(p))
    assert ol.separator == ";"
    assert [r.gap for r in ol.rows] == [2, 1.5, 0, 3]


def test_tab_separator_and_no_header(tmp_path):
    ol = read_order_list(str(write_order(tmp_path / "o.csv", ROWS, header="", sep="\t")))
    assert not ol.has_header and len(ol.rows) == 4


def test_rows_sorted_by_order_number():
    ol = parse_order_list("order,language,segment,gap\n3,LV,3,0\n1,LV,1,0\n2,EN,1,0\n")
    assert [r.order for r in ol.rows] == [1, 2, 3]
    assert [r.row for r in ol.rows] == [2, 3, 1]


def test_crlf_and_blank_lines_and_empty_excel_rows():
    ol = parse_order_list("order;language;segment;gap\r\n1;LV;1;2\r\n\r\n;;;\r\n2;EN;1;1,25\r\n")
    assert len(ol.rows) == 2 and ol.rows[1].gap == 1.25


@pytest.mark.parametrize("text,needle", [
    ("order,language,segment\n1,LV,1\n", "only 3 column"),
    ("order,language,segment,gap\n1,LV,1,\n", "Row 1: a value is missing"),
    ("order,language,segment,gap\n1,LV,x,1\n", "segment number 'x'"),
    ("order,language,segment,gap\n1,LV,0,1\n", "segment number '0'"),
    ("order,language,segment,gap\n1,LV,1.5,1\n", "segment number '1.5'"),
    ("order,language,segment,gap\nA,LV,1,1\n", "Row 1"),
    ("order,language,segment,gap\n1,LV,1,-2\n", "gap '-2'"),
    ("order,language,segment,gap\n1,LV,1,abc\n", "gap 'abc'"),
    ("order,language,segment,gap\n1,LV,1,1\n1,EN,1,1\n", "order number 1 is also used in row 1"),
    ("order,language,segment,gap\n1,LV,1,2,5\n", "decimal comma"),
    ("order,language,segment,gap\n", "no rows"),
    ("", "empty"),
])
def test_errors(text, needle):
    with pytest.raises(OrderListError) as e:
        parse_order_list(text)
    assert needle in e.value.text()


def test_all_problems_reported_at_once():
    with pytest.raises(OrderListError) as e:
        parse_order_list("order,language,segment,gap\n1,LV,x,1\n2,EN,1,-1\n")
    assert len(e.value.details) == 2


def test_extra_named_column_allowed():
    ol = parse_order_list("order,language,segment,gap,note\n1,LV,1,2,hello\n")
    assert ol.rows[0].gap == 2


def test_missing_file(tmp_path):
    with pytest.raises(OrderListError):
        read_order_list(str(tmp_path / "nope.csv"))
