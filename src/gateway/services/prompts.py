# Canned user-facing reply strings. All user-visible answer text lives here.

OUT_OF_SCOPE_REPLY = (
    "I can only answer questions about school policies and procedures. "
    "Please ask me about school rules, staff responsibilities, student welfare, "
    "or administrative operations."
)

ORIENTATION_RESPONSE = (
    "I'd be happy to help with school information! "
    "Could you be a bit more specific about what you'd like to know? "
    "For example, you could ask about:\n\n"
    "- Daily logistics — drop-off times, attendance, late pick-up\n"
    "- Health & wellbeing — illness rules, allergies, meals\n"
    "- Behaviour & values — expectations, dress code, conflict resolution\n"
    "- Curriculum & learning — how lessons work, assessments, progress reports\n"
    "- Technology — device policies, online safety\n"
    "- Fees & enrolment — payment schedules, what's included\n\n"
    "What would you like to know about?"
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
