def okved_depth(code, sector):
    code, sector = code.replace(".", ""), sector.replace(".", "")
    return max(
        (
            size
            for size in (4, 3, 2)
            if len(code) >= size and len(sector) >= size and code[:size] == sector[:size]
        ),
        default=0,
    )


def okved_covers(node, code):
    """Digits shared by a graph's sector ``node`` and an activity ``code`` on one branch.

    The codes lie on one branch of the OKVED hierarchy when one is a prefix of the other,
    compared up to the class (4 digits): the section "23" covers 23.61 and 23.61 covers
    23.61.1, but 23.61 does not cover 23.51. ``0`` when they lie on different branches.
    """
    node, code = node.replace(".", "")[:4], code.replace(".", "")[:4]
    shared = min(len(node), len(code))
    return shared if shared >= 2 and node[:shared] == code[:shared] else 0
