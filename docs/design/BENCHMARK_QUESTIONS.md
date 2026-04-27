# Benchmark Questions

**Scope:** candidate question set for the eval harness. All candidates go to `tests/eval/golden.jsonl`.
Empirical pass/fail will determine which catch real pipeline failures vs. which are redundant or trivially easy.

**Source verification status** is noted per question:
- `VERIFIED` — answer text confirmed against `data/pipeline/latest/02_ai_cleaned/`
- `TBD` — candidate constructed from L1 outlines; source passage must be located before golden.jsonl entry is treated as a real signal

**Relationship to BOT_QA.md:** BOT_QA.md owns the taxonomy and generation workflow.
This file owns the candidate set and tracks verification status. Do not modify BOT_QA.md from here.

---

## Family: Regression

*Pin the query string verbatim from HEURISTICS.log. Re-run on every corpus or prompt change.*

### rg-001
```json
{
  "id": "rg-001",
  "query": "What happens after a fire drill?",
  "expected_facts": ["headcount", "register"],
  "expected_source_ids": ["en_policy3_health_safety_reporting"],
  "must_not_contain": [],
  "skip": true,
  "notes": "[answerable][regression] known past failure — fire drill query from HEURISTICS.log; pin verbatim"
}
```
**Source verification:** UNVERIFIABLE — policy3 §1 (Fire and Emergency Policy) contains §1.4–§1.7 on evacuation procedures but does not include "headcount" or "register" steps. Policy3 §2.4 refers to a "separate Fire Safety Policy" that is not indexed in the corpus. Skip in eval until source doc is located.

---

## Family: Direct Fact Lookup

*Single-document, single-section. Establishes baseline pass rate.*

### fd-001
```json
{
  "id": "fd-001",
  "query": "What is the fee for a late pick-up between 5:16 pm and 5:30 pm?",
  "expected_facts": ["10 €", "10€"],
  "expected_source_ids": ["en_family_manual_24_25"],
  "must_not_contain": ["5 €", "20 €"],
  "notes": "[answerable][direct-fact] late pickup fee tier 2; fee table in §2.2; must_not_contain distinguishes from tier 1/3"
}
```
**Source verification:** VERIFIED — `en_family_manual_24_25.md` §2.2: "From 5:16 pm to 5:30 pm – 10 € per late pick-up"

### fd-002
```json
{
  "id": "fd-002",
  "query": "From what point during the school year do late arrivals start incurring a fee?",
  "expected_facts": ["fifth", "5th"],
  "expected_source_ids": ["en_family_manual_24_25"],
  "must_not_contain": ["first", "third"],
  "notes": "[answerable][direct-fact] late arrival fee threshold; §2.2 late arrivals paragraph"
}
```
**Source verification:** VERIFIED — §2.2: "Starting from the fifth late arrival during the school year, a fee of €5 per late arrival will be charged"

### fd-003
```json
{
  "id": "fd-003",
  "query": "How long must a child be symptom-free before returning to school after a fever?",
  "expected_facts": ["24 hours", "24h"],
  "expected_source_ids": ["en_family_manual_24_25"],
  "must_not_contain": ["48 hours", "48h"],
  "notes": "[answerable][direct-fact] illness exclusion period; §9.1; Spanish Paediatrics Association recommendation"
}
```
**Source verification:** VERIFIED — §9.1: "minimum of 24 hours have passed since the last episode of fever, vomiting, or diarrhea"

### fd-004
```json
{
  "id": "fd-004",
  "query": "What time does the school bus begin its route at the end of the school day?",
  "expected_facts": ["4:50", "16:50"],
  "expected_source_ids": ["en_family_manual_24_25"],
  "must_not_contain": ["4:40", "4:55"],
  "notes": "[answerable][direct-fact] bus departure time; §22; must_not_contain distinguishes from student dismissal window"
}
```
**Source verification:** VERIFIED — §22: "At 4:50 p.m. the bus will begin its route"

### fd-005
```json
{
  "id": "fd-005",
  "query": "By what time must a family notify the school if their child will not be taking the bus that day?",
  "expected_facts": ["2:30", "14:30"],
  "expected_source_ids": ["en_family_manual_24_25"],
  "must_not_contain": ["4:30", "16:30"],
  "notes": "[answerable][direct-fact] bus change notification deadline; §22"
}
```
**Source verification:** VERIFIED — §22: "must be communicated before 2:30 p.m."

