from collections.abc import Callable
from io import BytesIO

from app.schemas import ParseResult

ParserFn = Callable[[BytesIO, str], ParseResult]

_REGISTRY: dict[tuple[str, str], ParserFn] = {}


def register(bank_code: str, file_type: str) -> Callable[[ParserFn], ParserFn]:
    key = (bank_code.lower(), file_type.lower())

    def deco(fn: ParserFn) -> ParserFn:
        _REGISTRY[key] = fn
        return fn

    return deco


def get_parser(bank_code: str, file_type: str) -> ParserFn | None:
    key = (bank_code.lower(), file_type.lower())
    if key in _REGISTRY:
        return _REGISTRY[key]
    # Fallback: generic parser for this file type
    generic_key = ("generic", file_type.lower())
    return _REGISTRY.get(generic_key)


def list_registered_keys() -> list[tuple[str, str]]:
    return sorted(_REGISTRY.keys())
