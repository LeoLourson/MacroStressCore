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
