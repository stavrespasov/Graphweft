"""Decode finite, unambiguous GraphWeft JSON documents."""

import json
from math import isfinite


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
        return json.loads(contents, object_pairs_hook=_unique_object,
                          parse_float=_finite_number, parse_constant=_finite_number)
    except RecursionError:
        raise ValueError("The JSON is nested too deeply.") from None