---

## Family: Conditional / If-Then Policy

*Answer changes based on a condition stated in the same section or nearby parent. Condition is not named in the question.*

### cond-001
```json
{
  "id": "cond-001",
  "query": "Does a child with a cold need a doctor's prescription before the school will administer their medication?",
  "expected_facts": ["oral", "prescription", "written authorisation"],
  "expected_source_ids": ["en_family_manual_24_25"],
  "must_not_contain": ["any medication", "without prescription"],
  "notes": "[answerable][conditional] medication administration rule; only oral medication, always with medical prescription AND written parental authorisation; §9.1"
}
```
**Source verification:** VERIFIED — §9.1: "our school will only administer oral medications, always with a medical prescription and written authorisation from the families"

### cond-002
```json
{
  "id": "cond-002",
  "query": "What documentation is required for the school to accommodate a student's gluten-free diet?",
  "expected_facts": ["certificate", "allergologist", "gastroenterologist"],
  "expected_source_ids": ["en_policy3_health_safety_reporting"],
  "must_not_contain": ["no documentation required", "parent request"],
  "notes": "[answerable][conditional] special diet certificate requirement; food policy §4.2/4.3; medical diets require specialist certificate"
}
```
**Source verification:** VERIFIED — policy3 §4.2: "special diet due to health (gluten-free, specific food allergies, with a certificate from allergologists or gastroenterologists)"

### cond-003
```json
{
  "id": "cond-003",
  "query": "If a parent sends a note explaining their child's absence, is that absence automatically classified as authorised?",
  "expected_facts": ["only the school", "school can make", "parents do not have this authority"],
  "expected_source_ids": ["en_policy5_code_of_conduct"],
  "must_not_contain": ["parent note is sufficient", "automatically authorised"],
  "notes": "[answerable][conditional] absence authorisation power; §3.4a; only the school can authorise — parental support alone is insufficient"
}
```
**Source verification:** VERIFIED — policy5 §3.4a: "Only the school can make an absence authorised. Parents do not have this authority."

---

## Family: Exception Omission

*Standard answer is present but an exception clause that limits its scope is silently dropped.*

### ex-001
```json
{
  "id": "ex-001",
  "query": "Will the school always inform a family when their child is involved in a drug-related incident?",
  "expected_facts": ["unless", "heighten the risk", "rare circumstances"],
  "expected_source_ids": ["en_policy5_code_of_conduct"],
  "must_not_contain": ["always inform", "will always notify"],
  "notes": "[answerable][exception-omission] drug incident parental notification; §7.12 has 'unless in very rare circumstances this would heighten the risk to the child'; bare rule omits this exception"
}
```
**Source verification:** VERIFIED — policy5 §7.12: "The school will inform parents and carers of any drug-related incidents involving their own child, unless in very rare circumstances this would heighten the risk to the child."

### ex-002
```json
{
  "id": "ex-002",
  "query": "What are the available pick-up times during the school day?",
  "expected_facts": ["12:00", "2:30", "4:00"],
  "expected_source_ids": ["en_family_manual_24_25"],
  "must_not_contain": ["any time", "whenever"],
  "notes": "[answerable][exception-omission] early pickup times are restricted to three fixed slots; standard answer may omit that NO OTHER times are accepted; §2.2"
}
```
**Source verification:** VERIFIED — §2.2: "the only available pick-up times are as follows: 12:00 p.m. / 2:30 p.m. / 4:00 p.m."

---

## Family: Polysemic Routing Trap

*Same keyword appears under multiple headings with different procedures. Correct answer is in the less obvious section.*

### poly-001
```json
{
  "id": "poly-001",
  "query": "How should a staff member formally raise a concern about a colleague's conduct toward a child?",
  "expected_facts": ["Whistleblowing Channel", "website", "confidential"],
  "expected_source_ids": ["en_policy3_health_safety_reporting"],
  "must_not_contain": ["referral form", "behavioural incident"],
  "notes": "[answerable][polysemic] term: 'reporting'; decoy: 'Student Behavior Incident Reporting' (family manual); correct: 'Whistleblowing Channel Policy' (policy3 §6); concern about colleague routes to wrong doc"
}
```
**Source verification:** VERIFIED — policy3 §6: Whistleblowing Channel accessible on corporate website, "treated with utmost confidentiality", reports staff irregularities. Decoy: family manual "a referral form… in the event of any incident related to a student's behavioural incident" (student misconduct, not staff).

