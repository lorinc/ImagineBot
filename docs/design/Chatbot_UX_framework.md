# UX framework for RAG-supported Chatbots

I reviewed current guidance from Microsoft Copilot Studio, Google Dialogflow CX, OpenAI’s prompt guidance, and Azure/Vertex RAG documentation. The consistent pattern is not “write better answers”; it is “design a tighter decision policy”: define the assistant’s remit, force grounding to verifiable school sources, ask the fewest clarifying questions needed, and evaluate the system on groundedness, relevance, and completeness rather than raw answer rate. ([Microsoft Learn][1])

The most useful mental model is a state machine with five gates:

1. Is this topic allowed?
2. Is the question clear enough?
3. Do the retrieved documents actually support an answer?
4. Does this require single-hop lookup or multi-hop synthesis?
5. Can the bot complete the turn now, or should it recover, abstain, or hand off?

That framing matters because “out of scope,” “in scope but unsupported,” “ambiguous,” and “system failure” are different UX problems and should not collapse into the same fallback. Microsoft explicitly separates topic design, ambiguity handling, and escalation; OpenAI’s guardrails guidance similarly treats off-topic detection as a distinct control path. ([Microsoft Learn][1])

For a parent-facing school bot, start with the contract. Define the whitelist as jobs, not subjects: informational questions, task-completion questions, and troubleshooting questions that parents actually ask. Also define the negative space: what the bot must not do, what sources it may use, and when it must escalate. Microsoft’s topic-design guidance recommends starting from the user’s tasks, creating explicit topics for ambiguous openers such as “I need help,” and asking the fewest questions necessary to route correctly. If you are building a document-grounded bot, Azure’s “limit responses to your data” setting is the right conceptual default: the assistant should try to rely on your documents rather than silently filling gaps from general model knowledge. ([Microsoft Learn][1])

From there, treat every incoming message with three separate classifiers before you generate prose.

First: scope classification. “Not whitelisted” should be handled as a boundary decision, not a retrieval failure. The response pattern should be: state the boundary, frame the bot’s supported remit, and redirect to the nearest supported path. Do not partially answer from model memory and then add a disclaimer afterward; for a school assistant, that blurs institutional authority. OpenAI’s guardrails guidance explicitly recommends topical guardrails for off-topic questions, and Azure’s document-bounded mode exists precisely to prevent answers that drift beyond the approved source base. ([OpenAI Developers][2])

Second: ambiguity classification. Ask a follow-up only when the answer would materially differ depending on the interpretation. Good reasons to clarify are: multiple plausible intents, a missing slot that changes the answer, or a high-stakes branch such as one policy versus another. Bad reasons are: the bot is merely uncertain in a vague way, or it is asking for confirmation it does not need. Microsoft’s disambiguation guidance says clarifying questions are for similar or unclear intents, and Google advises that agents should guide the conversation while avoiding multiple questions at once. Microsoft’s topic guidance also says to define the fewest number of questions needed to understand the situation. So the rule is: one targeted disambiguator, one missing variable, one turn at a time. ([Microsoft Learn][3])

Third: evidence classification. Distinguish “not found in docs” from “retrieval probably failed.” If the question is in scope but the retrieved evidence is weak, contradictory, or absent, the bot should abstain from asserting facts. Both Google and Microsoft frame grounded generation as connecting output to verifiable sources, and Azure’s RAG evaluation guidance treats groundedness, relevance, and completeness as distinct qualities. Also, some “I don’t know” answers are not UX failures at all; they are retrieval-design failures caused by query quality, chunking, strictness, or too few retrieved documents. Microsoft’s retrieval guidance recommends avoiding generic queries, including as much context as possible, and not capping results too tightly; Azure’s “use your data” docs note that excessive abstention can come from chunk size or retrieval settings. ([Google Cloud Documentation][4])

That leads to a practical distinction you should enforce in UX copy, even if users never see the machinery:

If the topic is not allowed: respond with a scope boundary.
If the topic is allowed but evidence is missing: respond with a verification boundary.
If the topic is allowed and evidence exists but the question is underspecified: respond with a clarification request.

Those are three different user experiences. If you merge them into one generic fallback, parents will interpret the bot as erratic rather than constrained.

On follow-up questions, use a strict threshold: ask only when the follow-up improves answer correctness more than it increases conversational cost. In a school context, that usually means asking only for the minimum routing variable: school level, campus, student status, academic year, transport option, etc. Google’s guidance to avoid asking multiple questions in one turn is especially important here because parents often answer only one part of a compound prompt, which creates brittle state. ([Google Cloud Documentation][5])

