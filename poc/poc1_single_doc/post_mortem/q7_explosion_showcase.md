# Q7 explosion showcase — query 7, en_policy5_code_of_conduct

## What happened

During the iter3 eval, query 7 sent 59,569 chars to synthesis — the highest of any
query across all four documents. The target for a cross-section query is under 15K.
The answer returned was correct. The cost was ~4× over budget.

---

## The query

```
"Is racist language treated differently from other forms of misconduct?"
```

Type: cross_section. The note on the query states it is a vocabulary mismatch probe:
"racist language" does not appear verbatim in §4 headings, so the retrieval must
bridge §4 (Behaviour) with §5 (Anti-Racism).

---

## The outline seen by the selection LLM (sections 4, 5, 6 only)

The selection LLM sees every node in the index as a flat, indented list:

```
[4] School Behaviour Policy and Management: Policy scope; Community applicability; ...
  [4.1] Policy Scope: Community, Settings, Development: Policy applicability; ...
  [4.2] Behaviour Policy Terminology Guide: Positive Behaviour Approach; ...
  [4.3] Imagine Montessori Behaviour Principles: Individual respect; ...
  ...
  [4.18] Inappropriate language, stereotypes, discrimination: Inclusive school; Abusive behavior; ...
  ...21 children total...

[5] School Anti-Racism Policy: Policy scope; Community members; Direct racism; ...
  [5.1] Anti-Racism Policy Scope and Application: Policy scope; ...
  ...
  [5.7] School Action: Racism Suspected or Reported: Racism incident investigation; ...
  ...9 children total...

[6] Anti-Bullying Policy: Scope, Prevention, Action: Policy scope; Student coverage; ...
  [6.1] Anti-Bullying Policy Scope and Coverage: Students, staff, parents, visitors; ...
  ...
  [6.11] Bullying Action: Interviews, Sanctions, Reporting: Interview victim; Sanctions; ...
    [6.11.L0] Interviewing Involved Parties: Interview victim; Explain process; ...
    ...6 children...
  ...11 children total...
```

Each parent node has its own entry with a summary of all its descendants' topics.
`[4]` looks like a self-contained, selectable unit — the outline gives no visual signal
that selecting it delivers 22,500 chars instead of a single focused section.

---

## What the LLM selected

```json
selected_ids: ["4", "4.18", "5", "5.7", "6", "6.11"]
```

```
reasoning: "These sections outline the school's general behaviour policy, specific
policies for inappropriate language and discrimination, and the anti-racism and
anti-bullying policies, including their respective disciplinary actions, which are
necessary to compare the treatment of racist language with other forms of misconduct."
```

The selection is reasonable. The question spans three top-level sections. The LLM
selected the general policy for context ([4]), the specific leaf about discrimination
([4.18]), the full anti-racism section ([5]), the racism response leaf ([5.7]), and the
full anti-bullying section ([6]) with its action node ([6.11]).

Four of the six IDs are parent nodes:

| ID | Type | char_count (own content) |
|----|------|--------------------------|
| [4] | PARENT | 0 |
| [4.18] | leaf | 461 |
| [5] | PARENT | 0 |
| [5.7] | leaf | 1,288 |
| [6] | PARENT | 0 |
| [6.11] | PARENT | 0 |

Parent nodes store no direct content — `char_count = 0`. Their content is distributed
across their children.

---

## Why 59,569 chars were sent to synthesis

The synthesis step calls `node.full_text()` on each selected node:

```python
sections_text = "\n\n---\n\n".join(
    f"[Section {n.id}: {n.title}]\n{n.full_text(include_heading=False)}"
    for n in selected_nodes
)
```

`full_text()` is recursive:

```python
def full_text(self, include_heading=True):
    parts = []
    if include_heading and self.level > 0:
        parts.append(f"{'#' * self.level} {self.title}")
    if self.content:
        parts.append(self.content)
    for child in self.children:
        parts.append(child.full_text(include_heading=True))   # ← walks entire subtree
    return "\n\n".join(p for p in parts if p)
```

For a parent node with no direct content, this delivers the full text of every
descendant. The three parent nodes expand as follows:

| Node | Direct content | full_text delivers | Children |
|------|---------------|---------------------|----------|
| [4] | 0c | ~22,500c | 21 children |
| [5] | 0c | ~7,500c | 9 children |
| [6] | 0c | ~13,400c | 11 children (incl. [6.11]) |
| [6.11] | 0c | ~5,900c | 6 children |

Additionally, [4.18] and [5.7] are included both directly and as subtrees of [4] and
[5] respectively — they are sent to synthesis twice.

Total: ~59,569 chars. The two specific leaves the LLM correctly identified ([4.18] at
461c and [5.7] at 1,288c) contain the actual answer. Everything else is noise.

---

## The structural asymmetry

The outline presents parents and children as equivalent, selectable entries. But they
are not equivalent at retrieval time:

```
Outline entry for [4]:   one line, ~120 chars of aggregated topics
full_text() of [4]:      ~22,500 chars — the entire behaviour policy
```

The LLM has no way to know this from the outline. It sees `[4]` as a node like any
other and selects it for valid reasons. The explosion is a consequence of that
selection, invisible at decision time.

The only nodes that are safe to select are leaves. A parent selected for its aggregate
summary delivers all of its descendants whether they are relevant or not.

---

## What needs to change

The problem is not the selection LLM's reasoning — it correctly identified which
top-level sections are relevant. The problem is that "select [4]" means "read all of
§4" at synthesis time.

Three levers:

**1. Prevent parent selection at the prompt level.**
Tell the selection LLM: "Only select leaf nodes (those with no indented children
below them). If a whole section is relevant, select the specific children you need,
not the parent."

**2. Expand parent selections to children before synthesis.**
After the LLM returns IDs, replace each parent with its direct children. The LLM's
intent ("I need §4") is preserved; the delivery is the child nodes rather than the
full subtree.

**3. Budget cap at the synthesis step.**
After resolving `full_text()` for all selected nodes, if the total exceeds a threshold,
drop or trim the least relevant nodes before sending to the LLM.

Levers 1 and 2 address the root cause (parent selection). Lever 3 is a safety net.
