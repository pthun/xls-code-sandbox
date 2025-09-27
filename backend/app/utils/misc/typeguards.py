from typing import TypeGuard, Any, cast

def is_str_any_dict(value: Any) -> TypeGuard[dict[str, Any]]:
    return isinstance(value, dict) and all(isinstance(k, str) for k in cast(dict[Any, Any], value))

def is_any_list(value: Any) -> TypeGuard[list[Any]]:
    return isinstance(value, list)
