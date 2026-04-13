# Iteration 2 — 2026-04-12

## Parameters changed from iteration 1

| Parameter | Iteration 1 | Iteration 2 |
|-----------|------------|------------|
| MAX_NODE_CHARS | 1800 | 5000 |
| MIN_NODE_CHARS | 500 | 1500 |
| Summary length | "1–2 sentences" | budget formula (800–1389 chars) |
| Eval scope | 1 doc, 7 queries | 4 docs, 16 queries |
| MODEL_STRUCTURAL | gemini-2.5-flash | gemini-2.5-flash-lite |

Summary budget formula:
```python
effective = clamp(full_text_char_count, MIN_NODE_CHARS, MAX_NODE_CHARS)
divisor = (3 * MIN_NODE_CHARS + MAX_NODE_CHARS) / TARGET_MIN_SUMMARY_CHARS  # TARGET=800
budget = int((2 * effective + MAX_NODE_CHARS + MIN_NODE_CHARS) / divisor)
# range: 800 chars (min-sized node) → 1389 chars (max-sized node)
```

---

## Run metadata

| Document | Nodes | Build time | Eval run |
|----------|-------|-----------|---------|
| en_policy5_code_of_conduct.md | 104 | 68.4s | 2026-04-12T20:24:00Z |
| en_policy3_health_safety_reporting.md | 80 | 61.6s | 2026-04-12T20:23:09Z |
| en_policy1_child_protection.md | 34 | 41.2s | 2026-04-12T20:23:22Z |
| en_family_manual_24_25.md | 46 | 34.1s | 2026-04-12T20:23:11Z |

---

## Query results

### en_policy5_code_of_conduct.md (104 nodes, avg 10512ms)

| Q | Type | IDs selected | step1 | step2 | total | chars→synth | Result |
|---|------|-------------|-------|-------|-------|------------|--------|
| 1 | lookup | `3` | 3463 | 1302 | 4765 | 13512 | ✅ PASS |
| 2 | procedure | `6`, `6.10`, `6.11.*` (10 nodes) | 3246 | 11116 | 14362 | 36001 | ✅ PASS |
| 3 | procedure | `4`, `4.9`, `4.17` | 2663 | 3127 | 5790 | 28456 | ✅ PASS |
| 4 | lookup | `8`, `8.2`, `8.4` | 1234 | 4527 | 5761 | 11407 | ✅ PASS |
| 5 | lookup | `2.3`, `2.4` | 1857 | 2352 | 4209 | 6616 | ✅ PASS |
| 6 | procedure | `7`, `7.x`, `4.9`, `6.11.x` (11 nodes) | 9932 | 9930 | 19862 | 36472 | ✅ PASS |
| 7 | cross_section | `4`, `5`, `6` | 7271 | 11567 | 18838 | 50863 | ✅ PASS |

Q7 note: correct sections selected, but parent nodes `4/5/6` sent 50,863 chars to synthesis.
This is a precision failure at step 1: the LLM selects coarse parents instead of specific leaves,
causing synthesis explosion. Answer was correct but at 18.8s.

### en_policy3_health_safety_reporting.md (80 nodes, avg 7565ms)

| Q | Type | IDs selected | step1 | step2 | total | chars→synth | Result |
|---|------|-------------|-------|-------|-------|------------|--------|
| 1 | lookup | `1`, `1.8` | 2882 | 1488 | 4370 | 6010 | ✅ PASS |
| 2 | procedure | `2.4`, `2.5` | 2251 | 3919 | 6170 | 6171 | ✅ PASS |
| 3 | cross_section | `2`, `2.1`, `2.3.s4`, `2.4` | 5653 | 6503 | 12156 | 23454 | ✅ PASS* |

*Q3 note: §2.5 (EpiPen training) was NOT explicitly selected, but parent node `2` was selected,
which contains the full text of all sub-sections including §2.5. Synthesis correctly cited `[2.5]`
("Training in the use of an EpiPen") from the parent's full text. Pass via parent inclusion, not
direct selection. This is fragile: if the outline grows and parent nodes are de-listed, this stops working.

