from __future__ import annotations


def normalize_temperature_unit(unit) -> str | None:
    if unit is None:
        return None

    normalized = str(unit).strip().upper().replace("°", "")
    if normalized in ("C", "CELSIUS"):
        return "C"
    if normalized in ("F", "FAHRENHEIT"):
        return "F"
    return None


def preference_to_unit(preference, fallback=None) -> str | None:
    normalized = normalize_temperature_unit(preference)
    if normalized:
        return normalized

    pref = str(preference or "").strip().lower()
    if pref == "celsius":
        return "C"
    if pref == "fahrenheit":
        return "F"
    return normalize_temperature_unit(fallback)


def unit_suffix(unit) -> str:
    normalized = normalize_temperature_unit(unit)
    return f"°{normalized}" if normalized else "°"


def is_temperature_unit(unit) -> bool:
    return normalize_temperature_unit(unit) is not None


def is_temperature_entity(attributes: dict | None) -> bool:
    attrs = attributes or {}
    return (
        str(attrs.get("device_class", "")).lower() == "temperature"
        or is_temperature_unit(attrs.get("unit_of_measurement"))
        or is_temperature_unit(attrs.get("temperature_unit"))
    )


def convert_temperature(value, from_unit, to_unit):
    from_normalized = normalize_temperature_unit(from_unit)
    to_normalized = normalize_temperature_unit(to_unit)

    if value in (None, "", "--"):
        return None

    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None

    if not from_normalized or not to_normalized or from_normalized == to_normalized:
        return numeric

    if from_normalized == "C" and to_normalized == "F":
        return (numeric * 9.0 / 5.0) + 32.0
    if from_normalized == "F" and to_normalized == "C":
        return (numeric - 32.0) * 5.0 / 9.0
    return numeric


def convert_temperature_delta(value, from_unit, to_unit):
    from_normalized = normalize_temperature_unit(from_unit)
    to_normalized = normalize_temperature_unit(to_unit)

    if value in (None, "", "--"):
        return None

    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None

    if not from_normalized or not to_normalized or from_normalized == to_normalized:
        return numeric

    if from_normalized == "C" and to_normalized == "F":
        return numeric * 9.0 / 5.0
    if from_normalized == "F" and to_normalized == "C":
        return numeric * 5.0 / 9.0
    return numeric


def format_temperature(value, source_unit, preferred_unit=None, precision: int = 1, fallback: str = "--") -> str:
    target_unit = preference_to_unit(preferred_unit, fallback=source_unit)
    converted = convert_temperature(value, source_unit, target_unit)
    if converted is None or not target_unit:
        return f"{fallback}{unit_suffix(target_unit)}" if target_unit else fallback

    formatted = f"{converted:.{precision}f}"
    if "." in formatted:
        # Drop trailing zeros only ("20.0" -> "20"); a blanket replace(".0", "")
        # also ate digits inside values like "20.05".
        formatted = formatted.rstrip("0").rstrip(".")
    if formatted in ("-0", ""):
        formatted = "0"
    return f"{formatted}{unit_suffix(target_unit)}"
