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

# characters read per second. the styles are built on this rate: 52
# characters over 3 seconds is exactly it, so a cue held for as long as its
# style allows is always readable
READING_SPEED = 17.0

# the most a cue may exceed the style's time limit, as a multiple of it.
# only a word longer than the limit itself produces such a cue, and past
# this point the duration is a bad timestamp rather than speech
MAX_OVERRUN = 2.0

# how long a cue may be held past its last word to bridge a pause. a blank
# screen inside a sentence reads as the end of one, so a short pause is
# bridged rather than blanked; a longer one is a real pause
MAX_LEAD_OUT = 2.0

# the gap left between a cue and the one that follows
CUE_GAP_SECONDS = 0.05

# a gap this large between two words is not a pause but a cut made by the
# voice filter. deliberately the same figure as MAX_LEAD_OUT, so the two
# rules meet without a gap between them: shorter is bridged, longer is
# examined for a stranded word
STRANDED_GAP_SECONDS = MAX_LEAD_OUT

# how many words may be moved across such a gap. a longer run was spoken
# where it stands
STRANDED_WORDS = 3

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

# how much of a cue has to be cjk before it is treated as cjk. a single
# kanji in an english sentence - a name, a 草 - must not put the whole cue
# on the japanese line limit, which would cut it into three-character
# scraps, so the decision goes by share rather than by presence
CJK_SHARE = 0.3


def looks_cjk(text):
    counted = 0
    found = 0

    for character in text:
        if character.isspace():
            continue
        counted += 1
        code = ord(character)
        for low, high in CJK_RANGES:
            if low <= code <= high:
                found += 1
                break

    return counted > 0 and found / counted >= CJK_SHARE


def style_of(name):
    return STYLES.get(name, STYLES[DEFAULT_STYLE])


# the limit belongs to the text that is actually shown, so it is asked for
# per cue and never for a whole segment: one japanese word at the end of an
# english segment would otherwise narrow everything around it
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


# the smallest units a line may be broken at, and what joins them back
# together: spaces between latin words, nothing between japanese characters
def _units(text):
    if looks_cjk(text):
        return _cjk_pieces(text), ""
    return text.split(), " "


def _ends_with(text, characters):
    text = text.strip()
    return bool(text) and text[-1] in characters


# splits a sequence into at most `pieces` groups of similar weight. the
# target is recomputed after every break, so weight a group did not take is
# spread over the groups that follow instead of accumulating in the last
# one, which is where an orphan would end up. ends_well, when given, tests
# whether an item is a punctuation mark and so a preferable break point
def _even_groups(items, weight, pieces, ends_well=None):
    items = list(items)
    if not items:
        return []

    pieces = min(max(1, pieces), len(items))
    if pieces == 1:
        return [items]

    weights = [weight(item) for item in items]
    left = sum(weights)

    groups = []
    current = []
    used = 0

    for index, item in enumerate(items):
        current.append(item)
        used += weights[index]
        left -= weights[index]

        # groups still to be filled, this one included
        wanted = pieces - len(groups)
        if wanted <= 1:
            continue

        # every group after this one needs at least one item of its own
        spare = len(items) - index - 1 - (wanted - 1)
        target = (used + left) / wanted

        if spare <= 0 or used >= target or (
                used >= target * 0.6 and ends_well and ends_well(item)):
            groups.append(current)
            current = []
            used = 0

    if current:
        groups.append(current)
    return groups


# where to break a cue so that the longest line comes out as short as it
# can, and among the ties the most even set. filling line by line gets this
# wrong: it packs the first line up to the limit and strands the rest on
# the last one. the cost of working it out exactly is nothing at these
# sizes, a cue is a handful of words over at most MAX_LINES lines
def _line_breaks(units, glue, count):
    total = len(units)
    count = max(1, min(count, total))

    chars = [0]
    for unit in units:
        chars.append(chars[-1] + len(unit))

    def length(start, stop):
        return chars[stop] - chars[start] + len(glue) * (stop - start - 1)

    # (lines, start) -> longest line, sum of squares, where the first ends
    best = {}
    for start in range(total):
        span = length(start, total)
        best[(1, start)] = (span, span * span, total)

    for lines in range(2, count + 1):
        for start in range(total - lines + 1):
            choice = None
            for stop in range(start + 1, total - lines + 2):
                span = length(start, stop)
                rest = best[(lines - 1, stop)]
                option = (max(span, rest[0]), span * span + rest[1], stop)
                if choice is None or option[:2] < choice[:2]:
                    choice = option
            best[(lines, start)] = choice

    breaks = []
    start = 0
    for lines in range(count, 0, -1):
        stop = best[(lines, start)][2]
        breaks.append((start, stop))
        start = stop
    return breaks


# breaks a cue over at most MAX_LINES lines of similar length. the line
# count is a hard cap, not a target: a third line is where the one-word
# orphan appears, and a cue over budget is better slightly too wide than
# stacked over half the screen. a line can still exceed the limit by a
# character or two when no word boundary divides the text evenly;
# _line_breaks guarantees that overshoot is the smallest possible
def wrap(text, limit):
    text = text.strip()
    if len(text) <= limit:
        return text

    units, glue = _units(text)
    if not units:
        return text

    count = min(MAX_LINES, max(1, math.ceil(len(text) / limit)))
    lines = [glue.join(units[start:stop]).strip()
             for start, stop in _line_breaks(units, glue, count)]
    return "\n".join(line for line in lines if line)