### en_policy1_child_protection.md (34 nodes, avg 11970ms)

| Q | Type | IDs selected | step1 | step2 | total | chars→synth | Result |
|---|------|-------------|-------|-------|-------|------------|--------|
| 1 | lookup | `1.8` | 4682 | 1331 | 6013 | 1701 | ✅ PASS |
| 2 | procedure | `1`, `1.5`, `1.11`, `1.13` | 5418 | 7080 | 12498 | 46071 | ✅ PASS |
| 3 | cross_section | `1`, `1.3`–`1.13` (9 nodes) | 12486 | 4913 | 17399 | 53588 | ✅ PASS |

Q1 note: 6013ms total despite only 1 node selected — step1 dominates (4682ms for 39-node outline).
Q2/Q3 note: parent node `1` selected in both, sending ~46–53K chars to synthesis.

### en_family_manual_24_25.md (46 nodes, avg 8317ms)

| Q | Type | IDs selected | step1 | step2 | total | chars→synth | Result |
|---|------|-------------|-------|-------|-------|------------|--------|
| 1 | lookup | `2.1`, `2.6` | 7444 | 2035 | 9479 | 2171 | ✅ PASS |
| 2 | procedure | `2`, `2.7`, `3` | 4927 | 3728 | 8655 | 10841 | ✅ PASS |
| 3 | cross_section | `7`, `7.1`, `7.4` | 3948 | 2869 | 6817 | 6012 | ❌ FAIL |

Q3 failure: query "What adjustments does the school make for students fasting for religious reasons?"
Selected §7 nodes, which don't contain the relevant content. Answer: "The provided sections do not
answer this question." Clean vocabulary mismatch — "fasting" and "religious adjustments" didn't
appear in the summaries of the correct sections (likely PE, nutrition, or health subsections).
This is the only outright failure in iteration 2.

---

## Summary

**16 queries, 15 PASS, 1 FAIL.**

| Metric | Value |
|--------|-------|
| Pass rate | 15/16 (93.8%) |
| Only outright failure | family_manual Q3 (fasting adjustments — vocabulary mismatch) |
| Avg latency (all docs) | ~9,600ms |
| Queries under 5s | 3/16 (policy5 Q1, Q5; policy3 Q1) |
| Max chars to synthesis | 53,588 (policy1 Q3) |
| Unresolved IDs | 0 across all 16 queries |

---

## Failure modes

### 1. Synthesis explosion (structural — all documents)
Parent-node selection sends entire section subtrees to synthesis. Examples:
- policy5 Q7: nodes `4/5/6` → 50,863 chars, 11.6s synthesis
- policy1 Q3: 9 nodes including root `1` → 53,588 chars
- policy5 Q2: 10 nodes → 36,001 chars, 11.1s synthesis

Root cause: step-1 LLM selects coarse parents when summaries are ambiguous about which
leaf holds the answer. Safe but slow. Every multi-section query hits this.

### 2. Vocabulary mismatch (clean failure)
family_manual Q3: "fasting for religious reasons" — wrong §7 selected, relevant sections missed.
policy3 Q3: "medical emergencies training" — §2.5 not directly selected (rescued by parent inclusion).

Both are caused by heading text carrying no vocabulary overlap with the query.
**Decision 5 (retrieval_title generation) targets this directly.**

---

## Index trees — iteration 2

Format: `id: title  [summary_chars / full_text_chars]`

### en_policy5_code_of_conduct.md (104 nodes)

