"""F20's perf stories (``06-acceptance.md`` §5 ``perf/gen_flowchart.py``; AC-F20-68): a story
whose flowchart has an exact number of nodes, and the 50,000-statement story (TR-F20-08,
``tests/script/flowgraph_gen.statements``). Stdlib only, deterministic.

``chart_story(nodes)``: a chain of marked scenes; every third scene ends in a branching menu
(a choice node whose two choices jump one and two scenes ahead, so paths cross), every tenth
holds a chapter, and the last jumps to one ending. The start node comes from the line before
the first scene. Node count = 1 (start) + scenes + menus + chapters + 1 (the ending).
"""

from tests.script.flowgraph_gen import statements


def _count(scenes: int) -> int:
    menus = sum(1 for i in range(scenes) if i % 3 == 0 and i + 2 < scenes)
    chapters = sum(1 for i in range(scenes) if i % 10 == 5)
    return 1 + scenes + menus + chapters + 1


def chart_story(nodes: int) -> str:
    """A story whose flowchart (``menus = "branching"``) has exactly ``nodes`` nodes (≥ 3)."""
    scenes = 1
    while _count(scenes) < nodes:
        scenes += 1
    extra = _count(scenes) - nodes           # past the target: drop that many chapters
    lines = ["label start:", '    "The festival begins."', "    jump s0"]
    for i in range(scenes):
        lines += [f"label s{i}:", f'    flowchart scene "Scene {i}"', f'    "Line of scene {i}."']
        if i % 10 == 5:
            if extra > 0:
                extra -= 1
            else:
                lines.append(f'    chapter c{i} "Chapter {i}" "Part {i}"')
        nxt = f"s{i + 1}" if i + 1 < scenes else "finale"
        if i % 3 == 0 and i + 2 < scenes:
            lines += ["    menu:", f'        "Go on to {i + 1}":', f"            jump {nxt}",
                      f'        "Skip to {i + 2}":', f"            jump s{i + 2}"]
        else:
            lines.append(f"    jump {nxt}")
    lines += ["label finale:", '    "The lanterns go out."', '    ending last "The End" "Last"']
    return "\n".join(lines) + "\n"


__all__ = ["chart_story", "statements"]
