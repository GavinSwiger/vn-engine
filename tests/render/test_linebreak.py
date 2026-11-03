"""F43 P8: CJK line breaks (``render/linebreak``; 04 §7.5, PR-F43-14). AC-F43-22."""

import pytest

from engine.core.graphemes import graphemes
from engine.render.linebreak import is_ideographic, segments, soft_breaks

# --- AC-F43-22: CJK breaks between characters, not before closing or after opening
# punctuation; Latin words whole --------------------------------------------------------------

LINE_BREAKS = [
    # text, the pieces a line may break between ("".join gives the text back)
    ("日本語", ["日", "本", "語"]),                                          # Han
    ("ひらがなカタカナ", ["ひ", "ら", "が", "な", "カ", "タ", "カ", "ナ"]),     # kana
    ("한국어 텍스트", ["한", "국", "어 ", "텍", "스", "트"]),                   # Hangul
    ("「こんにちは」と言った。",                                                # brackets, small kana,
     ["「こ", "ん", "に", "ち", "は」", "と", "言っ", "た。"]),                  # full stop
    ("（笑）、ね！？", ["（笑）、", "ね！？"]),                                   # PR-F43-14's lists
    ("『本』【注】〈a〉《b》", ["『本』", "【注】", "〈a〉", "《b》"]),
    ("コーヒー・ティー：はい；", ["コー", "ヒー・", "ティー：", "は", "い；"]),    # ー and ・：；
    ("ぁぃぅぇぉゃゅょゎ", ["ぁぃぅぇぉゃゅょゎ"]),                            # small kana only
    ("ァィゥェォャュョッ", ["ァィゥェォャュョッ"]),
    ("日本Englishです", ["日", "本", "English", "で", "す"]),                 # Latin word whole
    ("Hello world, again.", ["Hello ", "world, ", "again."]),               # Latin: spaces only
    ("“Hi” he said", ["“Hi” ", "he ", "said"]),
    ("価格は$100。", ["価", "格", "は", "$100。"]),                         # ASCII no-end/no-start
    ("「Yes.」です", ["「Yes.」", "で", "す"]),
    ("……と言った", ["……", "と", "言っ", "た"]),                             # inseparable marks
    ("日本　語", ["日", "本　", "語"]),                                      # ideographic space
    ("日 本", ["日 本"]),                                           # no-break space
    ("ﾃｽﾄｰ", ["ﾃ", "ｽ", "ﾄｰ"]),                                              # halfwidth kana
    ("ｶﾞ゙", ["ｶﾞ゙"]),                                                       # one grapheme
    ("𠀋𠀋", ["𠀋", "𠀋"]),                                                     # extension B
    ("", []),
]


@pytest.mark.parametrize("text, pieces", LINE_BREAKS)
def test_ac_f43_22_cjk_line_breaks(text, pieces):
    assert segments(text) == pieces
    assert "".join(pieces) == text
    units = graphemes(text)
    breaks = soft_breaks(units)
    assert all(0 < i < len(units) for i in breaks)
    if not any(is_ideographic(g) for g in units):
        assert breaks == frozenset()                     # Latin layout is unchanged
