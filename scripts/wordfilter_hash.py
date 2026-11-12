"""Print the hash line for a word to add to the review word filter.

    python scripts/wordfilter_hash.py          # then type words, one per line (Ctrl+Z / Ctrl+D to finish)
    python scripts/wordfilter_hash.py < words.txt

Paste each printed line into BLOCKED in lambdas/src/cwtch/wordfilter.py. Words
are read from the keyboard (not the command line) so they don't end up in your
shell history. Only add whole words: the filter never matches parts of words.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lambdas" / "src"))

from cwtch import wordfilter  # noqa: E402  (needs the path above)


def main() -> None:
    for line in sys.stdin:
        word = wordfilter.fold(line.strip())
        if word:
            known = " (already blocked)" if wordfilter.word_hash(word) in wordfilter.BLOCKED else ""
            print(f'    "{wordfilter.word_hash(word)}",{known}')


if __name__ == "__main__":
    main()
