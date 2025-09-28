from typing import TypeGuard, Any


def is_str_any_dict(value: Any) -> TypeGuard[dict[str, Any]]:
    if not isinstance(value, dict):
        return False
    return all(isinstance(key, str) for key in value.keys())

def is_any_list(value: Any) -> TypeGuard[list[Any]]:
    return isinstance(value, list)
