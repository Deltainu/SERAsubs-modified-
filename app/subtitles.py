import math

# Whisper returns one segment per utterance, which can be half a minute of
# speech and several hundred characters, far too much for a single subtitle.
# This module regroups the individual words, each of which carries its own
# timestamp, into cues of a readable length.

# how much text may be on screen at once. the broadcast standard of 42
# characters per line is too wide once it is burned onto a clip, so Short
# is the default.
# chars: per line for latin scripts, cjk: the same for japanese/chinese,
# which fit fewer characters per line, seconds: how long a cue may last
STYLES = {
    "Short (best for burn-in)": {"chars": 26, "cjk": 10, "seconds": 3.0},
    "Normal": {"chars": 32, "cjk": 13, "seconds": 4.5},
    "Long (fewer cuts)": {"chars": 42, "cjk": 16, "seconds": 6.0},
}

DEFAULT_STYLE = "Short (best for burn-in)"

MAX_LINES = 2
MIN_CUE_SECONDS = 1.2

# a pause of at least this long counts as a sentence boundary
MAX_GAP_SECONDS = 0.7

SENTENCE_ENDS = ".!?…。！？"
CLAUSE_ENDS = ",;:、，；：」』"

# character ranges that use the narrower line limit
CJK_RANGES = (
    (0x3040, 0x30FF),    # hiragana + katakana
    (0x3400, 0x4DBF),    # rare kanji
    (0x4E00, 0x9FFF),    # the main kanji/hanzi block
    (0xF900, 0xFAFF),    # compatibility kanji
    (0xAC00, 0xD7AF),    # hangul
)


def looks_cjk(text):
    for character in text:
        code = ord(character)
        for low, high in CJK_RANGES:
            if low <= code <= high:
                return True
    return False


def style_of(name):
    return STYLES.get(name, STYLES[DEFAULT_STYLE])


def line_limit(text, style=None):
    style = style or STYLES[DEFAULT_STYLE]
    return style["cjk"] if looks_cjk(text) else style["chars"]


# punctuation that may not start a line, it belongs to the preceding word
NO_LINE_START = "、。，．？！?!,.」』）)"


# japanese has no spaces to break on, so the text is split into pieces:
# one per japanese character, but latin words stay whole so that "mixed"
# cannot be broken into "mixe/d"
def _cjk_pieces(text):
    pieces = []
    latin = ""

    for character in text:
        if character.isascii() and (character.isalnum() or character in "'-"):
            latin += character
            continue

        if latin:
            pieces.append(latin)
            latin = ""

        if character == " ":
            # a space only matters between two latin words
            if pieces and pieces[-1][-1].isascii():
                pieces.append(" ")
            continue

        # punctuation stays attached to the preceding piece
        if character in NO_LINE_START and pieces:
            pieces[-1] += character
        else:
            pieces.append(character)

    if latin:
        pieces.append(latin)
    return pieces


# breaks a cue over at most two lines of similar length
def wrap(text, limit):
    text = text.strip()
    if len(text) <= limit:
        return text

    if looks_cjk(text):
        lines = []
        current = ""
        for piece in _cjk_pieces(text):
            if current and len(current) + len(piece) > limit:
                lines.append(current.strip())
                current = "" if piece == " " else piece
            else:
                current += piece
        if current.strip():
            lines.append(current.strip())
        return "\n".join(lines)

    words = text.split()
    # aim for the middle, then break at the nearest space
    target = len(text) / 2
    lines = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and (len(candidate) > limit or len(current) >= target):
            lines.append(current)
            current = word
            target = float("inf") if len(lines) >= MAX_LINES - 1 else target
        else:
            current = candidate
    if current:
        lines.append(current)
    return "\n".join(lines)


def _ends_with(text, characters):
    text = text.strip()
    return bool(text) and text[-1] in characters


# first pass: split only at natural boundaries, a sentence end or a pause
def _natural_chunks(words):
    chunks = []
    current = []

    for word in words:
        if current and word.start - current[-1].end > MAX_GAP_SECONDS:
            chunks.append(current)
            current = []

        current.append(word)

        if _ends_with("".join(w.word for w in current), SENTENCE_ENDS):
            chunks.append(current)
            current = []

    if current:
        chunks.append(current)
    return chunks


# how many cues a piece of text has to become to stay within the limits
def _piece_count_for(length, span, limit, max_seconds):
    return max(1,
               math.ceil(length / (limit * MAX_LINES)),
               math.ceil(span / max_seconds))