# whether the text comes apart into lines that all fit. it can be within
# the budget and still not, when no word boundary divides it evenly
def _fits_lines(text, limit):
    return all(len(line) <= limit for line in wrap(text, limit).split("\n"))


# the text a group of words turns into. faster-whisper hands every word its
# own leading space, so the words need no glue and only the first one has
# to be stripped
def _text_of(words):
    return "".join(w.word for w in words).strip()


# a private copy of a word. the repair below shifts words in time, and the
# objects the engine returns are not modified
class _Word:
    __slots__ = ("word", "start", "end")

    def __init__(self, word, start, end):
        self.word = word
        self.start = float(start)
        self.end = float(end)


# a run of words left behind on the wrong side of a hole. the shape is
# always the same: a word or two, no full stop after them, and the sentence
# carrying on once the hole is over
def _is_stranded(run, following):
    if not run or len(run) > STRANDED_WORDS:
        return False

    text = _text_of(run)
    if not text or _ends_with(text, SENTENCE_ENDS):
        return False

    # a capital letter after the hole starts a new sentence, and then
    # nothing in front of it is missing
    return not following.word.strip()[:1].isupper()


# moves a run so that it ends just before the given time, keeping each
# word's duration. shifts forward only: the word was spoken, the timestamp
# puts it in the wrong place
def _move_before(run, when):
    shift = (when - CUE_GAP_SECONDS) - run[-1].end
    if shift <= 0:
        return
    for word in run:
        word.start += shift
        word.end += shift


# the voice filter cuts the audio into chunks before the model sees it, and
# a word falling on one of those cuts is returned pinned to the end of the
# preceding chunk, seconds away from its own sentence. the text is correct,
# only the timestamp is not, so the fragment is moved to where its sentence
# continues
def repair_stranded(words):
    begins = 0
    for index in range(len(words) - 1):
        following = words[index + 1]
        run = words[begins:index + 1]

        if following.start - words[index].end > STRANDED_GAP_SECONDS:
            if _is_stranded(run, following):
                _move_before(run, following.start)
            begins = index + 1
        elif _ends_with(words[index].word, SENTENCE_ENDS):
            begins = index + 1
    return words


# first pass: split only at natural boundaries, a sentence end or a pause
def _natural_chunks(words):
    chunks = []
    current = []

    for word in words:
        if current and word.start - current[-1].end > MAX_GAP_SECONDS:
            chunks.append(current)
            current = []

        current.append(word)

        if _ends_with(word.word, SENTENCE_ENDS):
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


# second pass: split an oversized chunk into equal pieces rather than
# filling one to the limit and leaving an orphan behind. splitting into
# "Hello, this is a test of the subtitle" + "engine." reads badly, two
# halves of similar length do not
def _split_evenly(words, pieces):
    return _even_groups(words, lambda word: len(word.word), pieces,
                        lambda word: _ends_with(word.word, CLAUSE_ENDS))


# third pass: a chunk is cut into as many pieces as its width and its
# length need, and every piece is then held against its own limits again -
# the count was worked out by character alone, and where the speaker slowed
# down that does not follow the clock. it repeats until a piece fits or is
# down to a single word, which is as far as any split can go
def _fit_words(group, style):
    if len(group) < 2:
        return [group]

    text = _text_of(group)
    limit = line_limit(text, style)
    span = group[-1].end - group[0].start

    # a word that on its own runs longer than the limit cannot be helped by
    # any split - cutting around it only shaves off pieces too brief to
    # read, so the time is left out of the count and the width decides
    longest = max(word.end - word.start for word in group)
    seconds = float("inf") if longest > style["seconds"] else style["seconds"]

    pieces = _piece_count_for(len(text), span, limit, seconds)
    if pieces <= 1:
        return [group]

    parts = _split_evenly(group, pieces)
    if len(parts) < 2:
        return [group]

    fitted = []
    for part in parts:
        fitted.extend(_fit_words(part, style))
    return fitted


# a sentence end or a pause is a good break point, but breaking at every
# one of them leaves single words on screen for a fraction of a second.
# neighbouring chunks are rejoined while the result still keeps the width
# and the time the style allows, and while the pause between them is short
# enough to be bridged anyway
def _merge_chunks(chunks, style):
    merged = []
    for chunk in chunks:
        if merged:
            joined = merged[-1] + chunk
            text = _text_of(joined)
            limit = line_limit(text, style)
            if (chunk[0].start - merged[-1][-1].end <= MAX_LEAD_OUT
                    and joined[-1].end - joined[0].start <= style["seconds"]
                    and len(text) <= limit * MAX_LINES
                    and _fits_lines(text, limit)):
                merged[-1] = joined
                continue
        merged.append(chunk)
    return merged


