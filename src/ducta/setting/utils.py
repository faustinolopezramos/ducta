import copy
from typing import Any, Dict, Tuple


def deep_merge(base: Any, override: Any) -> Any:
    """``override`` over ``base``: mappings merge, scalars and lists replace.

    What comes from ``override`` is copied; keys only ``base`` has are carried over as
    they are. Neither input is modified.
    """
    if isinstance(base, dict) and isinstance(override, dict):
        merged = dict(base)
        for key, value in override.items():
            merged[key] = deep_merge(base[key], value) if key in base else copy.deepcopy(value)
        return merged
    return copy.deepcopy(override)


def leaves(value: Any, prefix: Tuple[str, ...] = ()) -> Dict[Tuple[str, ...], Any]:
    """Every leaf of a nested mapping, keyed by its path. An empty mapping is a leaf."""
    if isinstance(value, dict) and value:
        out: Dict[Tuple[str, ...], Any] = {}
        for key, child in value.items():
            out.update(leaves(child, (*prefix, str(key))))
        return out
    return {prefix: value}