### poly-002
```json
{
  "id": "poly-002",
  "query": "What rights do parents have to request access to their child's personal data held by the school?",
  "expected_facts": ["right to access", "obtain information", "copy", "rectification", "erasure"],
  "expected_source_ids": ["en_policy3_health_safety_reporting"],
  "must_not_contain": ["not available to parents", "parents' meetings"],
  "notes": "[answerable][polysemic] term: 'data protection'; decoy: 'School Confidentiality Policy and Data Protection' (policy1); correct: 'Data Protection Privacy Policy Overview' (policy3 §5)"
}
```
**Source verification:** VERIFIED — policy3 §5.12: Access right — "you can obtain information regarding the processing of your personal data and a copy of it"; also lists Rectification, Erasure, Restriction, Opposition, Portability. Decoy: policy1 §2 Confidentiality Policy: "They are not available to parents to access, although parents may look at their own child's files on request during parents' meetings."

### poly-003
```json
{
  "id": "poly-003",
  "query": "What must be completed before taking a group of students on a school excursion?",
  "expected_facts": ["risk assessment", "consent form", "family consent", "Phidias"],
  "expected_source_ids": ["en_policy4_trips_and_outings"],
  "must_not_contain": ["annually", "annual"],
  "notes": "[answerable][polysemic] term: 'safety before leaving premises'; decoy: 'Comprehensive School Health Safety Policy' (policy3); correct: 'School Outings' (policy4); 'safety' vocabulary routes to H&S policy"
}
```
**Source verification:** VERIFIED — policy4 §5: "A thorough risk assessment must be completed for every outing"; "Family consent is required for all students"; "Consent forms must detail the purpose, location, itinerary, transportation… shared with families through Phidias." Decoy: policy3 §1 describes annual H&S risk assessment (not trip-specific); must_not_contain "annually"/"annual" catches the general assessment wording.

### poly-004
```json
{
  "id": "poly-004",
  "query": "Are parents permitted to take photos or videos of students during school performances and events?",
  "expected_facts": ["consent", "share images", "families", "specific authorization", "media"],
  "expected_source_ids": ["en_family_manual_24_25"],
  "must_not_contain": ["prohibited from photographing", "prohibited from recording"],
  "notes": "[answerable][polysemic] term: 'photographing students'; decoy: 'School Camera Mobile Device Policy' (policy2); correct: 'Student Photos and Media Policy' (family manual §24); camera vocabulary routes to tech policy"
}
```
**Source verification:** VERIFIED — family manual §24: all families consent to internal image sharing; for media use (press, website, social media) "a specific authorization will be required". Decoy: policy2 §10: "Parents are prohibited from photographing or recording pupils during events unless specified by the school" — the prohibition is for unauthorised photography, not the full answer about consent conditions.

### poly-005
```json
{
  "id": "poly-005",
  "query": "What is the correct way for a parent to inform the school that their child will be absent that day?",
  "expected_facts": ["Phidias", "guide", "tutor"],
  "expected_source_ids": ["en_family_manual_24_25"],
  "must_not_contain": ["school office", "first morning of absence"],
  "notes": "[answerable][polysemic] term: 'absence notification'; decoy: 'School Attendance Policy Overview' (policy5); correct: 'School-Family Communication Channels' / §2.2 (family manual); procedure lives in family manual not attendance policy"
}
```
**Source verification:** VERIFIED — family manual §2.2: "By sending a Phidias message to the administration and the student's Guide or tutor." Decoy: policy5 §3.1 says "Contacting the school office on the first morning of absence" — different channel, partial overlap. must_not_contain catches the policy5 wording.

---

## Family: L1 Vocabulary Mismatch

*Correct answer is in a document whose L1 title does not match query vocabulary. Stage 1 routes to wrong document.*

