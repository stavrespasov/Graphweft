"""Decode finite, unambiguous GraphWeft JSON documents."""

import json
from math import isfinite

MAX_JSON_DEPTH = 64


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key {key!r}.")
        result[key] = value
    return result


def _finite_number(token):
    value = float(token)
    if not isfinite(value):
        raise ValueError("JSON numbers must be finite.")
    return value


def decode_json(contents):
    try:
        document = json.loads(contents, object_pairs_hook=_unique_object,
                              parse_float=_finite_number, parse_constant=_finite_number)
    except RecursionError:
        raise ValueError("The JSON is nested too deeply.") from None

    # Python releases differ in how deeply their built-in decoder can parse.
    pending = [(document, 1)] if isinstance(document, (dict, list)) else []
    while pending:
        value, depth = pending.pop()
        if depth > MAX_JSON_DEPTH:
            raise ValueError("The JSON is nested too deeply.")
        children = value.values() if isinstance(value, dict) else value
        pending.extend((child, depth + 1) for child in children if isinstance(child, (dict, list)))
    return document
