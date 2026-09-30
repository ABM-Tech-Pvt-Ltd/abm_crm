# ABM CRM roadmap

Ideas for extending Frappe CRM (1.86) in abm_crm, based on a review of crm, crm_override and alfa_crm.
Each item notes where it plugs in. Rule of thumb: backend changes go through `hooks.py`
(`doc_events`, `scheduler_events`, `permission_query_conditions`, `extend_doctype_class`); frontend
changes go in `frontend/src_override/` (override one crm file, or add a new file).

Status: [x] done, [ ] not started.

## 1. Email

- [x] **Choose the sender in the email composer.** `ABM Email Sender` maps Email Accounts to users,
  roles or everyone. `abm_crm.api.email.get_sender_options` returns the allowed accounts, and
  `src_override/components/EmailEditor.vue` shows them in the FROM picker. A `Communication.before_insert`
  hook pins `email_account` so Frappe sends through the chosen SMTP account.
  "Enforce Sender Rules" in `ABM CRM Settings` blocks any other address.
  - Why the override: crm reads `User.user_emails`, which sales users cannot read (permlevel 1), so
    the picker never appeared for them.
- [ ] Send `in_reply_to` from `Activities/EmailArea.vue` `reply()` so replies thread reliably.
- [ ] Signature per Email Account (crm always uses the default outgoing account's signature,
  `crm/api/__init__.py`).
