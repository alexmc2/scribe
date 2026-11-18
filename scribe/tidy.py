"""Tidying transcribed speech: no "um" or "uh", no stutters, no "..." pauses.

Plain rules, no language model, so it's instant and only ever removes things:
the words that remain are the ones Whisper heard. The cleaned text is also
what Whisper is shown as context for the next phrase, and as it copies the
style of its context, that keeps it from writing more ums and pauses.
"""

from __future__ import annotations

import re

# Hesitation sounds. Not "hmm", "mm-hmm" or "uh-huh", which can mean something.
_FILLER = re.compile(r"(?:u+m+|u+h+m*|e+r+m+|er|e+h+m+)", re.IGNORECASE)

# Punctuation Whisper puts after a word; "..." (or "…") is how it writes a pause.
_TRAIL = re.compile(r"(?:\.\.\.|…|[.,!?;:])+$")
_SENTENCE_END = (".", "?", "!")
_PAUSE = ("...", "…")

# Words that can't be a name, so when Whisper capitalises one after a pause
# ("feeling... Particularly excited"), it's safe to join the sentence back up.
_COMMON = frozenset(
    """
    a an the and but or nor so yet because if then than that this these those
    there there's here it it's its they they're them their we we're our you
    you're your he she his her him me my us to of in on at for with from by
    about into onto over under after before between through as like just
    really very quite also even still only maybe perhaps actually basically
    probably particularly especially definitely is are was were be been being
    am do does did doing done have has had having can could would should might
    must not no what when where which who why how all some any more most much
    many other another each every both either neither one two three four five
    get got getting go going make making see think know want need use using
    able kind sort thing things something anything everything nothing now too
    again already though although while until unless since whether way lot
    bit sure okay
    """.split()
)

# After one of these the sentence must go on ("The... Problem is"), so the next
# word is joined on whatever it is, unless it's one of the names and terms.
_LEADS_ON = frozenset(
    "the a an my your our their his her its this that these those some any every each very quite really too".split()
)

# "I" and its contractions start a new thought after a pause more often than not.
_I_FORMS = frozenset({"i", "i'm", "i'll", "i've", "i'd"})

# Words a sentence doesn't end on, so a pause after one never becomes a full stop.
_CARRIES_ON = _LEADS_ON | frozenset(
    "and but or so because that if when while to of in on at for with from by as than is are was were am be".split()
)

# Whisper writes a pause as "..." after a word, before the next one, or both
# ("another... ...application"). Any run of them counts as one pause.
_DOTS = r"(?:\.{2,}|…)"
_PAUSE_RUN = re.compile(rf"\s*{_DOTS}(?:\s*{_DOTS})*\s*")


def _one_pause(match: re.Match) -> str:
    before = match.string[: match.start()].rstrip()
    if not before or not match.string[match.end() :].strip():
        return " "  # a pause at the very start or end says nothing
    return " " if before.endswith((".", "?", "!", ",", ";", ":")) else "... "


def _split(token: str) -> tuple[str, str]:
    """A word and the punctuation after it: "excited..." -> ("excited", "...")."""
    match = _TRAIL.search(token)
    return (token[: match.start()], match.group()) if match else (token, "")


def _bare(word: str) -> str:
    return word.strip("\"'()[]“”‘’").lower()


def _is_filler(word: str) -> bool:
    return bool(_FILLER.fullmatch(_bare(word)))


def _ends_sentence(trail: str) -> bool:
    return trail.endswith(_SENTENCE_END) and not trail.endswith(_PAUSE)


def _ends_pause(trail: str) -> bool:
    return trail.endswith(_PAUSE)


def _drop_fillers(words: list[list[str]]) -> list[list[str]]:
    kept: list[list[str]] = []
    for word, trail in words:
        if not _is_filler(word):
            kept.append([word, trail])
            continue
        if not kept:
            continue
        before = kept[-1]
        if before[1] == ",":
            # "do, um, by" -> "do, by"; "and, uh... see" -> "and see"
            before[1] = "," if trail == "," else trail if _ends_sentence(trail) else ""
        elif _ends_sentence(trail) and not before[1]:
            before[1] = trail  # "finish this um." -> "finish this."
    return kept


def _drop_repeats(words: list[list[str]]) -> list[list[str]]:
    """Collapse stutters across a pause: "It's... It's okay" -> "It's okay"."""
    changed = True
    while changed:
        changed = False
        for size in (1, 2, 3):
            for i in range(len(words) - 2 * size + 1):
                first, second = words[i : i + size], words[i + size : i + 2 * size]
                if not _ends_pause(first[-1][1]):
                    continue
                if [_bare(w) for w, _ in first] != [_bare(w) for w, _ in second]:
                    continue
                # Keep the first (its capitals are right), with the second's ending.
                first[-1][1] = second[-1][1]
                del words[i + size : i + 2 * size]
                changed = True
                break
            if changed:
                break
    return words


def _join_pauses(words: list[list[str]], names: frozenset[str]) -> None:
    """Take out every "..." pause, joining the words either side of it."""
    for here, after in zip(words, words[1:]):
        if not _ends_pause(here[1]):
            continue
        word = after[0]
        bare = _bare(word)
        here[1] = ""
        if not word or word[0].islower():
            continue
        if bare in _I_FORMS:
            # Usually a new thought: "follows your finger... I'll send it".
            if _bare(here[0]) not in _CARRIES_ON:
                here[1] = "."
        elif bare in names or (len(word) > 1 and word.isupper()):
            pass  # a name or an acronym keeps its capitals
        elif bare in _COMMON or _bare(here[0]) in _LEADS_ON:
            after[0] = word[0].lower() + word[1:]
    if words and _ends_pause(words[-1][1]):
        words[-1][1] = ""


def _capitalise_sentences(words: list[list[str]], first: bool) -> None:
    starts = [first] + [_ends_sentence(trail) for _, trail in words[:-1]]
    for entry, start in zip(words, starts):
        word = entry[0]
        if start and word and word[0].islower():
            entry[0] = word[0].upper() + word[1:]


def names_in(vocabulary: str) -> frozenset[str]:
    """The words of the "Names and terms" setting, which keep their capitals."""
    return frozenset(_bare(word) for word in re.split(r"[\s,;]+", vocabulary) if word)


def tidy_speech(text: str, names: frozenset[str] = frozenset()) -> str:
    """Remove fillers, stutters and needless pauses from transcribed speech.

    ``names`` (lowercase, see :func:`names_in`) are never lowercased. Text that
    starts with a pause ("...by turning it") carries on an earlier sentence, so
    its first word isn't capitalised.
    """
    carries_on = bool(re.match(rf"\s*{_DOTS}", text))
    text = _PAUSE_RUN.sub(_one_pause, text)
    words = [list(_split(token)) for token in text.split()]
    words = _drop_fillers(words)
    words = _drop_repeats(words)
    _join_pauses(words, names)
    _capitalise_sentences(words, first=not carries_on)
    text = " ".join(f"{word}{trail}" for word, trail in words if word or trail)
    return text.strip(" ,;:")
