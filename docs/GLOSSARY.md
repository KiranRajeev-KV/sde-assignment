# Glossary

The vocabulary we use every day at Agentic Universe. Both assignments use these terms.

| Term | Meaning |
|---|---|
| **Tenant** | A client company using the platform (for example an insurer). Limits like call concurrency apply per tenant. |
| **Workflow** | A business process run by voice agents, such as `motor_renewal` (remind customers to renew their policy) or `policy_feedback` (collect feedback after purchase). Each workflow has its own lead schema and disposition catalogue. |
| **Campaign** | One run of outbound calling for a tenant: a set of leads, a calling window, and retry rules. |
| **Lead** | A customer we intend to call, uploaded by the client. Identified within a workflow by phone number. |
| **Batch** | One uploaded file of leads. Reports are often grouped by batch ("how is Monday's upload doing?"). |
| **Lead schema** | Per-workflow definition of the columns we accept, their types, which are required, and which are PII. |
| **PII** | Personally identifiable information: names, phone numbers. Must be protected at rest. |
| **Call / Interaction** | One attempt to reach a lead. A call may fail at the telephony layer, ring out unanswered, or connect. |
| **Connectivity rate** | Connected calls ÷ total calls. A core health metric for every campaign. |
| **Disposition** | The classified outcome of a connected call, for example `renewed`, `callback_requested`, `not_interested`. Set by the AI agent after the call. |
| **Terminal disposition** | A disposition that ends our work on a lead. No more calls. |
| **Success disposition** | A disposition that counts as a business win for the client (for example `renewed`). |
| **Override** | A human supervisor correcting the AI's disposition. Recorded as a **new** event; the original is never edited. |
| **Interaction ledger** | The append-only record of everything that happened on every call. Reports are derived from it; it is the single source of truth. |
| **Calling window** | The hours (and days) during which we may start calls. Regulation in India restricts commercial calls to 09:00–21:00. |
| **DND** | "Do Not Disturb": the customer has asked never to be called. Calling them again is a compliance breach. |
| **Callback** | The customer asked to be called back at a specific time. Honouring it promptly matters a lot for conversion. |
| **Telephony provider** | The carrier API that actually places calls and reports results via webhooks. |
| **Idempotency key** | A client-chosen ID (`request_id`) that makes retrying a request safe: the provider performs the action at most once per key. |

## Assignment A: ingestion and reporting terms

Added while designing the Assignment A solution. Terms above are unchanged.

| Term | Meaning |
|---|---|
| **Drop** | One day's delivery of files (lead batches plus event files), ingested as a unit. _Avoid_: load, delivery. |
| **Lead identity** | `(workflow_id, canonical phone)`. Two lead rows with the same identity are the same lead. |
| **Merged duplicate** | A later valid lead row whose identity already exists; it updates the lead's non-null fields and never creates a new lead. _Avoid_: dupe lead. |
| **Rejection** | A lead row that fails a required-field or phone check; it never becomes a lead and is reported with a single reason. |
| **Field warning** | An optional value on a non-rejected row that is present but invalid; the field is treated as missing. |
| **Linked event** | A ledger event that, given everything ingested so far, belongs to a lead (by phone, or for overrides by call). |
| **Orphan event** | A ledger event that is not currently linked. Orphan status is not permanent: it ends when the matching lead arrives. _Avoid_: quarantined event. |
| **Effective disposition** | A call's outcome after supervisor corrections: the latest valid override, else the latest valid `disposition.set`. |
| **Bucket** | A lead's progress category: `yet_to_reach_out`, `completed`, `in_progress_telephony_failed`, `in_progress_dialed`. |
| **Counted call** | A call whose `call.initiated` event is linked; it belongs to that event's lead, and all events sharing its `call_id` are part of it. Events of a call with no `call.initiated` are not part of any counted call. _Avoid_: attempt (ambiguous with retries). |
