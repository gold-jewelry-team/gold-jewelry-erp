from app.routers.bank_reconciliation_reports import safe_csv_text


def test_safe_csv_text_preserves_normal_values():
    assert safe_csv_text("一般銀行") == "一般銀行"
    assert safe_csv_text("  一般帳戶") == "  一般帳戶"


def test_safe_csv_text_neutralizes_formula_prefixes():
    for value in ("=1+1", "+SUM(A1:A2)", "-10+20", "@SUM(A1)", "  =1+1", "\t=1+1"):
        assert safe_csv_text(value).startswith("'")


def test_safe_csv_text_does_not_change_numeric_values_as_strings_without_formula_prefix():
    assert safe_csv_text("12345678") == "12345678"
    assert safe_csv_text("2026-11-19") == "2026-11-19"
