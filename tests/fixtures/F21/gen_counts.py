"""F21 count stories (06 §5 ``gen_counts.py``): N tips, N items, and author categories, for
AC-F21-04's E254 rows at the real limits (1,000 tips, 1,000 items, 24 categories)."""


def counts_story(tips: int = 0, items: int = 0, categories: int = 0) -> str:
    """main.vns with ``tips`` tips spread over ``categories`` author categories (none: the
    default Tips category) and ``items`` items in the default Items category."""
    lines = []
    for i in range(tips):
        where = f' in "C{i % categories}"' if categories else ""
        lines.append(f'lock tip t{i} "Tip {i}"{where}')
    lines += [f'lock item i{i} "Item {i}"' for i in range(items)]
    lines += ["label start:", '    "Start."']
    return "\n".join(lines) + "\n"
