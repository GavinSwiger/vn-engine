"""Generated scripts for the flowchart graph's bounds (F20 ``06`` AC-F20-49, 05 group I;
``tests/fixtures/F20/gen_charts.py``'s chains and ladders, kept beside their test). Stdlib only,
deterministic."""


def call_chain(labels: int) -> str:
    """``start`` calls l1, each l_i calls l_(i+1), the last holds a chapter: depth ``labels``."""
    lines = ["label start:", '    "Begin."', "    call l1", '    chapter done "Done"']
    for i in range(1, labels + 1):
        lines.append(f"label l{i}:")
        if i < labels:
            lines += [f"    call l{i + 1}", "    return"]
        else:
            lines += ['    chapter deep "Deep"', "    return"]
    return "\n".join(lines) + "\n"


def jump_chain(labels: int) -> str:
    """``start`` jumps through ``labels`` labels; every 100th holds a chapter."""
    lines = ["label start:", '    "Begin."', "    jump j1"]
    for i in range(1, labels + 1):
        lines.append(f"label j{i}:")
        if i % 100 == 0:
            lines.append(f'    chapter j{i} "J{i}"')
        lines.append(f"    jump j{i + 1}" if i < labels else '    "End."')
    return "\n".join(lines) + "\n"


def mutual_recursion() -> str:
    """Two labels calling each other under conditions, between chapters."""
    return ("default n = 4\nlabel start:\n    chapter c1 \"One\"\n    call ping\n"
            "    chapter c2 \"Two\"\nlabel ping:\n    if n > 0:\n        $ n -= 1\n"
            "        call pong\n        chapter mid \"Mid\"\n    return\nlabel pong:\n"
            "    if n > 1:\n        call ping\n    return\n")


def ladder(anchors: int) -> str:
    """``anchors`` scenes, each followed by an if/else whose branches jump to the next rung
    or skip one (a ladder of crossing paths)."""
    lines = ["default v = 0", "label start:", '    "Begin."', "    jump r1"]
    for i in range(1, anchors + 1):
        lines += [f"label r{i}:", f'    flowchart scene "R{i}"']
        if i + 2 <= anchors:
            lines += ["    if v:", f"        jump r{i + 1}", "    else:", f"        jump r{i + 2}"]
        elif i < anchors:
            lines.append(f"    jump r{i + 1}")
    return "\n".join(lines) + "\n"


def many_calls(labels: int, calls: int) -> str:
    """``labels`` labels, each calling ``calls`` of the others (a scene in each)."""
    lines = ["label start:", '    "Begin."', "    call k0"]
    for i in range(labels):
        lines += [f"label k{i}:", f'    flowchart scene "K{i}"']
        for j in range(1, calls + 1):
            lines.append(f"    call k{(i + j * 7) % labels}")
        lines.append("    return")
    return "\n".join(lines) + "\n"


def statements(count: int) -> str:
    """About ``count`` statements: scenes of lines, menus, ifs, and calls (TR-F20-08)."""
    lines = ["default v = 0", "label start:", '    "Begin."', "    jump s0"]
    scenes = max(1, count // 50)
    for s in range(scenes):
        nxt = f"s{s + 1}" if s + 1 < scenes else None
        lines += [f"label s{s}:", f'    flowchart scene "Scene {s}"']
        lines += [f'    "Line {k} of scene {s}."' for k in range(30)]
        lines += ["    menu:", '        "Left":', '            $ v += 1',
                  '            "Left it is."', '        "Right":', '            "Right."']
        chapter = f'        chapter c{s} "C{s}"' if s < 900 else '        "No chapter."'
        lines += ["    if v > 3:", chapter, "    else:",
                  '        "Not yet."', "    call helper"]
        lines.append(f"    jump {nxt}" if nxt else '    ending last "Last"')
    lines += ["label helper:", '    "A helper line."', "    return"]
    return "\n".join(lines) + "\n"
