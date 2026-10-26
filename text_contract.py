"""Plain text at OCR, translation and lettering boundaries; never parse HTML."""
import re

_BREAK = re.compile(r'<br\s*/?\s*>', re.IGNORECASE)
_UNKNOWN = re.compile(r'<unk(?:_span)?>|\[unk\]', re.IGNORECASE)
_BREAK_MARKER = re.compile(r'(?<![A-Za-z0-9_\\/:])(?:\^n|\{n\}|\\r\\n|\\n)')


def ocr_problem(text):
    # Hayai's explicit unreadable-span marker is not recognized source text.
    # Do not erase it or invent a replacement for the missing characters.
    return 'ocr_unrecognized_span' if isinstance(text, str) and _UNKNOWN.search(text) else None


def translation_text(source, target, normalize_breaks=True):
    issue = ocr_problem(target)
    if issue:
        raise ValueError(issue + ': translation contains an unresolved OCR marker')
    if normalize_breaks and any(m.group() not in source for m in _BREAK_MARKER.finditer(target)):
        # This observed placeholder is not a JSON escape. Ask for a new answer
        # rather than guessing whether an arbitrary template token means a break.
        raise ValueError('translation_line_break_marker: use JSON newline escapes, not literal ^n, {n} or double-escaped newlines')
    # Only formatting introduced by the translator is unambiguous. If the
    # source itself discusses a literal <br> tag, preserve the answer verbatim.
    # Manual overrides are also literal text. No entity decoding or tag removal.
    if normalize_breaks and not _BREAK.search(source):
        return _BREAK.subn('\n', target)
    return target, 0