```
├── 1: 1. Our Commitment  [965c / 4779c]
│   ├── 1.1: 1.1. Equal Opportunities  [596c / 2075c]
│   └── 1.2: 1.2. Objectives  [663c / 1325c]
├── 2: 2. Dress Code Policy  [827c / 6331c]
│   ├── 2.1: 2.1. Scope of the Policy  [342c / 676c]
│   ├── 2.2: 2.2. Terminology  [370c / 593c]
│   ├── 2.3: 2.3. Policy Statement and Principles  [1191c / 4483c]
│   ├── 2.4: 2.4. General Guidance  [727c / 2105c]
│   ├── 2.5: 2.5. Imagine Staff Dress Code (Reference)  [591c / 1334c]
│   ├── 2.6: 2.6. Monitoring and Review  [266c / 312c]
│   └── 2.7: 2.7. Reference Documents  [267c / 235c]
├── 3: 3. Attendance Policy  [955c / 13502c]
│   ├── 3.1: 3.1. Scope  [465c / 1460c]
│   ├── 3.2: 3.2. Terminology  [407c / 825c]
│   ├── 3.3: 3.3. Policy Statement and Principles  [565c / 2161c]
│   ├── 3.4: 3.4. Definitions  [813c / 7855c]
│   │   ├── 3.4.s1: Definitions of Absence  [416c / 867c]
│   │   ├── 3.4.s2: Procedures and Responsibilities  [447c / 876c]
│   │   ├── 3.4.s3: Roles and Responsibilities  [797c / 2514c]
│   │   ├── 3.4.s4: Registration and Lateness Procedures  [454c / 1526c]
│   │   └── 3.4.s5: Absence and Attendance Concerns  [472c / 2043c]
│   ├── 3.5: 3.5. Monitoring and Review  [459c / 1052c]
│   └── 3.6: 3.6. Reference Documents  [445c / 115c]
├── 4: 4. Behaviour Policy  [1006c / 23153c]
│   ├── 4.1: 4.1. Scope  [436c / 586c]
│   ├── 4.2: 4.2. Terminology  [484c / 880c]
│   ├── 4.3: Positive Behaviour and Role Modelling  [539c / 1588c]
│   ├── 4.5: Responsibility and Principles of Behaviour  [582c / 1712c]
│   ├── 4.7: Behaviour and Expectations  [459c / 1266c]
│   ├── 4.9: 4.9. Dealing with Inappropriate Behaviours  [881c / 4490c]
│   ├── 4.10: 4.10. Natural Consequences  [367c / 384c]
│   ├── 4.11: 4.11. Day to Day Strategies  [667c / 1742c]
│   ├── 4.12: 4.12. Special Intervention Support: Tier 3  [597c / 1188c]
│   ├── 4.13: Removal from Class and Immediate Action  [568c / 1414c]
│   ├── 4.15: 4.15. Disagreements Between Pupils  [541c / 1594c]
│   ├── 4.16: 4.16. General Principles  [567c / 1908c]
│   ├── 4.17: 4.17. Physical Restraint  [428c / 766c]
│   ├── 4.18: 4.18. Inappropriate Language  [321c / 494c]
│   ├── 4.19: Managing Aggressive and Hurtful Play  [659c / 2196c]
│   ├── 4.21: 4.21. Monitoring and Review  [340c / 637c]
│   └── 4.22: 4.22. Reference Documents  [298c / 253c]
├── 5: 5. Anti-Racism Policy  [1068c / 7727c]
│   ├── 5.1: 5.1. Scope  [400c / 443c]
│   ├── 5.2: Racism, Equality, and Diversity Policy and Aims  [726c / 2446c]
│   ├── 5.5: 5.5. Definition of Racism  [702c / 1866c]
│   ├── 5.6: Accountability, Responsibility, and Action Regarding Racism  [720c / 2403c]
│   ├── 5.8: 5.8. Monitoring and Review  [364c / 376c]
│   └── 5.9: 5.9. Reference Documents  [352c / 158c]
├── 6: 6. Anti-Bullying Policy  [1192c / 19939c]
│   ├── 6.1: 6.1. Scope  [260c / 355c]
│   ├── 6.2: Bullying Policy: Terminology and Principles  [602c / 1846c]
│   ├── 6.4: 6.4. Policy Objectives  [711c / 1796c]
│   ├── 6.5: Rationale and Aims Regarding Bullying  [570c / 1822c]
│   ├── 6.7: 6.7. Implementation  [533c / 954c]
│   ├── 6.8: 6.8. Definition of Bullying  [507c / 1665c]
│   ├── 6.9: 6.9. Preventing Bullying  [529c / 1722c]
│   ├── 6.10: 6.10. Identifying and Reporting Bullying  [629c / 2243c]
│   ├── 6.11: 6.11. Taking Action  [1033c / 6169c]
│   │   ├── 6.11.s1: Interviewing the child who has been bullied  [355c / 499c]
│   │   ├── 6.11.s2: Interviewing the child responsible for the behaviour  [407c / 426c]
│   │   ├── 6.11.s3: Actions and Consequences: Formal School Warning  [372c / 144c]
│   │   ├── 6.11.s4: Actions and Consequences: Suspension  [600c / 2348c]
│   │   ├── 6.11.s5: Actions and Consequences: Exclusion  [324c / 952c]
│   │   └── 6.11.s6: Reporting and Policy Review  [623c / 1766c]
│   └── 6.12: 6.12. Record of the Incident  [757c / 1322c]
├── 7: 7. Drug and Alcohol Policy  [1389c / 13412c]
│   ├── 7.1: Scope and Terminology  [612c / 1770c]
│   ├── 7.3: Statutory Duties and Application of Policy  [673c / 1597c]
│   ├── 7.5: 7.5. The School's Stance on Drugs, Health and the Needs of P  [418c / 1068c]
│   ├── 7.6: 7.6. Policy Framework  [1150c / 3584c]
│   ├── 7.7: 7.7. Staff Support and Training  [210c / 211c]
│   ├── 7.8: Incident Management and Police Involvement  [540c / 1547c]
│   ├── 7.10: 7.10. The Needs of Pupils  [231c / 190c]
│   ├── 7.11: 7.11. Information Sharing  [280c / 271c]
│   ├── 7.12: 7.12. Involvement of Parent/Carer(s)  [206c / 216c]
│   ├── 7.13: 7.13. Staff Conduct and Drug Use  [153c / 199c]
│   ├── 7.14: 7.14. The Role of the Headteacher  [898c / 2709c]
│   ├── 7.15: 7.15. Specific Procedures  [592c / 1592c]
│   ├── 7.16: 7.16. Monitoring and Review  [303c / 246c]
│   └── 7.17: 7.17. Reference Documents  [567c / 319c]
├── 8: 8. Weapons and Dangerous Items Policy  [840c / 8043c]
│   ├── 8.1: 8.1. Scope  [326c / 533c]
│   ├── 8.2: 8.2. Terminology  [434c / 910c]
│   ├── 8.3: 8.3. Policy Statement and Principles  [469c / 1324c]
│   ├── 8.4: 8.4. Purpose and Aim  [716c / 2408c]
│   ├── 8.5: 8.5. Searching & Confiscation  [592c / 1958c]
│   ├── 8.6: 8.6. Monitoring and Review  [315c / 570c]
│   └── 8.7: 8.7. Reference Documents  [266c / 287c]
└── 9: 9. External Examinations Policies  [931c / 9089c]
    ├── 9.1: 9.1. Malpractice Policy – GCSE and A-Level Exams  [597c / 3596c]
    │   ├── 9.1.1: 9.1.1. Scope  [299c / 235c]
    │   ├── 9.1.2: Malpractice in Assessments and Procedures for Dealing with S  [605c / 1984c]
    │   ├── 9.1.6: Malpractice: Consequences and Student Responsibilities  [364c / 843c]
    │   ├── 9.1.8: 9.1.8. Communication  [244c / 154c]
    │   ├── 9.1.9: 9.1.9. Monitoring and Review  [165c / 93c]
    │   └── 9.1.10: 9.1.10. Reference Documents  [299c / 224c]
    └── 9.2: 9.2. Internal Appeals Procedure & Assessment Reviews  [941c / 5454c]
        ├── 9.2.1: 9.2.1. Scope  [291c / 282c]
        ├── 9.2.2: Internal Appeals Process for Internal Assessments  [656c / 2770c]
        ├── 9.2.4: 9.2.4. Enquiries About Results (EARs)  [527c / 820c]
        ├── 9.2.5: Academic Integrity and AI Usage  [573c / 961c]
        ├── 9.2.7: 9.2.7. Communication of Procedures  [177c / 163c]
        ├── 9.2.8: 9.2.8. Monitoring and Review  [388c / 93c]
        └── 9.2.9: 9.2.9. Reference Documents  [407c / 264c]
```

