import pytest

from services.update_checker import UpdateCheckerThread

@pytest.fixture
def checker_for(http_stub, qapp):
    def make(current, payload=None, status=200, body=None):
        if payload is not None or body is not None:
            http_stub.route("/latest", body if body is not None else payload, status=status)
        thread = UpdateCheckerThread(current)
        thread.repo_url = f"{http_stub.base}/latest"
        return thread

    return make

def run_and_collect(thread, signal_log):
    log = signal_log(
        update_available=thread.update_available,
        up_to_date=thread.up_to_date,
        error_occurred=thread.error_occurred,
    )
    thread.run()
    return log

@pytest.mark.parametrize("text,expected", [
    ("v1.2.3", "1.2.3"),
    ("1.0", "1.0"),
    ("Release v2.10.1 stable", "2.10.1"),
    ("version 3.4", "3.4"),
    ("", ""),
    (None, ""),
    ("  nightly  ", "nightly"),
    ("v7", "v7"),
])
def test_extract_version(text, expected, qapp):
    assert UpdateCheckerThread("1.0")._extract_version(text) == expected

@pytest.mark.parametrize("a,b", [("1.5", "1.5.0"), ("1.5.0.0", "1.5"), ("2", "2.0")])
def test_parse_version_ignores_trailing_zeros(a, b, qapp):
    t = UpdateCheckerThread("1.0")
    assert t._parse_version(a) == t._parse_version(b)

@pytest.mark.parametrize("newer,older", [
    ("1.10", "1.9"),
    ("1.6.1", "1.6"),
    ("2.0", "1.99.99"),
    ("1.0.1", "1"),
])
def test_parse_version_orders_numerically(newer, older, qapp):
    t = UpdateCheckerThread("1.0")
    assert t._parse_version(newer) > t._parse_version(older)

def test_parse_version_garbage_is_lowest(qapp):
    t = UpdateCheckerThread("1.0")
    assert t._parse_version("abc") == (0,)
    assert t._parse_version("1.x") == (0,)
    assert t._parse_version("") == (0,)

def test_newer_release_emits_update_available(checker_for, signal_log):
    thread = checker_for("1.6", {"tag_name": "v1.7", "name": "Prism 1.7"})
    log = run_and_collect(thread, signal_log)
    assert log["update_available"] == ["1.7"]
    assert log["up_to_date"] == [] and log["error_occurred"] == []

def test_same_version_with_extra_zero_is_up_to_date(checker_for, signal_log):
    thread = checker_for("1.6", {"tag_name": "v1.6.0"})
    log = run_and_collect(thread, signal_log)
    assert log["up_to_date"] == [()]
    assert log["update_available"] == []

def test_older_release_is_up_to_date(checker_for, signal_log):
    thread = checker_for("1.6", {"tag_name": "v1.5.9"})
    log = run_and_collect(thread, signal_log)
    assert log["up_to_date"] == [()]

def test_numeric_not_lexicographic_comparison(checker_for, signal_log):
    thread = checker_for("1.9", {"tag_name": "v1.10"})
    log = run_and_collect(thread, signal_log)
    assert log["update_available"] == ["1.10"]

def test_falls_back_to_release_name_when_tag_has_no_version(checker_for, signal_log):
    thread = checker_for("1.0", {"tag_name": "latest", "name": "Prism Desktop v2.0"})
    log = run_and_collect(thread, signal_log)
    assert log["update_available"] == ["2.0"]

def test_current_version_with_prefix_is_normalised(checker_for, signal_log):
    thread = checker_for("v1.7", {"tag_name": "1.7"})
    log = run_and_collect(thread, signal_log)
    assert log["up_to_date"] == [()]

def test_missing_tag_and_name_is_up_to_date(checker_for, signal_log):
    thread = checker_for("1.0", {})
    log = run_and_collect(thread, signal_log)
    assert log["up_to_date"] == [()]
    assert log["update_available"] == []

def test_http_error_emits_error(checker_for, signal_log):
    thread = checker_for("1.0", {"message": "rate limited"}, status=403)
    log = run_and_collect(thread, signal_log)
    assert len(log["error_occurred"]) == 1
    assert "403" in log["error_occurred"][0]
    assert log["update_available"] == []

def test_invalid_json_emits_error(checker_for, signal_log):
    thread = checker_for("1.0", body=b"<html>not json</html>")
    log = run_and_collect(thread, signal_log)
    assert len(log["error_occurred"]) == 1

def test_connection_refused_emits_error(signal_log, qapp):
    thread = UpdateCheckerThread("1.0")
    thread.repo_url = "http://127.0.0.1:1/latest"
    log = run_and_collect(thread, signal_log)
    assert len(log["error_occurred"]) == 1

def test_default_repo_url_points_at_github_api(qapp):
    assert UpdateCheckerThread("1.0").repo_url.startswith("https://api.github.com/repos/")

def test_request_goes_only_to_configured_url(checker_for, http_stub, signal_log):
    thread = checker_for("1.0", {"tag_name": "v1.0"})
    run_and_collect(thread, signal_log)
    assert [path for path, _ in http_stub.requests] == ["/latest"]