# natural breaks first, then put back together what was cut too small
def _chunks_of(words, style):
    return _merge_chunks(_natural_chunks(words), style)


# splits plain text into roughly equal parts, preferring a sentence or
# clause end near the target over an arbitrary cut
def _split_text(text, pieces):
    units, glue = _units(text)
    if pieces <= 1 or len(units) <= 1:
        return [text.strip()]

    groups = _even_groups(
        units, lambda unit: len(unit) + len(glue), pieces,
        lambda unit: _ends_with(unit, SENTENCE_ENDS + CLAUSE_ENDS))
    parts = [glue.join(group).strip() for group in groups]
    return [part for part in parts if part]


# the same job as _fit_words for the path without word timestamps: split
# the text until every part keeps its own width and its own share of the
# time. the time is distributed by how much text a part carries, which is
# an estimate, so each part is rechecked once it has been given one
def _text_cues(text, start, end, style):
    text = text.strip()
    limit = line_limit(text, style)
    span = max(0.0, end - start)

    pieces = _piece_count_for(len(text), span, limit, style["seconds"])
    parts = _split_text(text, pieces) if pieces > 1 else []

    if len(parts) < 2:
        return [{"start": start, "end": max(end, start),
                 "text": wrap(text, limit)}]

    total = sum(len(part) for part in parts) or 1
    cues = []
    at = start
    for part in parts:
        stop = min(end, at + span * len(part) / total)
        cues.extend(_text_cues(part, at, max(stop, at), style))
        at = stop
    return cues


# a segment without word timestamps still has to be cut, otherwise half a
# minute of speech ends up in one cue
def _cues_without_words(segment, style):
    text = segment.text.strip()
    if not text:
        return []
    return _text_cues(text, float(segment.start), float(segment.end), style)


# turns a group of words into the cue that gets written out
def _finish(group, style):
    text = _text_of(group)
    return {
        "start": group[0].start,
        "end": group[-1].end,
        "text": wrap(text, line_limit(text, style)),
    }


# whisper times words tightly, so a cue that ends on its last word is on
# screen for less time than its text takes to read. the end is extended to
# what READING_SPEED needs, into the silence that follows where there is
# any, but never past the start of the next cue: segments can overlap by a
# fraction of a second, and two cues at once stack or flicker when burned
# in. that neighbour is often the first cue of the next segment, so this
# runs over the finished stream rather than per segment
def _fit_time(cue, following, style):
    latest = None if following is None else following["start"] - CUE_GAP_SECONDS

    # a cue may exceed the style's limit when a single word does, but only
    # up to MAX_OVERRUN: a line hallucinated over a long silence can carry
    # one word with the whole span as its duration
    ceiling = min(max(cue["end"], cue["start"] + style["seconds"]),
                  cue["start"] + style["seconds"] * MAX_OVERRUN)
    if latest is not None:
        # trimming to a neighbour that starts before this cue does would
        # leave nothing on screen, so that one only stops it growing
        ceiling = min(ceiling, latest) if latest > cue["start"] else cue["end"]

    length = len(cue["text"].replace("\n", " "))
    wanted = cue["start"] + max(MIN_CUE_SECONDS, length / READING_SPEED)

    # a short pause inside a sentence is bridged rather than blanked
    if latest is not None and following["start"] - cue["end"] <= MAX_LEAD_OUT:
        wanted = max(wanted, latest)

    cue["end"] = min(max(cue["end"], wanted), ceiling)
    return cue


# a cue with nothing in it would be an empty line on screen
def _visible(cues):
    return (cue for cue in cues if cue["text"])


def _chunk_cues(chunks, style):
    for chunk in chunks:
        for group in _fit_words(chunk, style):
            yield _finish(group, style)


# segment boundaries follow whisper, not the speaker: with the voice filter
# off it returns a few words at a time, and chunks that belong together
# would never meet. the last chunk of a segment is therefore held back until
# the next segment has arrived
def _raw_cues(segments, style):
    pending = []

    for segment in segments:
        words = getattr(segment, "words", None)

        # whisper does not always return word timestamps, and a segment can
        # be half a minute long, so it is cut by length and time instead
        if not words:
            yield from _visible(_chunk_cues(_chunks_of(pending, style), style))
            pending = []
            yield from _visible(_cues_without_words(segment, style))
            continue

        pending.extend(_Word(w.word, w.start, w.end) for w in words)
        chunks = _chunks_of(repair_stranded(pending), style)
        yield from _visible(_chunk_cues(chunks[:-1], style))
        pending = list(chunks[-1])

    if pending:
        yield from _visible(_chunk_cues(_chunks_of(pending, style), style))


# entry point for the app. consumes whisper's segments as they arrive and
# yields cues, so the srt can be written while transcription is still
# running. one cue is held back, because the timing of the one before it
# has to know where the next one starts
def cues_from_segments(segments, style_name=DEFAULT_STYLE):
    style = style_of(style_name)
    previous = None

    for cue in _raw_cues(segments, style):
        if previous is not None:
            yield _fit_time(previous, cue, style)
        previous = cue

    if previous is not None:
        yield _fit_time(previous, None, style)