- [ ] Set `append_to` = CRM Deal on accounts used for deals (crm's default is CRM Lead only).
- [x] Settings page in the CRM UI for sender rules (Settings > Email > Senders).

Setup note: each sender must be its own Email Account with its own login (or OAuth). Gmail and
Office 365 reject or rewrite a From address that does not match the authenticated account.

## 2. Assignment and access

What crm already has: Round Robin / Load Balancing rules with a condition builder, a sales
hierarchy (`CRM Sales Hierarchy`, turn on "Enable Sales Hierarchy" in FCRM Settings) where managers
see their team's records, and Sales Users who see only records they own or are assigned.

- [x] Lead routing rules: assign by campaign, ad set, ad, Facebook form, sync source, source, platform,
  territory or a Python condition; round robin or load balancing; per-user open-lead cap; fallback user
  (Settings > Automation & Rules > Lead Routing, `abm_crm/lead_routing.py`).
- [x] Facebook campaign / ad set / ad attribution stored on leads and deals.
- [ ] Re-route existing unassigned leads in bulk from the Lead Routing page.
- [ ] Assign only within working hours (use a Holiday List or `CRM Service Day`).
- [ ] Auto-reassign when a lead has no activity for N hours or its SLA fails (scheduler job).
- [ ] Bulk reassign API for managers (e.g. when a rep leaves).
- [ ] Approval for deal discount or gated stage changes (`CRM Deal.validate` + `Deal Approval` doctype).
- [ ] Audit log of owner, status and assignment changes.

Note: every app's `permission_query_conditions` is ANDed, so abm_crm can narrow access but not
widen it. To widen (e.g. territory managers), use DocShare.

## 3. Lead channels

- **Facebook Lead Ads** already exist in crm (Settings > Lead Syncing), but only by polling (5 min
  minimum). Gaps: no pagination, one form per source, no token expiry warning, new forms are not
  fetched after setup, no phone/email dedupe across sources, no per-source assignment.
- **WhatsApp** in crm needs the `frappe_whatsapp` app and a Meta WhatsApp Business account. It is not
  installed on this bench, so the WhatsApp tab does nothing today. Gaps once installed: templates
  cannot be sent with variables from the CRM UI, no 24-hour window warning, one outgoing number
  for everyone, no lead creation from unknown numbers, no broadcasts.

- [ ] Install `frappe_whatsapp`, then patch template sending to pass `template_parameters`.
- [ ] Generic `Lead Channel` doctype + one guest webhook endpoint
  (`abm_crm.channels.ingest?channel=...`) with per-channel field mapping, signature check, raw payload
  log and background processing. Adapters: Facebook webhook (real-time), Instagram lead ads,
  IndiaMART (pull API), JustDial, Google Ads lead forms, website forms.
- [ ] Dedupe on normalised phone (+91) and email across CRM Lead, CRM Deal and Contact. On a match,
  log activity on the existing record instead of creating a new lead.
- [ ] First-touch automation after a lead arrives: assign, then send a WhatsApp template.
- [ ] Per-rep WhatsApp number routing.

## 4. Mobile

crm switches to Mobile* pages below 768px, but list views are desktop tables that scroll sideways,
kanban drag is poor on touch, and there are no tap-to-call / WhatsApp links.

- [ ] Tap-to-call (`tel:`), WhatsApp (`wa.me`) and directions buttons in `MobileLead.vue` /
  `MobileDeal.vue` headers and list rows.
- [ ] Card list for Leads and Deals on mobile instead of the table.
- [ ] "Today" agenda page: tasks, reminders and overdue follow-ups.
- [ ] Log call outcome after a `tel:` call (writes `CRM Call Log`, asks for next follow-up).
- [ ] Web push notifications for reminders and new assignments.
- [ ] GPS check-in for field visits (`Field Visit` doctype; crm_override has a `GeolocationControl.vue`).
- [ ] Voice notes on leads (MediaRecorder upload).

## 5. Follow-ups and productivity

- [ ] Mandatory next follow-up date when a lead or deal status changes.
- [ ] Per-rep daily digest email (port alfa_crm's daily reminder, but per user and at the right time).
- [ ] Port `CRM Reminder` and `CRM Activity Tracker` from alfa_crm.
- [ ] AI follow-up drafts (port `crm_override/api/ai_followup.py`; move prompts and API key into settings).
- [ ] Quick WhatsApp template picker next to phone fields (works with `wa.me`, no API needed).
- [ ] Quotation PDF from a deal, shared by WhatsApp or email.

## 6. Admin dashboards

crm's Dashboard already has funnel, lost deal reasons, deals by source/territory/salesperson.

- [ ] Rep leaderboard: calls, meetings, emails, won deals, win rate.
- [ ] Lead response time per rep (SLA data exists, not charted).
- [ ] Follow-ups due / overdue.
- [ ] Source ROI (add a cost field on CRM Lead Source).
- [ ] Lost reasons for leads (crm only charts deals).

## 7. More ideas (research, 2026-10-01)

Note: crm 1.86 ships Frappe's Automation Engine (flow builder with wait steps, Settings > Workflow
Automations). Build cadences as new actions plugged in with the `automation_actions` hook, not as a
separate sequence doctype.

Quick wins (under a day each) are marked QW.

- [ ] **Phone normalisation (QW).** Store numbers as E.164 (`+91...`) on CRM Lead, CRM Deal and Contact
  in `before_validate` (`phonenumbers` library), plus a one-time patch for existing records. Do this
  first: dedupe, WhatsApp matching and missed-call matching all depend on it.
- [ ] **Tasks per status (QW).** `ABM Status Playbook` doctype: status → task title, due offset,
  priority. For example "Contacted" → "Call back in 24h". Triggered on status change.
- [ ] **Required fields per status.** For example "Qualified" needs budget and city, "Lost" needs a
  reason. Enforce in `validate`, and prompt for the missing fields in the status dropdown.
- [ ] **Lead ageing report (QW).** Open leads grouped by age (0-1, 1-3, 3-7, 7+ days) and "never
  contacted", per rep and status.
- [ ] **Missed-call leads (QW).** Guest webhook for Exotel / MyOperator / Knowlarity: create or match
  the lead, set source "Missed Call", then route it.
- [ ] **DPDP consent and do-not-contact flag (QW).** Record consent source and time. WhatsApp, SMS and
  cadence actions skip DND contacts.
- [ ] **Cadence actions for the Automation Engine.** Send WhatsApp template (with variables), send SMS
  (MSG91 / DLT template id), create CRM Task with a due offset.
- [ ] **Accept-or-pass new leads.** Realtime alert to the assigned rep. If not accepted within N minutes,
  pass the lead to the next user in the routing rule.
- [ ] **Send lead quality back to Meta and Google Ads.** Qualified / won / junk events go to Meta's
  Conversions API (leadgen id) or Google Ads (gclid), so ads optimise for good leads.
- [ ] **Campaign funnel with ad spend.** Import daily spend, impressions and clicks from Facebook
  Insights into an `ABM Ad Spend` doctype, then show leads → qualified → won, CPL and ROAS per
  campaign, ad set and ad.
- [ ] **Calling queue.** "Next lead" page on mobile, ordered by SLA breach, temperature and oldest
  untouched. Tap to call, log the outcome, move on.
- [ ] **Android call log and recording sync** (TeleCRM style) for calls from reps' own SIMs, into
  `CRM Call Log` (which already has `recording_url`).
- [ ] **Call transcription and AI summary** (Hindi / Hinglish) into the call log note.
- [ ] **AI lead brief** in the side panel: 3-line summary and suggested next step.
- [ ] **Click-to-WhatsApp ad attribution.** Inbound WhatsApp messages carrying an ad `referral` create
  a lead with its campaign fields filled, so routing rules match it.
- [ ] **Razorpay payment links on deals**, marked paid by Razorpay's webhook.
- [ ] **Live team activity feed** for managers (calls, emails, status changes, assignments).
- [ ] **Field visibility per role** (e.g. hide cost and margin from Sales Users), enforced on the server too.
- [ ] **Multiple pipelines** with their own deal statuses and kanban.

## 8. WhatsApp gaps (frappe_whatsapp installed, see WHATSAPP.md)

- [ ] Send templates with variables from the CRM UI (crm's `send_whatsapp_template` drops parameters).
- [ ] Warn when the 24-hour window is closed, and offer a template instead.
- [ ] One WhatsApp number per rep or team.
- [ ] Create a lead from a message sent by an unknown number, then route it.
