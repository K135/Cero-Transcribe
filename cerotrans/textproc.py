"""Post-process transcripts: junk filter, light formatting, vocabulary fixes."""

from __future__ import annotations

import re

_SPECIAL_TOKEN_RE = re.compile(
    r"\[[^\]]*\]|\([^)]*speaking in foreign language[^)]*\)|"
    r"<\|[^|>]+\|>",
    re.IGNORECASE,
)

_JUNK_EXACT = {
    "",
    ".",
    "..",
    "...",
    "?",
    "!",
    "you",
    "the",
    "a",
    "thank you",
    "thank you.",
    "thanks",
    "thanks.",
    "thanks for watching",
    "thanks for watching.",
    "thanks for watching!",
    "please subscribe",
    "please subscribe.",
    "subscribe",
    "bye",
    "bye.",
    "okay",
    "ok",
    "hmm",
    "uh",
    "um",
    "ah",
    "oh",
    "yeah",
    "subtitle",
    "subtitles",
    "subtitles by the amara.org community",
    "blank_audio",
    "blank audio",
    "music",
    "applause",
    "laughter",
    "silence",
    "inaudible",
}

_JUNK_CONTAINS = (
    "thanks for watching",
    "amara.org",
    "subscribe",
    "like and subscribe",
    "blank_audio",
    "blank audio",
    "speaking in foreign language",
)

# Spoken punctuation → real symbols (longer phrases first)
_SPOKEN_PUNCT: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bexclamation\s+(?:mark|point)\b", re.I), "!"),
    (re.compile(r"\bquestion\s+mark\b", re.I), "?"),
    (re.compile(r"\bfull\s+stop\b", re.I), "."),
    (re.compile(r"\bperiod\b", re.I), "."),
    (re.compile(r"\bdot\b", re.I), "."),
    (re.compile(r"\bcomma\b", re.I), ","),
    (re.compile(r"\bsemi[\s-]?colon\b", re.I), ";"),
    (re.compile(r"\bcolon\b", re.I), ":"),
    (re.compile(r"\bapostrophe\b", re.I), "'"),
    (re.compile(r"\bnew\s+line\b", re.I), "\n"),
    (re.compile(r"\bnewline\b", re.I), "\n"),
    (re.compile(r"\bnew\s+paragraph\b", re.I), "\n\n"),
    (re.compile(r"\bdash\b", re.I), "—"),
    (re.compile(r"\bhyphen\b", re.I), "-"),
]

_SPOKEN_PUNCT_WORD = re.compile(
    r"\b(full\s+stop|period|dot|comma|question\s+mark|"
    r"exclamation\s+(?:mark|point)|semi[\s-]?colon|colon|"
    r"new\s+line|newline|new\s+paragraph|apostrophe|dash|hyphen)\b",
    re.I,
)

_ATTACH_PUNCT = set(",.!?;:'\"—-")

_OPENERS = ("(", "[", "{", '"', "'", "«")


def _collapse_stutter_words(text: str) -> str:
    """Collapse Whisper stutter loops: 'four four four four' → 'four'."""
    t = text or ""
    if not t.strip():
        return t
    words = t.split()
    if len(words) < 2:
        return t
    out: list[str] = [words[0]]
    for w in words[1:]:
        prev = out[-1]
        if not w:
            continue
        # identical immediate repeat → drop (keep "had had"? no, drop)
        if w.lower() == prev.lower():
            continue
        out.append(w)
    return " ".join(out)


def _fix_spacing_punctuation(text: str) -> str:
    """Clean spacing and common speech→text artifacts."""
    t = text or ""
    if not t:
        return t
    # Ratios first: "3 is to 2", "3 to 2", "16 : 9" → "3:2", "16:9"
    t = re.sub(
        r"\b(\d+(?:\.\d+)?)\s+(?:is\s+to|to|is|:)\s*(\d+(?:\.\d+)?)\b",
        r"\1:\2",
        t,
    )
    t = re.sub(r"\b(\d+)\s*[:：]\s*(\d+)\b", r"\1:\2", t)
    # No space before punctuation (but skip digits so ratios survive)
    t = re.sub(r"\s+([,.!?;%])", r"\1", t)
    # Colon: add space after only when NOT a ratio (not between digits)
    t = re.sub(r"(?<![0-9:])\s+(:)(?![0-9])", r"\1", t)
    # Space after sentence enders . ! ? when followed by a word char
    t = re.sub(r"([.!?])(?=[A-Za-z0-9])", r"\1 ", t)
    # Space after commas/semicolons (colons handled above for ratios)
    t = re.sub(r"([,;])(?=\S)", r"\1 ", t)
    # Percent
    t = re.sub(r"(\d)\s+%", r"\1%", t)
    # Currency
    t = re.sub(r"([$€£])\s+(\d)", r"\1\2", t)
    # Collapse multiple spaces (keep newlines)
    t = re.sub(r"[^\S\n]+", " ", t)
    t = re.sub(r" *\n *", "\n", t)
    return t.strip()


def strip_special_tokens(text: str) -> str:
    t = _SPECIAL_TOKEN_RE.sub(" ", text or "")
    t = re.sub(r"\s+", " ", t).strip()
    return t


