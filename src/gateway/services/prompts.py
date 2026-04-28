# Canned user-facing reply strings. All user-visible answer text lives here.

OUT_OF_SCOPE_REPLY = (
    "I can only answer questions about school policies and procedures. "
    "Please ask me about school rules, staff responsibilities, student welfare, "
    "or administrative operations."
)

UNDERSPECIFIED_CLARIFICATION_TEMPLATE = (
    "To answer this, I need to know: {missing_variable}. Could you tell me?"
)

OVERSPECIFIED_NOTE = (
    "Your question was very specific, so I looked up a more general answer. "
    "If you think I've made a mistake with this generalization, please say so "
    "and I'll try to answer your original question.\n\n"
)

BROAD_QUERY_PREFIX = (
    "Your question covers several school policy areas. "
    "Here's a high-level overview:\n\n"
)

NO_EVIDENCE_REPLY = (
    "Your question is about a school topic, but I don't have specific "
    "documentation to answer it from the knowledge base. "
    "Please contact the school office directly for this information."
)


# LLM prompt constructors

def gate3_fallback_prompt(query: str) -> str:
    return (
        "You are a helpful assistant for a school information system.\n\n"
        "A parent asked the following question:\n"
        f'"{query}"\n\n'
        "The assistant initially flagged this as outside the scope of the school knowledge base. "
        "The parent explicitly asked to search anyway, so a search was performed. "
        "The search returned no relevant documentation.\n\n"
        "Acknowledge that the search came up empty — do not answer from general knowledge. "
        "Instead, offer to look up who the right contact person at the school is for this topic. "
        "Keep the response concise and warm."
    )