### en_policy3_health_safety_reporting.md (80 nodes)

```
├── 1: 1. Fire and Emergency Policy  [761c / 5784c]
│   ├── 1.1: 1.1. Scope  [512c / 1073c]
│   ├── 1.2: 1.2. Terminology  [518c / 936c]
│   ├── 1.3: 1.3. Policy Statement and Principles  [450c / 785c]
│   ├── 1.4: 1.4. Emergency Evacuation Procedures  [273c / 256c]
│   ├── 1.5: 1.5. Staff absences  [243c / 313c]
│   ├── 1.6: 1.6. Visitor Registration and Safety Procedures  [496c / 1573c]
│   ├── 1.7: 1.7. Evacuation routes  [218c / 114c]
│   ├── 1.8: Fire Safety Equipment Testing  [237c / 198c]
│   ├── 1.10: 1.10. Monitoring and Review  [200c / 126c]
│   └── 1.11: 1.11. Reference Documents  [479c / 360c]
├── 2: 2. Health & Safety Policy  [959c / 16591c]
│   ├── 2.1: 2.1. Scope  [678c / 2400c]
│   ├── 2.2: 2.2. Terminology  [196c / 226c]
│   ├── 2.3: 2.3. Policy Statement and Principles  [1018c / 6007c]
│   │   ├── 2.3.s1: General Policy Statement  [162c / 198c]
│   │   ├── 2.3.s2: Daily Safety Checks and Responsibilities  [481c / 971c]
│   │   ├── 2.3.s3: Monitoring and Review of Health and Safety Measures  [318c / 605c]
│   │   ├── 2.3.s4: Staff Training in Health and Safety  [478c / 1149c]
│   │   ├── 2.3.s5: Contractor Selection and Control  [328c / 405c]
│   │   ├── 2.3.s6: Workplace Safety and Emergency Procedures  [608c / 1711c]
│   │   └── 2.3.s7: Accident Reporting and Maintenance  [527c / 915c]
│   ├── 2.4: 2.4. First aid  [1094c / 3248c]
│   ├── 2.5: 2.5. Protocol for action in case of wasp stings in students  [912c / 2894c]
│   ├── 2.6: 2.6. Monitoring and Review  [300c / 239c]
│   └── 2.7: 2.7. Reference Documents  [489c / 1536c]
├── 3: 3. Policy of action in the event of weather alerts  [1130c / 8743c]
│   ├── 3.1: 3.1. Objective  [244c / 275c]
│   ├── 3.2: 3.2. Alert levels and action measures  [870c / 3050c]
│   ├── 3.3: Coordination, Suspension of Classes, and Educational Continuity  [554c / 1516c]
│   ├── 3.5: 3.5. General preventive measures  [253c / 398c]
│   ├── 3.6: 3.6. Query and monitoring of alerts  [224c / 237c]
│   ├── 3.7: 3.7. Responsibility and coordination  [317c / 439c]
│   ├── 3.8: 3.8. Correspondence table  [814c / 2196c]
│   └── 3.9: 3.9. Additional measures in case of dana events  [332c / 548c]
├── 4: 4. Food Policy  [1375c / 8188c]
│   ├── 4.1: 4.1. Scope  [317c / 404c]
│   ├── 4.2: 4.2. Terminology  [488c / 769c]
│   ├── 4.3: 4.3. Policy Statement and Principles  [613c / 1977c]
│   ├── 4.4: 4.4. Considerations for Fasting for Religious Reasons  [944c / 3688c]
│   ├── 4.5: 4.5. Monitoring and Review  [323c / 365c]
│   └── 4.6: 4.6. Reference Documents  [408c / 957c]
├── 5: 5. Data Protection Privacy Policy  [1065c / 17378c]
│   ├── 5.1: 5.1. Scope  [399c / 957c]
│   ├── 5.2: 5.2. Terminology  [647c / 3150c]
│   ├── 5.3: 5.3. Policy Statement and Principles  [564c / 1877c]
│   ├── 5.4: 5.4. Ownership of the data and the purpose  [484c / 1504c]
│   ├── 5.5: Data Controller and Personal Data Processed  [444c / 1041c]
│   ├── 5.7: Collection and Purpose of Personal Information  [515c / 1667c]
│   ├── 5.9: 5.9. With whom do we share your personal data?  [331c / 555c]
│   ├── 5.10: 5.10. Data transfers outside the EEA  [481c / 834c]
│   ├── 5.11: 5.11. How long will we retain your personal data?  [304c / 580c]
│   ├── 5.12: 5.12. What are your rights?  [469c / 1830c]
│   ├── 5.13: 5.13. Contacting us  [225c / 240c]
│   ├── 5.14: 5.14. Security measures  [589c / 1401c]
│   ├── 5.15: 5.15. Legal information  [269c / 425c]
│   ├── 5.16: 5.16. Monitoring and review  [291c / 149c]
│   └── 5.17: 5.17. Reference Documents  [353c / 1103c]
└── 6: 6. Whistleblowing Channel Policy  [795c / 35640c]
    ├── 6.1: 6.1. Scope  [425c / 823c]
    ├── 6.2: 6.2. Terminology  [504c / 1471c]
    ├── 6.3: 6.3. Policy Principles and Statements  [524c / 1571c]
    ├── 6.4: 6.4. General Responsibilities  [413c / 1450c]
    ├── 6.5: 6.5. Means of Communication  [253c / 257c]
    ├── 6.6: 6.6. Processing of Reports  [566c / 1827c]
    ├── 6.7: 6.7. Receipt and Registration of the Report  [360c / 1280c]
    ├── 6.8: 6.8. Admission Process  [652c / 2385c]
    ├── 6.9: 6.9. Investigation  [715c / 1843c]
    ├── 6.10: 6.10. Conclusion of Proceedings  [887c / 2650c]
    ├── 6.11: 6.11. Reporting of False or Malicious Claims  [559c / 1064c]
    ├── 6.12: 6.12. Personal Data Protection  [634c / 1626c]
    ├── 6.13: 6.13. Annex  [1044c / 14515c]
    │   ├── 6.13.s1: Introduction  [333c / 2016c]
    │   ├── 6.13.s2: Financial and Security Crimes  [362c / 1790c]
    │   ├── 6.13.s3: Information and Data Security  [570c / 1942c]
    │   ├── 6.13.s4: Workplace Conduct and Discrimination  [700c / 2946c]
    │   ├── 6.13.s5: Regulatory and Policy Non-Compliance  [680c / 4811c]
    │   └── 6.13.s6: Other Reportable Incidents  [262c / 984c]
    ├── 6.14: 6.14. Monitoring and Review  [169c / 149c]
    └── 6.15: 6.15. Reference Documents  [751c / 2665c]
```

