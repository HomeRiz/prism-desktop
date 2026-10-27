import ast
import json
import string
from pathlib import Path

import pytest

from core import localization_manager as lm

ROOT = Path(__file__).resolve().parent.parent
TRANSLATIONS = ROOT / "translations"
LANG_FILES = sorted(p for p in TRANSLATIONS.glob("*.json"))
OTHER_FILES = [p for p in LANG_FILES if p.stem != "en"]
LANG_IDS = [p.stem for p in OTHER_FILES]


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def placeholders(text):
    names = set()
    for _, field, _, _ in string.Formatter().parse(text):
        if field is not None:
            names.add(field)
    return names


@pytest.fixture(scope="module")
def english():
    return load(TRANSLATIONS / "en.json")


@pytest.fixture
def fresh_manager(monkeypatch):
    manager = lm._LocalizationManager()
    monkeypatch.setattr(lm, "_manager", manager)
    return manager


def test_english_reference_exists_and_is_not_empty(english):
    assert len(english) > 100


def test_every_supported_language_has_a_file():
    stems = {p.stem for p in LANG_FILES}
    assert set(lm.supported_languages()) == stems


@pytest.mark.parametrize("path", LANG_FILES, ids=lambda p: p.stem)
def test_file_is_valid_utf8_json_object_of_strings(path):
    data = load(path)
    assert isinstance(data, dict)
    assert all(isinstance(k, str) and isinstance(v, str) for k, v in data.items())


@pytest.mark.parametrize("path", LANG_FILES, ids=lambda p: p.stem)
def test_file_has_no_duplicate_keys(path):
    def reject(pairs):
        keys = [k for k, _ in pairs]
        assert len(keys) == len(set(keys)), f"duplicate keys in {path.name}"
        return dict(pairs)

    json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject)


@pytest.mark.parametrize("path", OTHER_FILES, ids=LANG_IDS)
def test_no_unknown_keys_absent_from_english(path, english):
    extra = sorted(set(load(path)) - set(english))
    assert not extra, f"{path.name} has keys missing from en.json: {extra}"


@pytest.mark.parametrize("path", LANG_FILES, ids=lambda p: p.stem)
def test_no_empty_or_blank_values(path):
    blank = sorted(k for k, v in load(path).items() if not v.strip())
    assert not blank, f"{path.name} has empty values: {blank}"


@pytest.mark.parametrize("path", OTHER_FILES, ids=LANG_IDS)
def test_placeholders_match_english_for_every_key_present(path, english):
    bad = {}
    for key, value in load(path).items():
        if key in english and placeholders(value) != placeholders(english[key]):
            bad[key] = (sorted(placeholders(english[key])), sorted(placeholders(value)))
    assert not bad, f"{path.name} placeholder mismatches: {bad}"


@pytest.mark.parametrize("path", LANG_FILES, ids=lambda p: p.stem)
def test_every_value_is_a_valid_format_string(path):
    for key, value in load(path).items():
        try:
            list(string.Formatter().parse(value))
        except ValueError as exc:
            pytest.fail(f"{path.name}:{key} is not a valid format string: {exc}")


@pytest.mark.parametrize("path", OTHER_FILES, ids=LANG_IDS)
def test_missing_keys_are_reported_by_name_and_stay_a_minority(path, english):
    missing = sorted(set(english) - set(load(path)))
    ratio = len(missing) / len(english)
    assert ratio < 0.5, f"{path.name} is missing {len(missing)} keys: {missing}"


@pytest.mark.parametrize("path", OTHER_FILES, ids=LANG_IDS)
def test_missing_keys_fall_back_to_english_at_runtime(path, english, fresh_manager):
    missing = sorted(set(english) - set(load(path)))
    fresh_manager.init(path.stem)
    for key in missing[:5]:
        assert fresh_manager.translate(key) == english[key]


@pytest.mark.parametrize("path", LANG_FILES, ids=lambda p: p.stem)
def test_translate_formats_every_placeholder_without_falling_back_to_raw(path, english, fresh_manager):
    fresh_manager.init(path.stem)
    for key in load(path):
        names = placeholders(english.get(key, load(path)[key]))
        kwargs = {name: "VAL" for name in names if name and not name.isdigit()}
        if not kwargs or any(n.isdigit() or n == "" for n in names):
            continue
        out = fresh_manager.translate(key, **kwargs)
        assert "{" not in out, f"{path.name}:{key} left a placeholder unformatted"
        assert "VAL" in out


def test_unsupported_language_falls_back_to_english(english, fresh_manager):
    fresh_manager.init("xx")
    assert fresh_manager.current_language == "en"
    key = next(iter(english))
    assert fresh_manager.translate(key) == english[key]


def test_unknown_key_returns_the_key_itself(fresh_manager):
    fresh_manager.init("en")
    assert fresh_manager.translate("no.such.key") == "no.such.key"


def test_only_hebrew_is_right_to_left(fresh_manager):
    for code in lm.supported_languages():
        fresh_manager.init(code)
        assert fresh_manager.is_rtl == (code == "he")


def literal_translation_keys():
    keys = {}
    files = [ROOT / "main.py"]
    for d in ("core", "services", "ui"):
        files.extend(sorted((ROOT / d).rglob("*.py")))
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "t"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                keys.setdefault(node.args[0].value, path.name)
    return keys


def test_every_literal_key_used_in_source_exists_in_english(english):
    keys = literal_translation_keys()
    assert len(keys) > 50
    unknown = {k: f for k, f in keys.items() if k not in english}
    assert not unknown, f"keys used in code but missing from en.json: {unknown}"