### l1-001
```json
{
  "id": "l1-001",
  "query": "What procedure applies when a student is found to be carrying a weapon on school grounds?",
  "expected_facts": ["immediate action", "searches", "confiscation", "reporting to authorities"],
  "expected_source_ids": ["en_policy5_code_of_conduct"],
  "must_not_contain": ["Designated Safeguarding Lead", "DSL", "child protection"],
  "notes": "[answerable][l1-mismatch] query vocabulary 'weapon' / 'threat' matches 'Comprehensive Child Protection Policy' (policy1 L1) but the weapons policy lives in 'Code of Conduct' (policy5 §8); child safety surface match routes wrong"
}
```
**Source verification:** VERIFIED — policy5 §8: "Staff will take immediate action upon suspicion or discovery of a weapon, including searches, confiscation, and necessary reporting to authorities." Decoy: policy1 uses DSL / safeguarding lead language for child harm concerns; must_not_contain catches a policy1-sourced answer.

### l1-002
```json
{
  "id": "l1-002",
  "query": "What online safety topics must the school teach students as part of the curriculum?",
  "expected_facts": ["validation of online information", "recognition of online risks", "privacy and copyright"],
  "expected_source_ids": ["en_policy2_technology"],
  "must_not_contain": ["child protection", "safeguarding", "DSL"],
  "notes": "[answerable][l1-mismatch] query: 'online safety' + 'curriculum'; decoy: 'Comprehensive Child Protection Policy' (policy1, L1 matches 'child safety') rather than policy2 'Online Safety Policy and Education' section; NOTE: curriculum content is in §9 not §10"
}
```
**Source verification:** VERIFIED — policy2 §9 (Online Safety and E-Safety): "e-safety curriculum teaches pupils… validation of online information, recognition of online risks, and respect for privacy and copyright." Decoy: policy1 discusses online safety in safeguarding/child protection context using DSL language.

---

## Family: Parent-Context Loss

*Answer correct only if qualifying condition from parent node is known. Child node selected without parent.*

### pcl-001
```json
{
  "id": "pcl-001",
  "query": "What protection does a staff member have against retaliation after submitting a whistleblowing report?",
  "expected_facts": ["without fear of dismissal", "retaliation", "confidentiality"],
  "expected_source_ids": ["en_policy3_health_safety_reporting"],
  "must_not_contain": ["no specific protection", "TBD — verify procedure-only answer from a child subsection"],
  "notes": "[answerable][parent-context-loss] retaliation protection stated in §6.1 Scope intro only; subsections §6.4-6.11 describe procedures without repeating the protection guarantee; retrieval of procedural subsection alone misses the guarantee"
}
```
**Source verification:** VERIFIED — policy3 §6.1: "without fear of dismissal or other forms of retaliation. The information provided will be treated with utmost confidentiality." Confirm subsections §6.4+ do not repeat this.

---

## Family: Procedure Truncation

*Multi-step procedure spans a heading boundary. Stage 2 selects first node; later steps silently omitted.*

### pt-001
```json
{
  "id": "pt-001",
  "query": "What are all the steps staff must take during and after a fire evacuation?",
  "expected_facts": ["TBD — verify step from second heading in policy3 §1 fire procedure"],
  "expected_source_ids": ["en_policy3_health_safety_reporting"],
  "must_not_contain": ["TBD — phrasing that presents an early step as the final step"],
  "skip": true,
  "notes": "[answerable][procedure-truncation] fire evacuation procedure in policy3 §1; verify steps span multiple headings; expected_facts must come from a step only in the later heading"
}
```
**Source verification:** UNVERIFIABLE — policy3 §1 (Fire and Emergency Policy) does not contain a numbered multi-step staff fire procedure; §1.4–§1.7 cover visitors/routes/equipment only. Policy3 §2.4 references a "separate Fire Safety Policy" not indexed in corpus. Skip until that document is located.

---

## Family: Cross-Doc Routing Miss

*Complete answer requires combining content from two documents. Stage 1 routes to only one.*

### xd-001
```json
{
  "id": "xd-001",
  "query": "What rules govern how students travel to and from a school excursion, and what safety checks must the school complete beforehand?",
  "expected_facts": [
    "risk assessment", "consent",
    "group", "transport chosen by the school"
  ],
  "expected_source_ids": ["en_policy4_trips_and_outings", "en_family_manual_24_25"],
  "must_not_contain": ["individually", "own transport"],
  "notes": "[answerable][cross-doc] policy4 owns staff-facing safety requirements (risk assessment, ratios, supervision); family manual §21 owns family-facing rules (group travel, school-chosen transport, must start day at school); neither alone gives the complete answer"
}
```
**Source verification:** VERIFIED — family manual §21: "children must leave and return to school as a group, using the transport chosen by the school." Policy4: "thorough risk assessment must be completed for every outing"; "family consent is required"; "appropriate staff-to-student ratio must be maintained."