### en_policy1_child_protection.md (34 nodes)

```
├── 1: 1. Child Protection Policy  [1177c / 33115c]
│   ├── 1.1: 1.1. Scope  [453c / 1017c]
│   ├── 1.2: 1.2. Terminology  [379c / 906c]
│   ├── 1.3: 1.3. Policy Statement and Principles  [756c / 2402c]
│   ├── 1.4: 1.4. Safeguarding Legislation and Guidance  [683c / 2438c]
│   ├── 1.5: 1.5. The Designated Safeguarding Lead (DSL)  [864c / 2531c]
│   ├── 1.6: 1.6. The Deputy Designated Safeguarding Lead(s)  [436c / 470c]
│   ├── 1.7: 1.7. Attendance  [281c / 284c]
│   ├── 1.8: 1.8. Children Missing from Education  [549c / 1690c]
│   ├── 1.9: 1.9. Helping Children to Keep Themselves Safe  [728c / 2517c]
│   ├── 1.10: 1.10. Complaints Procedure  [513c / 976c]
│   ├── 1.11: 1.11. Child Protection Procedures  [954c / 6686c]
│   │   ├── 1.11.s1: Recognising Abuse and Categories of Abuse  [355c / 673c]
│   │   ├── 1.11.s2: Physical Abuse  [324c / 483c]
│   │   ├── 1.11.s3: Emotional Abuse  [566c / 1180c]
│   │   ├── 1.11.s4: Sexual Abuse  [534c / 876c]
│   │   ├── 1.11.s5: Neglect  [500c / 848c]
│   │   └── 1.11.s6: Indicators of Abuse and Reporting Responsibilities  [634c / 2578c]
│   ├── 1.12: 1.12. Impact of Abuse  [380c / 588c]
│   ├── 1.13: 1.13. Taking Action  [971c / 3673c]
│   ├── 1.14: 1.14. Sexual Exploitation of Children  [510c / 1009c]
│   ├── 1.15: 1.15. Local Contact Telephones  [596c / 929c]
│   ├── 1.16: 1.16. Appendix  [1009c / 4100c]
│   ├── 1.17: 1.17. Monitoring and Review  [363c / 168c]
│   └── 1.18: 1.18. Reference Documents  [341c / 667c]
└── 2: 2. Confidentiality Policy  [1337c / 4690c]
    ├── 2.1: 2.1. Scope  [267c / 333c]
    ├── 2.2: Confidentiality and Data Protection Procedures  [611c / 1587c]
    ├── 2.5: 2.5. Schoolwork Records  [405c / 821c]
    ├── 2.6: 2.6. SEN Children  [330c / 500c]
    ├── 2.7: 2.7. Computers  [609c / 891c]
    ├── 2.8: 2.8. Staff DBS Checks  [206c / 246c]
    ├── 2.9: 2.9. Monitoring and Review  [90c / 148c]
    └── 2.10: 2.10. Reference Documents  [523c / 121c]
```