# how many cues this chunk has to become to stay within the limits
def _piece_count(words, limit, max_seconds):
    length = len("".join(w.word for w in words).strip())
    span = words[-1].end - words[0].start
    return _piece_count_for(length, span, limit, max_seconds)


# second pass: split an oversized chunk into equal pieces rather than
# filling one to the limit and leaving an orphan behind. splitting into
# "Hello, this is a test of the subtitle" + "engine." reads badly, two
# halves of similar length do not
def _split_evenly(words, pieces):
    if pieces <= 1:
        return [words]

    total = sum(len(w.word) for w in words)
    target = total / pieces

    groups = []
    current = []
    used = 0

    for word in words:
        current.append(word)
        used += len(word.word)

        # never produce more pieces than were decided on
        if len(groups) == pieces - 1:
            continue

        # a comma near the target is a better break than an arbitrary one
        text = "".join(w.word for w in current)
        if used >= target or (used >= target * 0.6
                              and _ends_with(text, CLAUSE_ENDS)):
            groups.append(current)
            current = []
            used = 0

    if current:
        groups.append(current)
    return groups


# natural breaks first, then even out whatever is still too long or too wide
def cues_from_words(words, limit, max_seconds):
    groups = []
    for chunk in _natural_chunks(words):
        groups.extend(_split_evenly(chunk, _piece_count(chunk, limit, max_seconds)))
    return groups


# the smallest units a line may be broken at, and what joins them back
# together: spaces between latin words, nothing between japanese characters
def _units(text):
    if looks_cjk(text):
        return _cjk_pieces(text), ""
    return text.split(), " "


# splits plain text into roughly equal parts, preferring a sentence or
# clause end near the target over an arbitrary cut
def _split_text(text, pieces):
    units, glue = _units(text)
    if pieces <= 1 or len(units) <= 1:
        return [text.strip()]

    target = len(text) / pieces
    parts = []
    current = ""

    for unit in units:
        current = (current + glue + unit).strip() if current else unit.strip()

        # never produce more parts than were decided on
        if len(parts) == pieces - 1:
            continue

        if len(current) >= target or (len(current) >= target * 0.6
                                      and _ends_with(current,
                                                     SENTENCE_ENDS + CLAUSE_ENDS)):
            parts.append(current)
            current = ""

    if current:
        parts.append(current)
    return parts


# a segment without word timestamps still has to be cut, otherwise half a
# minute of speech ends up in one cue. the time is shared out by how much
# text each part carries, which is an estimate but stays readable
def _cues_without_words(segment, limit, max_seconds):
    text = segment.text.strip()
    if not text:
        return []

    start = float(segment.start)
    span = max(0.0, float(segment.end) - start)
    parts = _split_text(text, _piece_count_for(len(text), span, limit,
                                               max_seconds))

    total = sum(len(part) for part in parts) or 1
    cues = []
    for part in parts:
        end = min(float(segment.end), start + span * len(part) / total)
        cues.append({"start": start, "end": max(end, start), "text": wrap(part, limit)})
        start = end
    return cues


# turns a group of words into the cue that gets written out
def _finish(group, limit):
    text = "".join(w.word for w in group).strip()
    return {
        "start": float(group[0].start),
        "end": float(group[-1].end),
        "text": wrap(text, limit),
    }


# very short cues are held a little longer, as long as that does not run
# into the cue that follows
def stretch_short_cues(cues):
    for index, cue in enumerate(cues):
        if cue["end"] - cue["start"] >= MIN_CUE_SECONDS:
            continue
        wanted = cue["start"] + MIN_CUE_SECONDS
        if index + 1 < len(cues):
            wanted = min(wanted, cues[index + 1]["start"] - 0.05)
        cue["end"] = max(cue["end"], wanted)
    return cues


# entry point for the app. consumes whisper's segments as they arrive and
# yields cues, so the srt can be written while transcription is still running
def cues_from_segments(segments, style_name=DEFAULT_STYLE):
    style = style_of(style_name)

    for segment in segments:
        words = getattr(segment, "words", None)

        # whisper does not always return word timestamps, and a segment can
        # be half a minute long, so it is cut by length and time instead
        if not words:
            limit = line_limit(segment.text, style)
            for cue in stretch_short_cues(
                    _cues_without_words(segment, limit, style["seconds"])):
                if cue["text"]:
                    yield cue
            continue

        limit = line_limit(segment.text, style)
        groups = cues_from_words(words, limit, style["seconds"])
        cues = stretch_short_cues([_finish(g, limit) for g in groups if g])
        for cue in cues:
            if cue["text"]:
                yield cue
