## I want the indexer to follow this protocol:

1. Parse the markdown, create the initial tree from the headers, storing the line number of each header
2. Find the increments on this line number series, that are bigger than the max allowed chunk size
3. Identify semantic sub-topics in these oversized chunks (for this work, LLM must receive the `document name ... H1 ... Hn` breadcrumb information, so it has some high-level context), and update the tree. Because the LLM is already reading the whole chunk, it must generate the title and summary for those nodes. If generation happens in a sub-process, pass down the breadcrumb context in addition to the to-be-summarized text to the sub-process.
4. Repeat step 3, until no oversized chunks remain.
5. Create sub-headers, so that all content is inside an end node. I.e. {H2 ... content ... H3 ... content ... H3 content} => {H2 ... no content! ... H3 ... content ... H3 ... content ... H3 content}. For this, the H2 core content (excluding sub-topics!) must be read, titled, summarized.
6. Create titles and summaries for those END nodes, that are still not processed
7. Thin the tree. Merge end nodes, that meet all this 3 criteria: below min threshold, consecutive, semantically coherent. Can merge too small nodes into normal ones, as long as the combined size is below max threshold, and the semantic similarity and consecutive checks pass. Merges must stay within branch: can not merge a H3 into another H3 in a different H2.
8. ONLY NOW rewrite the titles and the description of intermediary and top nodes, bottom-up (so H1 is the last to be written), using ONLY the node information of their sub nodes. Not the corpus, the title+description.
9. validate the tree

If done well, text has been read only once, avary prompt received only, what they needed to do the task, yet the tree is complete and correct.

## Summary wording must change dramatically too:
* the LLM must be aware, that the goal is building a rich TOC, not a prosaic summary. It should be a list topics, not sentences. Both the node title and the description must be worded as "semantic contents list", not a real summary. The purpose is helping LLM reasoning to find relevant nodes based on this text, but never answering the question. Topics, not answers.
* LLM must know the `doc > H1 > ... > Hn` breadcrumb, when writing the title and description of a node, but provided as context, not something to include in the title or description.
* The titles start as "working title" from the original markdown headers, but when a node is processed, titles must be rewritten to better reflect the TOC/index nature of the tree. E.g. instead of "# Welcome to the 2026 school year", it should be something like "School Values and High level goals for 2026"