### en_family_manual_24_25.md (46 nodes)

```
├── welcome-to-the-school-ye: Welcome to the School Year  [225c / 545c]
├── index: Index  [899c / 2960c]
├── 1: 1. Our School  [1055c / 5737c]
│   ├── 1.1: 1.1 Imagine Montessori School Valencia  [588c / 1396c]
│   ├── 1.2: 1.2 Pedagogical Team  [697c / 3019c]
│   └── 1.3: 1.3 Leadership and Administration  [603c / 1301c]
├── 2: 2. Timetables and Other Logistical Considerations  [1069c / 7426c]
│   ├── 2.1: 2.1 Timetables  [573c / 1007c]
│   ├── 2.2: 2.2 School Hours, Punctuality Guidelines and Drop-Off  [605c / 3041c]
│   ├── 2.3: 2.3 Rainy Days  [179c / 330c]
│   ├── 2.4: Arrival and Pick-up Logistics  [527c / 1303c]
│   ├── 2.6: 2.6 Early Bird and Afternoon Club  [468c / 1135c]
│   └── 2.7: 2.7 Authorisation for Students to Leave or Be Picked Up Alone  [343c / 547c]
├── 3: 3. Communication Between Families and the School  [1022c / 2823c]
├── 4: 4. Pedagogical Meetings  [395c / 1204c]
├── 5: 5. Our Curriculum  [1042c / 8937c]
│   ├── 5.1: 5.1 First Years – Early Years  [1250c / 4172c]
│   └── 5.2: 5.2 Primary (6-12)  [630c / 2841c]
├── 6: 6. Psycho Pedagogical and Career Guidance Department  [552c / 2200c]
├── 7: 7. Nutrition  [818c / 2992c]
│   ├── 7.1: Healthy Eating and Educational Approach to Food  [658c / 2258c]
│   └── 7.4: 7.4 Practical Matters  [371c / 716c]
├── 8: 8. Nap  [328c / 513c]
├── 9: 9. Health Standards  [968c / 3726c]
│   ├── 9.1: 9.1 Medications and Illnesses  [707c / 3168c]
│   └── 9.2: 9.2 Vaccination Status  [335c / 533c]
├── 10: 10. Behavior  [376c / 802c]
├── 11: 11. Our Commitment to the English Language  [408c / 788c]
├── 12: 12. Dress Code  [566c / 1237c]
├── 13: 13. Spare Clothing and Required Equipment  [425c / 1407c]
├── 14: 14. Nappies and Accidents  [450c / 835c]
├── 15: 15. Birthday Celebrations  [479c / 1113c]
├── 16: 16. Enrichment Programme  [302c / 577c]
├── 17: 17. School's Materials  [265c / 286c]
├── 18: 18. Toys  [275c / 263c]
├── 19: 19. Balls  [307c / 462c]
├── 20: 20. Lost and Found  [486c / 578c]
├── 21: 21. Outings  [581c / 1762c]
├── 22: 22. School Bus  [690c / 1422c]
├── 23: 23. Updating Personal Information or Family Situation  [343c / 587c]
├── 24: 24. Individual and Group Photographs  [570c / 1548c]
├── 25: 25. Payment Policy and Financial Aid  [1079c / 4186c]
│   ├── 25.1: 25.1 Payment Policy  [698c / 2156c]
│   └── 25.2: 25.2 Financial Aid  [508c / 1988c]
├── 26: 26. Comparison of the Spanish Education System vs the British  [436c / 1392c]
└── 27: 27. School Policies  [104c / 98c]
```

