import json

# Maps span name → display template. None = do not display. Variables reference span["attributes"] keys.
STEP_MESSAGES: dict[str, str | None] = {
    "classify":                    "In scope · specific enough",
    "classify.out_of_scope":       "Out of scope",
    "classify.not_specific":       "In scope · needs more detail",
    "rewrite":                     "Rewritten: ‘{rewritten_query}’",
    "rewrite.skipped":             None,
    "topics":                      "Topics: {topic_labels_short} ({topic_count} total)",
    "breadth.overview":            "Broad query ({topic_count} topics) → overview",
    "breadth.focused":             "Focused query ({topic_count} topics)",
    "knowledge.routing":           "Routing → {doc_titles}",
    "knowledge.selection":         "Selected {chunk_count} chunks: {chunk_summary}",
    "knowledge.synthesis_started": "Sending {chunk_count} chunks ({total_chars} chars) to LLM…",
    "knowledge.synthesis_done":    "Answer synthesized ({answer_chars} chars)",
}


def format_span(span: dict) -> str | None:
    template = STEP_MESSAGES.get(span["name"])
    if not template:
        return None
    try:
        return template.format_map(span["attributes"])
    except KeyError:
        return template