On multi-hop reasoning, do not default to it. Microsoft’s orchestration guidance says to use the lowest level of complexity that reliably meets the requirement. A single lookup is enough when one chunk or one policy page answers the question directly. Multi-hop is warranted when the answer requires combining facts across documents or across sections of one document: policy plus exception, calendar plus eligibility rule, fee plus waiver condition, procedure plus deadline, or comparison across campuses/grade bands. OpenAI’s guidance notes that some assistants are built for evidence-rich multi-step workflows, and OpenAI’s temporal retrieval cookbook explicitly calls out multi-hop retrieval and the importance of data freshness. ([Microsoft Learn][6])

When you do need multi-hop, the process should be explicit:

decompose the parent question into subquestions;
retrieve separately for each subquestion;
extract only the claims supported by documents;
reconcile conflicts by source priority or freshness;
answer from the intersection, not from inference gaps.

The UX consequence is important: the bot should not expose chain-of-thought, but it should expose the structure of certainty. Parents do not need to see your reasoning steps; they do need to understand whether the answer was directly found, synthesized across documents, or blocked by missing evidence.

On session quota, timeouts, and retries: treat them as execution failures, not comprehension failures. Google’s Dialogflow guidance recommends maintaining an error counter and capping retries rather than looping indefinitely, and Microsoft’s handoff guidance emphasizes passing conversation history and variables to the live agent. So the UX pattern should be: preserve state, say what step failed, avoid repeating already-collected information, and offer either a resumable next step or a human handoff with context. If a quota is hit, the bot should summarize completed progress and carry forward the resolved variables so the next turn or the human agent does not restart from zero. ([Google Cloud Documentation][5])

For evaluation, do not score the bot mainly on “answered vs not answered.” Use at least these dimensions: groundedness (did it stay within the documents), relevance (did it address the actual parent question), completeness (did it omit a critical condition), ambiguity handling (did it ask only when necessary), and handoff quality (did it transfer context cleanly). Microsoft’s RAG evaluators define groundedness, relevance, and response completeness in exactly these terms, and NIST’s AI RMF argues for structured risk management and operational evaluation rather than one-off lab impressions. ([Microsoft Learn][7])

A compact checklist for your design review:

* Have we defined the bot’s remit as a finite set of parent jobs, plus explicit non-goals? ([Microsoft Learn][1])
* Does every turn pass through separate scope, ambiguity, and evidence checks before answer generation? ([Microsoft Learn][3])
* In doc-grounded mode, will the bot abstain rather than supplement from model knowledge when evidence is missing? ([Microsoft Learn][8])
* Do follow-up questions collect only the minimum variable needed, one question at a time? ([Google Cloud Documentation][5])
* Do we distinguish retrieval miss from true documentation gap before saying “not found”? ([Microsoft Learn][9])
* Do we trigger multi-hop only for cross-document or cross-condition questions, not for every query? ([Microsoft Learn][6])
* Are retries capped, and does failure preserve state for resume or handoff? ([Google Cloud Documentation][5])
* Are we evaluating groundedness, relevance, and completeness separately? ([Microsoft Learn][7])

If you want the next step, I can turn this into an actual conversation policy spec: a turn-by-turn decision tree for your RAG bot.

[1]: https://learn.microsoft.com/en-us/microsoft-copilot-studio/guidance/defining-chatbot-topics "Begin the agent topic design process - Microsoft Copilot Studio | Microsoft Learn"
[2]: https://developers.openai.com/cookbook/examples/how_to_use_guardrails/ "How to implement LLM guardrails"
[3]: https://learn.microsoft.com/en-us/microsoft-copilot-studio/guidance/cux-disambiguate-intent "Disambiguate customer intent - Microsoft Copilot Studio | Microsoft Learn"
[4]: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/grounding/ground-responses-using-rag "Ground responses using RAG  |  Generative AI on Vertex AI  |  Google Cloud Documentation"
[5]: https://docs.cloud.google.com/dialogflow/cx/docs/concept/agent-design "General agent design best practices  |  Dialogflow CX  |  Google Cloud Documentation"
[6]: https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/ai-agent-design-patterns "AI Agent Orchestration Patterns - Azure Architecture Center | Microsoft Learn"
[7]: https://learn.microsoft.com/en-us/azure/foundry/concepts/evaluation-evaluators/rag-evaluators "Retrieval-Augmented Generation (RAG) Evaluators for Generative AI - Microsoft Foundry | Microsoft Learn"
[8]: https://learn.microsoft.com/en-us/azure/foundry-classic/openai/concepts/use-your-data "Using your data with Azure OpenAI in Microsoft Foundry Models (classic) - Microsoft Foundry (classic) | Microsoft Learn"
[9]: https://learn.microsoft.com/en-us/microsoft-365-copilot/extensibility/api/ai-services/retrieval/overview "Microsoft 365 Copilot Retrieval API Overview | Microsoft Learn"

