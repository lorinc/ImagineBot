# Split failure showcase — node [1.11], en_policy1_child_protection

## What happened

During the iter3 build, node [1.11] (6477 chars) triggered the split step.
The LLM identified 6 sub-sections and provided a `start` string for each.
The code tried to locate each `start` string inside the node's text using `str.find()`.
Every numbered section (1–5) returned position `-1`. The split was abandoned.
Node [1.11] remained in the index at 6477 chars, above the 5000-char limit.

---

## The text that was sent to the LLM (first 30 chars of each section)

The node content begins like this (exact bytes from the source):

```
1.  **Recognising Abuse:**
    To ensure that our pupils are protected from harm, we need to understand
    what types of behaviour constitute abuse and neglect. ...

2.  **Physical Abuse:**
    Physical abuse is a form of abuse which may involve hitting, shaking, ...

3.  **Emotional Abuse:**
    Emotional abuse is the persistent emotional maltreatment of a child ...

4.  **Sexual Abuse:**
    Sexual abuse involves forcing or enticing a child or young person ...

5.  **Neglect:**
    Neglect is the persistent failure to meet a child's basic physical ...

    **B. Indicators of Abuse:**
    Physical signs define some types of abuse, for example, bruising ...
```

Sections 1–5 are a Markdown ordered list rendered by the source document as
`N.  ` — **one period, two spaces**.

Section 6 (`B. Indicators of Abuse`) is a bold heading, not a list item.

---

## What the LLM returned

The LLM was asked: *"provide the first 50 characters of that sub-section,
copied verbatim from the text"*

| # | Title returned | `start` string returned (repr) |
|---|----------------|-------------------------------|
| 1 | Recognising Abuse Types | `'1. **Recognising Abuse:**\n    To ensure...'` |
| 2 | Physical Abuse Definition | `'2. **Physical Abuse:**\n    Physical abuse...'` |
| 3 | Emotional Abuse Definition | `'3. **Emotional Abuse:**\n    Emotional abuse...'` |
| 4 | Sexual Abuse Definition | `'4. **Sexual Abuse:**\n    Sexual abuse...'` |
| 5 | Neglect Definition | `'5. **Neglect:**\n    Neglect is...'` |
| 6 | Indicators of Abuse | `'**B. Indicators of Abuse:**\n    Physical signs...'` |

---

## Why sections 1–5 failed

The LLM normalised `1.  ` (two spaces) to `1. ` (one space) in every `start` string.

```
Source text:   '1.  **Recognising Abuse:**'
                   ^^  two spaces

LLM returned:  '1. **Recognising Abuse:**'
                  ^   one space
```

`str.find()` is an exact byte match. The code tries prefixes of 50, 30, and 15 chars.
Even at 15 chars the mismatch is present:

```
text.find('1. **Recognis')   →  -1    (not in source)
text.find('1.  **Recognis')  →   0    (would match — but this string was never tried)
```

The same normalisation happened for sections 2, 3, 4, and 5.

Section 6 has no leading number, no double-space, and matched at position 3955 on the
first attempt.

---

## The rule in `_split_text_by_starts`

```python
for start in starts[1:]:          # skip section 1 (assumed at position 0)
    matched = False
    for prefix_len in (50, 30, 15):
        prefix = start[:prefix_len].strip()
        idx = text.find(prefix, positions[-1] + 1)
        if idx != -1:
            matched = True
            break
    if not matched:
        return []                  # one miss → discard everything, return empty
```

Section 1 is implicitly placed at position 0, so it is never searched.
Section 2 is the first one searched. It fails. `return []` fires immediately.
Sections 3–6 are never tried.

---

## What the code did with the empty result

```python
slices = _split_text_by_starts(node.content, [s["start"] for s in sections])
if len(slices) != len(sections):   # 0 != 6 → True
    _blog(f"  [{node.id}] split FAILED ...")
    return                         # node unchanged, still 6477 chars
```

`return` exits `_split_large_node`. `_split_all` recurses into `node.children`,
but the node is still a leaf (no children were created), so nothing more happens.
No retry. No stdout message. The failure is only in the build log.

---

## What needs to change

**Boundary matching:** `strip()` on the prefix hides the double-space before the
`find()` call, but the source text itself still has the double-space. Either:
- normalise whitespace in both the search string **and** the source before matching, or
- use a regex with `\s+` instead of exact-space matching.

**Retry on failure:** if boundary detection fails, re-prompt the LLM with the
raw text and ask for character offsets instead of verbatim start strings,
or retry with a simpler split prompt.

**Stdout visibility:** the `_blog()` call goes to the build log only.
A split failure should also print to stdout so it is visible during the build run.

**Build gate:** after `_split_all`, any remaining oversize leaf should abort the
build (exit non-zero) rather than fall through to validation as a passive warning.