def apply_spoken_punctuation(text: str) -> str:
    """Turn spoken 'comma' / 'period' / etc. into real symbols."""
    t = text or ""
    for pat, repl in _SPOKEN_PUNCT:
        t = pat.sub(repl, t)
    # Tidy spaces around inserted punctuation
    t = re.sub(r"\s+([,.!?;:])", r"\1", t)
    t = re.sub(r"([(\[{])\s+", r"\1", t)
    t = re.sub(r"\s+([)\]}])", r"\1", t)
    t = re.sub(r" +", " ", t)
    t = re.sub(r" *\n *", "\n", t)
    return t.strip() if not (t or "").endswith("\n") else t.strip(" ") 


def is_punctuation_only(text: str) -> bool:
    t = (text or "").strip(" ")  # keep newlines
    if not t:
        return False
    return bool(re.fullmatch(r"[\s,.!?;:'\"—\-…]+", t))


def has_spoken_punctuation(text: str) -> bool:
    return bool(_SPOKEN_PUNCT_WORD.search(text or ""))


def is_junk(text: str) -> bool:
    t = strip_special_tokens(text or "")
    if not t:
        return True
    # Voice punctuation commands are never junk
    if has_spoken_punctuation(t):
        return False
    converted = apply_spoken_punctuation(t)
    if is_punctuation_only(converted):
        return False
    low = t.lower().strip(" .!?,;:\"'")
    if low in _JUNK_EXACT:
        return True
    if any(s in low for s in _JUNK_CONTAINS):
        return True
    if re.fullmatch(r"[\W_]+", t):
        return True
    if len(low) <= 1:
        return True
    return False


def apply_replacements(text: str, replacements: dict[str, str]) -> str:
    if not text or not replacements:
        return text
    out = text
    for wrong in sorted(replacements.keys(), key=len, reverse=True):
        right = replacements[wrong]
        out = re.sub(re.escape(wrong), right, out, flags=re.IGNORECASE)
    return out


def soft_format(text: str, *, capitalize: bool = False) -> str:
    """Format a live phrase without forcing a full stop."""
    t = (text or "").strip()
    if not t:
        return ""
    keep_end_punct = has_spoken_punctuation(t)
    # Whisper often ends every pause with '.' — strip unless user said period/etc.
    if not keep_end_punct:
        if t.endswith("...") or t.endswith("…"):
            pass
        elif t.endswith(".") and not t.endswith(".."):
            t = t[:-1].rstrip()
    t = apply_spoken_punctuation(t)
    t = re.sub(r"[^\S\n]+", " ", t)
    t = re.sub(r" *\n *", "\n", t)
    if t.endswith("\n"):
        t = t.rstrip(" ") 
    else:
        t = t.strip()
    if is_punctuation_only(t):
        return t
    t = re.sub(r"\s+\.", ".", t)
    t = re.sub(r"[^\S\n]+", " ", t).strip()
    if capitalize and t and t[0].isalpha():
        t = t[0].upper() + t[1:]
    t = re.sub(r"([.!?])\s+([a-z])", lambda m: m.group(1) + " " + m.group(2).upper(), t)
    t = re.sub(r"\n([a-z])", lambda m: "\n" + m.group(1).upper(), t)
    # Lowercase obvious mid-sentence shout-caps
    t = _fix_shout_caps(t)
    return t


_COMMON_CAPWORDS = {
    "a","an","and","are","as","at","be","but","by","for","from","has","have",
    "he","her","his","i","if","in","into","is","it","its","my","no","not","of",
    "on","or","our","so","she","that","the","their","there","they","this","to",
    "was","we","what","when","which","who","will","with","you","your",
}


def _fix_shout_caps(text: str) -> str:
    """Lowercase obvious mid-sentence capitals ('is The category' → 'is the category')."""
    t = text or ""
    if not t:
        return t
    parts = re.split(r"(\s+)", t)
    out: list[str] = []
    prev_word: str | None = None
    for i, tok in enumerate(parts):
        if not tok.strip():
            out.append(tok)
            continue
        after_sentence = prev_word is not None and prev_word[-1] in ".!?"
        first = prev_word is None
        if tok[:1].isupper() and not tok.isupper():
            low = tok.lower()
            if not first and not after_sentence and low in _COMMON_CAPWORDS:
                tok = low
        out.append(tok)
        prev_word = tok
    return "".join(out)


def ends_with_sentence_end(text: str) -> bool:
    """True if text clearly ends a sentence (real . ! ? or newline)."""
    t = (text or "").rstrip()
    if not t:
        return False
    if t.endswith("\n"):
        return True
    return t[-1] in ".!?"


def should_attach_to_previous(text: str) -> bool:
    """True when the paste should glue to the previous word (no space before)."""
    t = (text or "").lstrip()
    return bool(t) and t[0] in _ATTACH_PUNCT


def prepare_transcript(
    text: str,
    *,
    replacements: dict[str, str] | None = None,
    sentence_start: bool = False,
    finalize: bool = False,
) -> str:
    t = strip_special_tokens(text or "")
    if is_junk(t):
        return ""
    t = _collapse_stutter_words(t)
    t = apply_replacements(t, replacements or {})
    t = strip_special_tokens(t)
    if is_junk(t):
        return ""
    spoken = has_spoken_punctuation(t)
    t = soft_format(t, capitalize=sentence_start and not spoken)
    if not t:
        return ""
    t = _fix_spacing_punctuation(t)
    if not t:
        return ""
    if t.endswith("\n"):
        return t
    return t.strip()
