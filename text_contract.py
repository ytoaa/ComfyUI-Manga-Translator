"""Plain text at OCR, translation and lettering boundaries; never parse HTML."""
import re

_BREAK = re.compile(r'<br\s*/?\s*>', re.IGNORECASE)


def ocr_problem(text):
    # Hayai's explicit unreadable-span marker is not recognized source text.
    # Do not erase it or invent a replacement for the missing characters.
    return 'ocr_unrecognized_span' if isinstance(text, str) and '<UNK_SPAN>' in text else None


def translation_text(source, target, normalize_breaks=True):
    issue = ocr_problem(target)
    if issue:
        raise ValueError(issue + ': translation contains an unresolved OCR marker')
    # Only formatting introduced by the translator is unambiguous. If the
    # source itself discusses a literal <br> tag, preserve the answer verbatim.
    # Manual overrides are also literal text. No entity decoding or tag removal.
    if normalize_breaks and not _BREAK.search(source):
        return _BREAK.subn('\n', target)
    return target, 0
