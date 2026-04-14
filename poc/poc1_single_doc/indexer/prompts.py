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
        "You are helping answer a question about a school policy document. "
        "Below is an outline of the document: each line is [section_id] Title: topics.\n\n"
        f"OUTLINE:\n{outline}\n\n"
        f"QUESTION: {question}\n\n"
        "Select the section IDs whose full text must be read to answer the question. "
        "IMPORTANT: Only select LEAF nodes — those WITHOUT a '[+N children — do not select]' "
        "annotation. Selecting a parent node delivers its entire subtree and wastes budget. "
        "If a whole section is relevant, select the specific child nodes you need instead. "
        "Be selective — only include sections directly relevant. "
        "Return JSON with:\n"
        "  selected_ids: array of section IDs (exactly as shown in the outline)\n"
        "  reasoning: one sentence explaining why these sections were chosen"
    )


def make_synthesize_prompt(question: str, sections_text: str) -> str:
    """Prompt for step 2 of query: synthesising an answer from retrieved section text."""
    return (
        "Answer the following question using ONLY the document sections provided. "
        "For each claim, cite the section ID in square brackets, e.g. [3.4]. "
        "If the sections do not contain a clear answer, respond: "
        "'The provided sections do not answer this question.'\n\n"
        f"QUESTION: {question}\n\n"
        f"SECTIONS:\n{sections_text}"
    )


def make_route_prompt(routing_outline: str, question: str) -> str:
    """Prompt for multi-doc routing: select which document(s) to search."""
    return (
        "You are routing a question to the relevant school document(s). "
        "Below is a compact outline of each document: L1 section titles and representative topics.\n\n"
        f"DOCUMENTS:\n{routing_outline}\n\n"
        f"QUESTION: {question}\n\n"
        "Select the 1–2 document IDs (exactly as shown in the === header, "
        "e.g. 'en_policy1_child_protection') most likely to contain the answer. "
        "Select 2 only if the question clearly requires content from both. "
        "Return JSON with:\n"
        "  selected_doc_ids: array of document IDs\n"
        "  reasoning: one sentence explaining the choice"
    )
