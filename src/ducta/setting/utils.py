from typing import Any, Dict


def deep_merge_dicts(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge ``override`` onto ``base``, returning a new dict."""
    result = dict(base)
    for key, value in override.items():
        if value is None:
            result.pop(key, None)
            continue
        if isinstance(value, dict) and value.get("__reset__") is True:
            result[key] = {k: v for k, v in value.items() if k != "__reset__"}
            continue
        existing = result.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            result[key] = deep_merge_dicts(existing, value)
        else:
            result[key] = value
    return result
