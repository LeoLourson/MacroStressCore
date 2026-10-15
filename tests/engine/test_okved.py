"""msa.engine.okved: okved_covers() — digits shared by two codes on one OKVED branch."""

import pytest

from msa.engine.okved import okved_covers


@pytest.mark.parametrize(
    "node,code,expected",
    [
        ("23.61", "23.61", 4),
        ("23", "23.61", 2),
        ("23.61", "23", 2),
        ("23.61", "23.51", 0),
        ("23.61", "23.61.1", 4),
        ("23.6", "23.61", 3),
        ("23.61", "24.10", 0),
        ("2", "23.61", 0),
    ],
)
def test_okved_covers(node, code, expected):
    assert okved_covers(node, code) == expected