---

## Family: Version Authority

*`en_family_manual_24_25` and `es_family_manual_25_26` indexed together. 25/26 is authoritative.*

**Research note:** After corpus comparison, both manuals contain nearly identical policy values (fees, hours, exclusion periods, timetables). Version-authority questions below test that the system retrieves from 25/26 and correctly identifies the source — even where values are the same, source attribution matters. No factual difference was found for dual-version synthesis blend; va-003 tests the one verified discrepancy.

### va-001
```json
{
  "id": "va-001",
  "query": "What is the late pick-up fee for a collection between 5:16 pm and 5:30 pm?",
  "expected_facts": ["10 €", "10€"],
  "expected_source_ids": ["en_family_manual_24_25"],
  "must_not_contain": ["5 €", "20 €"],
  "notes": "[answerable][version-authority] same fact exists in both manuals; tests that system cites 25/26 (Spanish) or 24/25 as source — currently both indexed; will become meaningful when routing between versions is implemented"
}
```
**Source verification:** VERIFIED — same value in both manuals (€10 for 5:16-5:30 tier).

### va-002
```json
{
  "id": "va-002",
  "query": "What are the available timetable options for a student in Children's House Nursery?",
  "expected_facts": ["Early Bird", "Reduced Day", "Full Day"],
  "expected_source_ids": ["en_family_manual_24_25"],
  "must_not_contain": ["Morning Session"],
  "notes": "[answerable][version-authority] Nursery timetable: Early Bird ✓, Morning Session ✗, Reduced Day ✓, Full Day ✓; same in both manuals; must_not_contain 'Morning Session' which is only available for Infant Community"
}
```
**Source verification:** VERIFIED — both manuals show same timetable table: Nursery has x for Morning Session.

---

## Family: Dual-Version Synthesis Blend

*Stage 3 blends conflicting content from both manuals rather than deferring to 25/26.*

### dv-001
```json
{
  "id": "dv-001",
  "query": "Does the change to the school bus departure schedule affect the time buses arrive at stops?",
  "expected_facts": ["minimally", "mínimamente"],
  "expected_source_ids": ["en_family_manual_24_25"],
  "must_not_contain": ["will not affect", "no impact"],
  "notes": "[answerable][dual-version-blend] 24/25 English: 'will NOT affect arrival time at stops'; 25/26 Spanish: 'afectará mínimamente' (will minimally affect); system must prefer 25/26 authoritative statement; must_not_contain catches 24/25 wording"
}
```
**Source verification:** VERIFIED — 24/25 §22: "This change will not affect the arrival time at the stops" | 25/26 §22: "Este cambio afectará mínimamente al horario de llegada a las paradas"

---

## Family: Model Knowledge Supplement

*Corpus gives a school-specific answer that differs from general knowledge. Bot must use corpus value.*

### mk-001
```json
{
  "id": "mk-001",
  "query": "What is the school's late pick-up fee for a collection between 4:55 pm and 5:15 pm?",
  "expected_facts": ["5 €", "5€"],
  "expected_source_ids": ["en_family_manual_24_25"],
  "must_not_contain": ["no charge", "no fee", "free"],
  "notes": "[answerable][model-knowledge-supplement] specific fee amount — bot must cite corpus value, not assume free or apply a different default; §2.2"
}
```
**Source verification:** VERIFIED — §2.2: "From 4:55 pm to 5:15 pm – 5 € per late pick-up"

### mk-002
```json
{
  "id": "mk-002",
  "query": "Does Imagine school require students to wear a uniform?",
  "expected_facts": ["not promote", "does not promote", "no uniform"],
  "expected_source_ids": ["en_family_manual_24_25"],
  "must_not_contain": ["uniform required", "must wear uniform"],
  "notes": "[answerable][model-knowledge-supplement] school explicitly does NOT promote uniform (except PE/excursions); general school expectation is uniform; corpus-specific answer differs; §12"
}
```
**Source verification:** VERIFIED — §12: "we do not promote the use of school uniforms"

