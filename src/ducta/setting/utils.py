from typing import Any, Dict


def deep_merge_dicts(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge ``override`` onto ``base``, returning a new dict.

    Nested dicts are merged key-by-key; any non-dict value in ``override``
    replaces the corresponding value in ``base``. Neither input is mutted.

    Two sentinels let a child/env config express things a plain merge
    can't:

    - ``key: null`` in ``override`` removes ``key`` from the result entirely
      (an empty dict/``{}`` is not a substitute for this — merging ``{}``
      onto an existing nested dict is a no-op, so a child config had no way
      to say "clear this whole section" the base declared).
    - ``key: {"__reset__": true, ...}`` replaces ``base[key]`` outright with
      the rest of that dict (the ``__reset__`` marker itself is stripped),
      instead of merging onto whatever ``base[key]`` already had.
    """
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
