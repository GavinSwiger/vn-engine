"""Writes ``textfx_golden.toml`` beside this file (F29 06 §5, AC-F29-08).

An independent transcription of F29 ``04-technical.md`` §7.1 and §7.3 and ``07`` I-3's
``line_seed``: it imports nothing of ``engine``. Run once by hand and review the diff
(``python -I tests/fixtures/F29/gen_textfx_golden.py``); tests never regenerate the table.
"""

import json
import math
from pathlib import Path

M = 0xFFFFFFFF


def mix32(x):
    x &= M
    x ^= x >> 16
    x = (x * 0x7FEB352D) & M
    x ^= x >> 15
    x = (x * 0x846CA68B) & M
    x ^= x >> 16
    return x


def h(i, step, salt, seed):
    return mix32(mix32(mix32(i ^ 0x5BD1E995) + step) + (salt << 20 | seed))


def u(x):
    return (x & 0xFFFF) / 65536


def v(x):
    return (x >> 16) / 65536


def shake_unit(i, t, seed):
    x = h(i, math.floor(t / 0.05), 1, seed)
    return 2 * u(x) - 1, 2 * v(x) - 1


def wave_unit(i, t):
    return math.sin(2 * math.pi * t / 1.0 + 0.6 * i)


def glitch_pick(i, t, seed, p, still):
    step = 0 if still else math.floor((t + 0.12 * u(h(i, 0, 2, seed))) / 0.12)
    x = h(i, step, 3, seed)
    return int(v(x) * 20) if u(x) < p else -1


def line_seed(sid):
    x = 0x811C9DC5
    for byte in sid.encode("utf-8", "surrogatepass"):
        x = mix32(x ^ byte)
    return x & 0xFFFFF


INDICES = [0, 1, 2, 45, 203, 2_399, 2**31, 2**32 - 1]
TIMES = [0.0, 0.0499, 0.05, 0.11999, 0.12, 1.0, 59.99, 3600.0]
SEEDS = [0, 1, 13]
PS = [0.1, 0.25, 0.5]
SIDS = ["", "a", "b", "start/e6db5068f584", "start/26021b18b2ed", "start/66739b0087b9",
        "chapter_2/0ff871ab010a", "start/e6db5068f585", "ハナ/祭り", "café/😀",
        "label/" + "x" * 1018, "z" * 1024]


def rows():
    out = {"mix32": [{"x": x, "out": mix32(x)} for x in
                     [0, 1, 2, 0xFFFFFFFF, 2**32, 45, 203, 2_399, 2**31, 0x5BD1E995,
                      123_456_789, 2**40 + 7]],
           "shake_unit": [], "wave_unit": [], "glitch_pick": [],
           "line_seed": [{"sid": sid, "out": line_seed(sid)} for sid in SIDS]}
    for k in range(24):
        i, t, seed = INDICES[k % 8], TIMES[(k * 3) % 8], SEEDS[k % 3]
        ux, uy = shake_unit(i, t, seed)
        out["shake_unit"].append({"index": i, "t": t, "seed": seed, "ux": ux, "uy": uy})
        out["wave_unit"].append({"index": i, "t": TIMES[(k * 5) % 8], "out": None})
        p, still = PS[(k // 3) % 3], k % 2 == 1
        out["glitch_pick"].append({"index": i, "t": t, "seed": seed, "p": p, "still": still,
                                   "out": glitch_pick(i, t, seed, p, still)})
    for row in out["wave_unit"]:
        row["out"] = wave_unit(row["index"], row["t"])
    return out


def value(x):
    if isinstance(x, bool):
        return "true" if x else "false"
    if isinstance(x, str):
        return json.dumps(x, ensure_ascii=False)
    return repr(x)


def main():
    lines = ["# F29 AC-F29-08 golden table: written by gen_textfx_golden.py, never by tests.", ""]
    for name, table in rows().items():
        for row in table:
            lines.append(f"[[{name}]]")
            lines += [f"{key} = {value(x)}" for key, x in row.items()]
            lines.append("")
    path = Path(__file__).with_name("textfx_golden.toml")
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