---

## Family: Out-of-Corpus

*Topic completely absent from all corpus documents. Scope gate must intercept.*

### ooc-001
```json
{
  "id": "ooc-001",
  "query": "How long does the school retain student personal data after they leave?",
  "expected_facts": ["TBD — verify canned scope boundary response substring"],
  "expected_source_ids": [],
  "must_not_contain": ["7 years", "5 years", "retained for"],
  "notes": "[out-of-corpus] GDPR / data retention periods — not addressed in any corpus document; policy3 §5 mentions data protection privacy policy exists but does not specify retention periods; gate must block"
}
```
**Source verification:** VERIFIED (absence) — policy3 §5 mentions privacy policy URL but contains no retention periods.

### ooc-002
```json
{
  "id": "ooc-002",
  "query": "What is the school's policy on staff annual leave entitlement?",
  "expected_facts": ["TBD — canned boundary response"],
  "expected_source_ids": [],
  "must_not_contain": ["22 days", "30 days", "leave entitlement"],
  "notes": "[out-of-corpus] staff employment terms / HR — entirely absent from corpus; corpus covers student/family-facing policies only"
}
```
**Source verification:** VERIFIED (absence) — no HR/employment content in corpus.

### ooc-003
```json
{
  "id": "ooc-003",
  "query": "What is the school's admissions criteria for secondary students?",
  "expected_facts": ["TBD — canned boundary response"],
  "expected_source_ids": [],
  "must_not_contain": ["exam", "interview", "academic record"],
  "notes": "[out-of-corpus] admissions criteria — not covered in corpus documents; family manual mentions admissions contact but no criteria"
}
```
**Source verification:** VERIFIED (absence) — family manual lists Hernan as admissions contact but contains no selection or entry criteria; no admissions criteria found in policy1–5 either.

---

## Family: In-Scope Undocumented

*Topic within school's remit; related content in corpus; specific fact absent. System must abstain.*

### isd-001
```json
{
  "id": "isd-001",
  "query": "What is the school's procedure when a guide (teacher) is absent and a substitute takes over?",
  "expected_facts": ["TBD — abstention phrase"],
  "expected_source_ids": [],
  "must_not_contain": ["supply teacher", "substitute teacher procedure"],
  "notes": "[in-scope-undocumented] substitute/supply cover procedure — school's remit, but not documented in any corpus doc; corpus mentions 'guides' extensively but no cover procedure"
}
```
**Source verification:** VERIFIED (absence) — policy3 §1.5 mentions "supply staff" only in fire evacuation context; no substitute or cover teacher procedure in any corpus document.

### isd-002
```json
{
  "id": "isd-002",
  "query": "How does the school handle a request to change a student's assigned bus stop?",
  "expected_facts": ["TBD — abstention phrase OR corpus has partial answer"],
  "expected_source_ids": [],
  "must_not_contain": [],
  "notes": "[in-scope-undocumented] bus stop change process — family manual §22 covers exceptional stop changes (same form as day-off exceptions, deadline 2:30 PM before start of year); permanent contract stop change is undocumented; question is ambiguous between the two"
}
```
**Source verification:** PARTIALLY — family manual §22: "This form must be used if your child will not take the bus one day or if there is an exceptional change of stop." Same form and 2:30 PM deadline apply to both day-off and exceptional stop changes. Permanent contract change is undocumented. expected_facts and must_not_contain require further definition once query intent is clarified.

---

## Family: Scope Gate False Positive

*In-scope query with unusual/indirect phrasing that might trigger false scope rejection.*

### sgfp-001
```json
{
  "id": "sgfp-001",
  "query": "My kid throws up at breakfast — when can they come back?",
  "expected_facts": ["24 hours", "24h"],
  "expected_source_ids": ["en_family_manual_24_25"],
  "must_not_contain": ["not covered", "outside my scope"],
  "notes": "[answerable][scope-gate-false-positive] informal colloquial phrasing of illness exclusion query; gate may misclassify 'throws up' / informal register as out-of-scope; must return policy answer not canned boundary"
}
```
**Source verification:** VERIFIED — answer exists in §9.1.

