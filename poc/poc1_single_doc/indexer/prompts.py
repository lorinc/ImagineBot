"""prompts.py — prompt builder functions, one per LLM call site.

Each function returns a plain string. No LLM calls, no I/O.
"""

from .node import Node

# Shared instruction fragment used by all topic-generation prompts
_PHRASE_PROMPT = (
    "For each distinct concept, rule, or procedure in this section, "
    "write a 1–5 word topic phrase. Separate phrases with semicolons. "
    "No sentences, no elaboration."
)


def make_topics_prompt(full_text: str, breadcrumb: str) -> str:
    """Prompt for generating (title, topics) for a leaf node."""
    return (
        f"Breadcrumb (context only — do not include in output): {breadcrumb}\n\n"
        f"Text:\n{full_text}\n\n"
        "1. Rewrite the section title as a 4–8 word information-dense index anchor "
        "(do not repeat the breadcrumb path).\n"
        f"2. {_PHRASE_PROMPT}"
    )


def make_intermediate_topics_prompt(
    node_title: str,
    children: list[Node],
    breadcrumb: str,
) -> str:
    """Prompt for generating (title, topics) for a non-leaf from its children's summaries."""
    child_block = "\n".join(f"- {c.title}: {c.topics}" for c in children)
    return (
        f"Breadcrumb (context only — do not include in output): {breadcrumb}\n\n"
        f"Section: {node_title}\n\n"
        "Sub-sections covered:\n"
        f"{child_block}\n\n"
        "Synthesise the index entry for this section.\n"
        "1. Rewrite the section title as a 4–8 word information-dense index anchor "
        "(do not repeat the breadcrumb path).\n"
        f"2. {_PHRASE_PROMPT}"
    )


def make_split_prompt(title: str, content: str, breadcrumb: str) -> str:
    """Prompt for identifying semantic sub-section boundaries within an oversized node."""
    return (
        f"Breadcrumb (context only — do not include in output): {breadcrumb}\n\n"
        f"Section: '{title}'\n\n"
        f"Text:\n{content}\n\n"
        "This section is too long to index as a single unit. "
        "Identify 2–6 meaningful semantic sub-sections. For each provide:\n"
        "  title: a 1–8 word index title\n"
        "  start: the first 50 characters of that sub-section, copied verbatim from the text\n"
        f"  topics: {_PHRASE_PROMPT}\n"
        "The first sub-section MUST start at the very beginning of the text. "
        "Sub-sections must be exhaustive and contiguous."
    )


def make_merge_prompt(a_title: str, a_repr: str, b_title: str, b_repr: str) -> str:
    """Prompt for deciding whether two adjacent leaf nodes should be merged."""
    return (
        f"Section A — '{a_title}':\n{a_repr}\n\n"
        f"Section B — '{b_title}':\n{b_repr}\n\n"
        "Should these two consecutive sections be merged into one index entry? "
        "Merge ONLY if they cover the same specific topic and a reader looking for "
        "either topic would naturally expect to find them together."
    )


def make_select_prompt(outline: str, question: str) -> str:
    """Prompt for step 1 of query: selecting relevant leaf node IDs from the outline."""
    return (
        f"OUTLINE:\n{outline}\n\n"
        f"QUESTION: {question}\n\n"
        "Select leaf section IDs needed to answer the question. "
        "Leaf = no '[+N children]' annotation. "
        "Return JSON: selected_ids (array), reasoning (one sentence)."
    )


def make_route_section_prompt(level1_outline: str, question: str) -> str:
    """Stage 1 of hierarchical selection: route question to top-level sections.

    Recall-oriented: false positive costs one extra call; false negative loses the answer.
    """
    return (
        f"SECTIONS:\n{level1_outline}\n\n"
        f"QUESTION: {question}\n\n"
        "Select top-level section IDs likely to contain the answer. "
        "Err inclusive: missing the right section is worse than one extra. "
        "Return JSON: selected_ids (array), reasoning (one sentence)."
    )


def make_discriminate_prompt(
    question: str,
    parent_summaries: list,   # list of (id, title, topics) tuples
    children_outline: str,
    prior_reasoning: str,
) -> str:
    """Stage 2+ of hierarchical selection: select specific subsections within routed sections.

    Recall-oriented: topic descriptions are lossy; err inclusive rather than miss content.
    """
    parent_block = "\n".join(
        f"  [{pid}] {ptitle}: {ptopics}"
        for pid, ptitle, ptopics in parent_summaries
    )
    return (
        f"PARENT SECTION(S):\n{parent_block}\n"
        f"Routing reasoning: {prior_reasoning}\n\n"
        f"SUBSECTIONS:\n{children_outline}\n\n"
        f"QUESTION: {question}\n\n"
        "Skip items marked '[+N children]' — expanded in a later step.\n"
        "Select subsections whose full text is needed to answer the question. "
        "Err inclusive: missing relevant content is worse than one extra section. "
        "Return JSON: selected_ids (array), reasoning (one sentence)."
    )


def make_synthesize_prompt(question: str, sections_text: str) -> str:
    """Prompt for step 2 of query: synthesising an answer from retrieved section text.

    Three-step structure forces explicit extraction of conditional clauses before
    producing the final answer, preventing silent drop of if/unless/except clauses.
    """
    return (
        f"QUESTION: {question}\n\n"
        f"SECTIONS:\n{sections_text}\n\n"
        "Answer using ONLY the sections above. Three labeled steps:\n\n"
        "1. CORE RULE: Primary directive, 1-2 sentences. Cite [section_id].\n"
        "2. EXCEPTIONS AND CONDITIONS: Every if/unless/except/provided-that/only-if clause, "
        "one per bullet. 'None.' if absent.\n"
        "3. FINAL ANSWER: Direct answer combining 1+2. Cite [section_id] per claim.\n\n"
        "If no answer in sections: 'The provided sections do not answer this question.'"
    )


def make_route_prompt(routing_outline: str, question: str) -> str:
    """Prompt for multi-doc routing: select which document(s) to search."""
    return (
        f"DOCUMENTS:\n{routing_outline}\n\n"
        f"QUESTION: {question}\n\n"
        "Select 1–2 document IDs most likely to contain the answer. "
        "Select 2 only if the question requires content from both. "
        "Return JSON: selected_doc_ids (array), reasoning (one sentence)."
    )
