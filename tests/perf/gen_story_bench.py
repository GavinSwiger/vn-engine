"""F46's story text for the Studio budgets (``06-acceptance.md`` §5, AC-F46-46; ``04`` §10).

``story(size)`` is one ``.vns`` text of about ``size`` bytes: labels of ``scene_lines`` lines
(narration, dialogue, a ``$`` line, a menu every few scenes), each ending in a ``jump`` to the
next, so every chunk parses and links. Built in memory, deterministic, never written to the
repository. Step 1a uses the 800 KB and 16 MB texts; later steps add the 2,000-statement
scene, 1,500 linked labels and the 1,000-file rename set here.
"""

KB = 1024
MB = 1024 * KB


def scene(n: int, lines: int) -> list[str]:
    """Label ``s<n>``: ``lines`` lines after its label line, then a blank line."""
    out = [f"label s{n}:"]
    body = lines - 1
    if n % 4 == 0:
        out += ["    menu:", f'        "Go on to scene {n + 1}":', f"            jump s{n + 1}",
                '        "Stay a while":', "            $ pass"]
        body -= 5
    for k in range(max(0, body)):
        if k % 3 == 0:
            out.append(f'    hana "Line {k} of scene {n}, under the paper lanterns."')
        elif k % 3 == 1:
            out.append(f'    "The festival went on, line {k}, and the river ran past."')
        else:
            out.append(f"    $ coins = {k} + {n}")
    out += [f"    jump s{n + 1}", ""]
    return out


def story(size: int, *, scene_lines: int = 40) -> str:
    """About ``size`` bytes of script, ending in a label every jump can reach."""
    head = ['define hana = Character("Hana")', "default coins = 0", "",
            "label start:", "    jump s0", ""]
    lines = list(head)
    total = sum(len(line) + 1 for line in lines)
    n = 0
    while total < size:
        part = scene(n, scene_lines)
        total += sum(len(line) + 1 for line in part)
        lines += part
        n += 1
    lines += [f"label s{n}:", "    return", ""]
    return "\n".join(lines)