---

## Family: False Presupposition

*Question assumes a rule or penalty exists that does not. System must not fabricate.*

### fp-001
```json
{
  "id": "fp-001",
  "query": "What is the penalty for a student who repeatedly forgets to bring their PE kit?",
  "expected_facts": ["TBD — abstention phrase"],
  "expected_source_ids": [],
  "must_not_contain": ["detention", "written warning", "penalty", "fine"],
  "notes": "[false-presupposition] no penalty schedule for forgotten PE kit exists in corpus; system must abstain, not fabricate a consequence"
}
```
**Source verification:** VERIFIED (absence) — dress code section in family manual and policy5 §2 contain no PE kit or forgotten equipment penalty schedule.

---

## Family: Contact Extraction

*Query asks who to contact. Answer requires naming a specific person or role from the contacts table, not just describing a policy or procedure.*

### ce-001
```json
{
  "id": "ce-001",
  "query": "My son has lost his hoodie. Who should I talk to?",
  "expected_facts": ["María Luisa", "Madhu", "Secretar"],
  "expected_source_ids": ["en_family_manual_24_25"],
  "must_not_contain": ["CH playground", "last Friday"],
  "notes": "[answerable][contact-extraction] query embeds two sub-questions: (1) lost & found policy (location + monthly display), (2) who to contact; contacts table lists María Luisa / Madhu (Secretaries) under 'lost & found'; must_not_contain catches the policy-only failure mode where the pipeline answers (1) and silently drops (2); confirmed real failure from user testing 2026-04-27"
}
```
**Source verification:** VERIFIED — `en_family_manual_24_25.md` contacts table: "lost & found" → **María Luisa / Madhu** Secretaries.

---

## Family: Underspecified

*Missing a required discriminating factor. System must request clarification.*

### us-001
```json
{
  "id": "us-001",
  "query": "What is the supervision ratio for students?",
  "expected_facts": ["TBD — clarification phrase"],
  "expected_source_ids": [],
  "must_not_contain": ["TBD — any specific ratio without clarification"],
  "notes": "[out-of-corpus] supervision ratios are NOT present in corpus for any stage — the 'underspecified' premise fails; corpus only mentions 'appropriate ratio' without specifics (policy4 §5); reclassified as out-of-corpus; expected_facts should be abstention signal"
}
```
**Source verification:** VERIFIED (absence) — no stage-specific supervision ratios found in any corpus document. Policy4 §5 says "an appropriate staff-to-student ratio… must be maintained" without figures. Policy3 §2.4 mentions first-aid ratio only. The discriminating multi-ratio context does not exist in the corpus; category updated from underspecified → out-of-corpus.

---

## Family: Multi-Turn Follow-Up

*Correct answer depends on context from prior turn. System that ignores session context fails.*

### mt-001
```json
{
  "id": "mt-001",
  "prior_turns": [
    {"role": "user", "content": "My daughter is in the Nursery (Casa de Niños)."}
  ],
  "query": "What timetable options are available for her?",
  "expected_facts": ["Early Bird", "Reduced Day", "Full Day"],
  "expected_source_ids": ["en_family_manual_24_25"],
  "must_not_contain": ["Morning Session"],
  "notes": "[answerable][multi-turn] prior turn establishes Nursery stage; Nursery timetable: no Morning Session; without prior turn the query is ambiguous (could be any stage); must_not_contain catches wrong answer for Infant Community"
}
```
**Source verification:** VERIFIED — timetable table in §2.1.

### mt-002
```json
{
  "id": "mt-002",
  "prior_turns": [
    {"role": "user", "content": "My child's medication needs to be given every 6 hours."}
  ],
  "query": "Can the school administer it during the school day?",
  "expected_facts": ["every 8 hours", "adjust", "at home"],
  "expected_source_ids": ["en_family_manual_24_25"],
  "must_not_contain": ["yes, the school will administer", "school will give"],
  "notes": "[answerable][multi-turn] prior turn establishes 6-hour frequency; §9.1 states school only administers if required every 8 or MORE hours; families must adjust 6h schedule to give at home; without prior turn question is answerable in principle, with it becomes a clear NO"
}
```
**Source verification:** VERIFIED — §9.1: "If medication is required every 8 hours or more, families should adjust the schedule to administer it at home."
