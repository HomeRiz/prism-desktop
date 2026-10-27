import json
import types

import pytest

from core import localization_manager as lm


@pytest.fixture
def translations(tmp_path, monkeypatch):
    root = tmp_path / "res"
    (root / "translations").mkdir(parents=True)

    def write(lang, data):
        (root / "translations" / f"{lang}.json").write_text(json.dumps(data), encoding="utf-8")

    monkeypatch.setattr(lm, "get_resource_path", lambda rel: root / rel)
    write("en", {"hello": "Hello", "only_en": "English only", "fmt": "Hi {name}", "empty": "x"})
    write("fr", {"hello": "Bonjour", "fmt": "Salut {name}", "empty": ""})
    return types.SimpleNamespace(root=root, write=write)


@pytest.fixture
def manager(translations):
    return lm._LocalizationManager()


def test_translate_before_init_returns_key(manager):
    assert manager.translate("hello") == "hello"


def test_english_loads_by_default(manager):
    manager.init()
    assert manager.translate("hello") == "Hello"
    assert manager.current_language == "en"
    assert manager.is_rtl is False


def test_selected_language_overrides_english(manager):
    manager.init("fr")
    assert manager.translate("hello") == "Bonjour"
    assert manager.current_language == "fr"


def test_missing_key_falls_back_to_english(manager):
    manager.init("fr")
    assert manager.translate("only_en") == "English only"


def test_empty_translation_falls_back_to_english(manager):
    manager.init("fr")
    assert manager.translate("empty") == "x"


def test_unknown_key_returns_key_itself(manager):
    manager.init("fr")
    assert manager.translate("no.such.key") == "no.such.key"


def test_unsupported_language_falls_back_to_english(manager):
    manager.init("xx")
    assert manager.current_language == "en"
    assert manager.translate("hello") == "Hello"


def test_supported_language_with_missing_file_uses_english(manager):
    manager.init("de")
    assert manager.current_language == "de"
    assert manager.translate("hello") == "Hello"


def test_malformed_language_file_uses_english(manager, translations):
    (translations.root / "translations" / "fr.json").write_text("{broken", encoding="utf-8")
    manager.init("fr")
    assert manager.translate("hello") == "Hello"


def test_missing_english_file_returns_keys(manager, translations):
    (translations.root / "translations" / "en.json").unlink()
    manager.init("en")
    assert manager.translate("hello") == "hello"


def test_format_arguments_are_substituted(manager):
    manager.init("fr")
    assert manager.translate("fmt", name="Zoe") == "Salut Zoe"


def test_missing_format_argument_returns_raw_string(manager):
    manager.init("en")
    assert manager.translate("fmt", other="x") == "Hi {name}"


def test_bad_format_spec_returns_raw_string(manager, translations):
    translations.write("en", {"bad": "{0"})
    manager.init("en")
    assert manager.translate("bad", a=1) == "{0"


def test_format_not_applied_without_kwargs(manager):
    manager.init("en")
    assert manager.translate("fmt") == "Hi {name}"


def test_rtl_only_for_hebrew(manager):
    manager.init("he")
    assert manager.is_rtl is True
    manager.init("en")
    assert manager.is_rtl is False


def test_supported_languages_returns_copy(manager):
    langs = manager.supported_languages()
    langs["xx"] = "Fake"
    assert "xx" not in manager.supported_languages()
    assert manager.supported_languages()["en"] == "English"


def test_module_level_helpers_delegate_to_manager(translations):
    try:
        lm.init_localization("fr")
        assert lm.t("hello") == "Bonjour"
        assert lm.t("fmt", name="A") == "Salut A"
        assert lm.current_language() == "fr"
        assert lm.is_rtl() is False
        assert "fr" in lm.supported_languages()
    finally:
        lm.init_localization("en")


def test_every_supported_language_has_a_translation_file_with_valid_json():
    from core.utils import get_resource_path

    for code in lm._SUPPORTED_LANGUAGES:
        path = get_resource_path(f"translations/{code}.json")
        assert path.is_file(), code
        assert isinstance(json.loads(path.read_text(encoding="utf-8")), dict)


def test_real_english_catalogue_resolves_a_known_key():
    manager = lm._LocalizationManager()
    manager.init("en")
    assert manager.translate("settings.title") == "Settings"


def test_real_non_english_keys_exist_in_english_catalogue():
    from core.utils import get_resource_path

    english = set(json.loads(get_resource_path("translations/en.json").read_text(encoding="utf-8")))
    for code in ("fr", "de"):
        keys = set(json.loads(get_resource_path(f"translations/{code}.json").read_text(encoding="utf-8")))
        assert keys - english == set(), code
