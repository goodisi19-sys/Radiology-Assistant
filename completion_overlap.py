"""Insert-only overlap handling. Existing right-hand text is never edited."""
import re


def trim_right_overlap(suffix, after):
    """Return an insertable prefix, or None for an unverified mid-line continuation.

    Match complete tokens, including punctuation, rather than character fragments.
    Do not assume that two different measurements, negations or sides are equivalent.
    """
    if not after.strip():
        return suffix
    right = after.lstrip()
    # Use the actual right context: clipping it could hide a word boundary.
    for match in re.finditer(r'\w+|[^\w\s]', suffix):
        overlap = suffix[match.start():]
        if not right.startswith(overlap):
            continue
        following = right[len(overlap):len(overlap)+1]
        if overlap[-1:].isalnum() and following and (following.isalnum() or following == '_'):
            continue
        prefix = suffix[:match.start()]
        if after[:1].isspace():
            prefix = prefix.rstrip()
        return prefix
    return None


def insertion_text(suffix, after):
    # End-of-block behaviour is preserved. Mid-line inserts already have spacing
    # supplied by the suffix or by the existing text to the right of the caret.
    return suffix if after.strip() else suffix + ' '
