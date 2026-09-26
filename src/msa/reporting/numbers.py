import re
from decimal import ROUND_HALF_EVEN, Decimal

from msa.contracts.report import NumberRef

_NUMBER = re.compile(r"(?<![\w.,/-])[#№]?[-+]?(?:\d+(?:[.,]\d+)?)(?![\w])")


def extract_numbers(text):
    return [
        (
            Decimal(match.group().replace(",", ".")),
            len(match.group().split(",")[-1].split(".")[-1])
            if "," in match.group() or "." in match.group()
            else 0,
        )
        for match in _NUMBER.finditer(text)
        if not match.group().startswith(("#", "№"))
    ]


def rounded(value, places):
    quantum = Decimal(1).scaleb(-places)
    return Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_EVEN)


def resolve_pointer(data, path):
    if not path.startswith("/"):
        raise KeyError(path)
    current = data
    for token in path[1:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        current = current[token]
    return current


def pointer_token(value):
    return str(value).replace("~", "~0").replace("/", "~1")


def check_refs(summary, refs, metric_tree):
    refs = [NumberRef.model_validate(ref) for ref in refs]
    errors = []
    resolved = []
    for ref in refs:
        try:
            source = resolve_pointer(metric_tree, ref.metric_path)
        except (KeyError, TypeError, IndexError):
            errors.append(f"Missing metric: {ref.metric_path}")
            continue
        if not isinstance(source, int | float) or isinstance(source, bool):
            errors.append(f"Metric is not numeric: {ref.metric_path}")
        elif rounded(source, ref.rounding) != rounded(ref.value, ref.rounding):
            errors.append(f"Number differs from metric: {ref.metric_path}")
        else:
            resolved.append(ref)
    for number, places in extract_numbers(summary):
        if not any(
            ref.rounding == places and rounded(ref.value, places) == number for ref in resolved
        ):
            errors.append(f"Untraceable number: {number}")
    return errors
