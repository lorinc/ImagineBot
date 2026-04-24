# TODO — admin service

_Append-only. Resolve items by striking through and noting the outcome._

---

## Tenant admin panel

- **Feedback statistics page** — Each tenant can see aggregated feedback on their corpus:
  thumbs-up/down counts, ratio over time, comments, and which questions received negative
  ratings. Scoped to the tenant's own traces only (filter by `group_id` / source IDs they own).

---

## Service-provider admin panel

- **Technical statistics dashboard** — Across all tenants: request volume, per-stage latency
  breakdown (classifier, topics, knowledge, end-to-end), error rates, pipeline path distribution
  (out_of_scope / vague / specific / broad ratios).

- **Outlier view** — Highlight requests that are anomalous: unusually high latency, zero facts
  returned, negative feedback, classifier flip (in_scope but no answer). Used to catch
  systematic retrieval failures and prompt regressions before users escalate.