---

## What changes for iteration 3

1. **Implement Decision 5** — generate `retrieval_title` for each node during summarise phase.
   Show `retrieval_title` (not heading text) in the step-1 outline.
   Expected to fix family_manual Q3 and harden policy3 Q3 (direct selection instead of rescue via parent).

2. **Synthesis explosion is the remaining latency problem.**
   After retrieval_title is validated, the next lever is preventing parent-node selection.
   Options: penalise parent selection in the step-1 prompt; or add a step-1.5 that expands
   selected parents to their direct children before synthesis.

## What to carry into POC2

**What worked:**
- Three-phase pipeline (split → thin → summarise) produces clean, well-bounded nodes.
- Summary quality is high enough for vocabulary-mismatch cross-section reasoning.
- No hallucinated IDs in 7 queries — the constrained JSON schema approach is reliable.
- Synthetic split nodes (e.g. `3.4.s6`, `8.4.s2`) held precise facts that heading-level
  nodes would have buried in long text.

**What needs to change:**
- The flat 65K-char outline is the fundamental scalability problem. A routing layer must
  reduce the candidate set before full-outline node selection.
- 29 stubs inflate the outline without contributing retrieval signal. Consider a post-thin
  merge pass that collapses stubs into their parent regardless of semantic similarity.

**Routing layer recommendation for POC2:**
The Q7 result argues against pure vector routing: the query phrase didn't appear verbatim
in the target sections, yet the LLM still found them via summary reasoning. Vector routing
risks missing this kind of semantic bridge.

Recommendation: **hierarchical (meta-tree) routing first.**
Step 0: LLM selects top-level sections (9 nodes, ~1K chars outline) from a summary-of-summaries.
Step 1: Full outline of only the selected subtrees (~20–40 nodes) → existing node selection.
Step 2: Synthesis as now.

This keeps the vocabulary-mismatch reasoning in the LLM path while making the outline
small enough for step 1 to be fast.
