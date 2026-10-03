"""Kaynaktan calistirma Python 3.10+ destekler (README, Calistir.bat).

Python 3.12 (PEP 701) f-string ifadelerinin satir asmasina, ayni tirnagi
yeniden kullanmasina, ters bolu ve yorum icermesine izin verir; 3.10/3.11 bu
dosyayi hic yukleyemez ("unterminated string literal"). Gelistirme ortami
3.12+ oldugunda derleme bu hatayi gostermez, bu yuzden tokenizer ile taranir.
"""
import pathlib
import sys
import tokenize
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FSTRING_START = getattr(tokenize, "FSTRING_START", None)


def _pep701_only_constructs(path):
    problems = []
    with open(path, "rb") as fh:
        tokens = list(tokenize.tokenize(fh.readline))
    stack = []  # (tirnak, f-string baslangic satiri)
    for tok in tokens:
        if tok.type == FSTRING_START:
            body = tok.string.lstrip("rRfFbB")
            quote = body[:3] if body[:3] in ('"""', "'''") else body[0]
            if stack and len(stack[-1][0]) == 1 and quote[0] == stack[-1][0]:
                problems.append((tok.start[0], "ic ice ayni tirnakli f-string"))
            stack.append((quote, tok.start[0]))
        elif tok.type == tokenize.FSTRING_END:
            stack.pop()
        elif stack:
            quote, line = stack[-1]
            single_line = len(quote) == 1
            if tok.type == tokenize.STRING:
                if single_line and tok.string.lstrip("rRuUbB")[0] == quote:
                    problems.append((tok.start[0], "ifadede ayni tirnak"))
                if "\\" in tok.string:
                    problems.append((tok.start[0], "ifadede ters bolu"))
            if tok.type == tokenize.COMMENT:
                problems.append((tok.start[0], "ifadede yorum"))
            if (single_line and tok.type != tokenize.FSTRING_MIDDLE
                    and tok.end[0] != line):
                problems.append((tok.start[0], "tek satirlik f-string satir asiyor"))
    return problems


@unittest.skipIf(FSTRING_START is None, "3.12 oncesi derleyici bunu zaten reddeder")
class Python310Syntax(unittest.TestCase):
    def test_sources_avoid_pep701_only_fstrings(self):
        found = []
        for folder in ("app", "tests", "scripts", "packaging"):
            for path in sorted((ROOT / folder).rglob("*.py")):
                for line, reason in _pep701_only_constructs(path):
                    found.append(f"{path.relative_to(ROOT)}:{line}: {reason}")
        self.assertEqual(found, [], "\n".join(found))

    def test_detector_catches_the_reported_regression(self):
        sample = ROOT / "tests" / "_pep701_sample.tmp"
        sample.write_text(
            "x = f\"{a or 'b '\n"
            "       'c'}\"\n", encoding="utf-8")
        try:
            self.assertTrue(_pep701_only_constructs(sample))
        finally:
            sample.unlink()


if __name__ == "__main__":
    unittest.main()
