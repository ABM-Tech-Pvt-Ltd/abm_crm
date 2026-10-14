# ABM CRM mobile API

API used by the ABM CRM Android app. Every method is in `abm_crm/api/mobile.py` and is called as
`POST /api/method/abm_crm.api.mobile.<method>` with a JSON body. The response is `{"message": <result>}`.

**Authentication:** `login` returns an API key and secret. Every other call sends this header:

```
Authorization: token <api_key>:<api_secret>
```

**Permissions:** normal Frappe permissions apply. A rep sees only the leads and deals they are allowed
to see. Methods marked *manager* need the System Manager or Sales Manager role.

**Formats:**
- Datetimes are site-local strings, `YYYY-MM-DD HH:MM:SS`.
- Phone numbers come back exactly as they are stored.

## Auth and bootstrap

### `login(usr, pwd)`
Guest method, rate limited to 10 per 10 minutes per IP. Returns:
```json
{ "api_key": "...", "api_secret": "...", "user": "a@b.com", "full_name": "A B",
  "user_image": "/files/..", "roles": ["Sales User"], "is_manager": false }
```
- The user must be enabled and have a CRM role (Sales User, Sales Manager or System Manager).
- Existing keys are reused; new ones are generated if the user has none.
- No browser session is opened. Users with two-factor authentication are refused, because API keys would skip it.

### `logout(token=None)`
Generates a new API secret, which signs out every device using the old one. Because every device is
signed out, all of the user's ABM Mobile Devices are disabled too (no more pushes); `token` is optional.
Signing in again and calling `register_device` re-enables the device.

### `bootstrap()`
```json
{ "user": {"name","full_name","user_image","mobile_no"}, "is_manager": bool,
  "lead_statuses": [{"name","color","type","position"}], "deal_statuses": [...],
  "lead_sources": ["..."], "users": [{"name","full_name","user_image"}],
  "settings": {"call_sync_scope": "CRM numbers only" | "All calls", "upload_recordings": 1,
               "calling_code": "91", "whatsapp_mode": "Click to Chat"},
  "brand": {"name": "...", "logo": "/files/..."} }
```
`users` contains the enabled CRM users.

## Home

### `get_home()`
Data for the current user:
```json
{ "tasks_today": [Task], "tasks_overdue": [Task], "new_leads": [LeadRow] (assigned to me, status type Open, max 10),
  "calls_today": {"count": n, "connected": n, "talk_time": seconds},
  "counts": {"my_open_leads": n, "my_open_deals": n} }
```

## Leads and deals

**LeadRow:** `{name, lead_name, first_name, organization, status, mobile_no, phone, email, lead_owner, source, abm_campaign, modified, creation}`

**DealRow:** `{name, organization, lead_name, status, deal_value, currency, mobile_no, email, deal_owner, modified, creation}`

### `list_leads(search=None, status=None, owner=None, start=0, page_length=20, order_by="modified desc")`
- `search` matches lead_name, organization, mobile_no and email (LIKE).
- `owner = "me"` means the session user.
- `list_leads` leaves out converted leads (they continue as deals), like the CRM's own list.
- `order_by` is `<field> [asc|desc]` with field modified, creation, lead_name, organization, status or deal_value; anything else falls back to `modified desc`. `page_length` is at most 100.
- Uses `frappe.get_list`, so permissions apply.
- Returns `{"data": [LeadRow + lead_owner_name], "has_more": bool, "total": int}`. `lead_owner_name` (`deal_owner_name`
  for deals) is the owner's full name. `total`, the number of matching records the user can see, comes with the first
  page (`start=0`) only.

### `list_deals(...)`
Same as `list_leads`, returning DealRows.

### `get_record(doctype, name)`
`doctype` is `CRM Lead` or `CRM Deal`. Returns:
```json
{ "doc": {LeadRow/DealRow fields + "territory","industry","website","job_title","annual_revenue","lost_reason",
          "abm_adset","abm_ad","abm_platform",
          "form_answers": [{"question","answer"}]},
  "notes": [{"name","title","content","owner","creation"}],
  "tasks": [Task],
  "calls": [Call],
  "comments": [{"name","content","owner","creation"}],
  "visits": [Visit],
  "whatsapp": [{"name","message","sent_by","creation"}] }
```
Each list is newest first, with at most 50 items.

`doc.form_answers` is the lead form's questions that are not mapped to a CRM field (budget, location, ...), in form
order, `[]` when there are none. Several values for one question are joined with ", ". A deal has its own copy, made
from its lead at conversion. It replaces `abm_form_answers` (a "Question: answer" per line text), which is no longer
returned.

### `update_status(doctype, name, status)`
Returns the updated `doc`.

### `add_note(doctype, name, content, title=None)`
Creates an FCRM Note linked to the record. Returns the note.

### `create_lead(data)`
`data` may contain: first_name, last_name, mobile_no, email, organization, source, status, lead_owner.
`lead_owner` defaults to the session user.
Returns a LeadRow.

## Tasks

**Task:** `{name, title, description, status, priority, due_date, assigned_to, reference_doctype, reference_docname}`

### `list_tasks(filter="today" | "overdue" | "upcoming" | "done" | "all", start=0, page_length=50)`
Tasks assigned to the session user. Returns `{"data": [Task], "has_more": bool}`.

### `create_task(reference_doctype, reference_docname, title, due_date=None, priority="Medium", assigned_to=None, description=None)`
`assigned_to` defaults to the session user. Returns a Task.

### `update_task(name, status=None, due_date=None)`
Returns a Task.

## Calls

**Call:** `{name, type, status, from, to, duration, start_time, end_time, caller, receiver, recording_url,
recording_url_path, abm_outcome, note, reference_doctype, reference_docname, telephony_medium}`

### `sync_calls(calls, device_id)`
The app sends phone call-log entries. Each item:
```json
{ "device_call_id": "1234", "number": "+919876543210", "type": "incoming" | "outgoing" | "missed" | "rejected",
  "start": 1790000000000 (epoch ms), "duration": 42 (seconds), "contact_name": "optional" }
```
The session user must have a mobile number (or phone) on their profile, otherwise the whole request
fails with a message asking for it (`from` / `to` are mandatory on CRM Call Log). At most 500 calls per request.

For each call, the server:
- Builds the CRM Call Log `id` as `abm-{device_id}-{device_call_id}`. A call that already exists is returned unchanged, so retries are safe.
- Matches the number to a lead, deal or contact with `crm.integrations.api.get_contact_lead_or_deal_from_number`.
- Skips the call when the scope is "CRM numbers only" and nothing matches, returning `call_log: null`.
- Also skips hidden / private numbers (empty or not a phone number).
- Otherwise creates the CRM Call Log:
  - `telephony_medium`: "Manual"
  - `type`: incoming / missed / rejected → "Incoming", outgoing → "Outgoing"
  - `status`: duration > 0 → "Completed"; missed → "No Answer"; rejected → "Busy"; outgoing with 0 duration → "No Answer"
  - `from` / `to`: the number and the session user's mobile_no, depending on direction
  - `caller` / `receiver`: the session user, depending on direction
  - `start_time` / `end_time`, `duration`
  - linked to the matched lead or deal

Returns one entry per input:
```json
[{ "device_call_id": "1234", "call_log": "abm-dev-1234" | null, "reference_doctype": "CRM Lead" | null,
   "reference_docname": "...", "reference_title": "...", "upload_recording": true | false }]
```
`upload_recording` is true when a call log exists, the duration is over 0, recordings are enabled,
and no recording is attached yet.

### `upload_recording(call_log)`
- Multipart form upload with the field `file` (audio: m4a, mp3, amr, awb, aac, wav, ogg, oga, opus, 3gp, 3gpp, flac, webm).
- Stored as a private File attached to the CRM Call Log; `recording_url` is set to its file URL.
- Only the call's caller or receiver, or a manager, may upload.
- Returns `{"recording_url": "/private/files/..."}`.

### `set_call_outcome(call_log, outcome, note=None, next_follow_up=None)`
- `outcome` is a custom Select field `abm_outcome` on CRM Call Log: Interested, Not Interested, Call Back, No Answer, Wrong Number, Busy, Converted.
- `note` creates an FCRM Note linked to the call's lead or deal, and sets `CRM Call Log.note`.
- `next_follow_up` (datetime) creates a CRM Task "Follow up" for the session user on the lead or deal.

Returns a Call.

### `list_calls(scope="mine" | "team", date_from=None, date_to=None, start=0, page_length=50)`
`team` is for managers only and covers all users. Returns `{"data": [Call + "user_full_name", "reference_title"], "has_more"}`.

## Field visits

**Visit:** `{name, reference_doctype, reference_docname, latitude, longitude, accuracy, address, notes, photo, visited_by, visited_at}`

### `check_in(reference_doctype, reference_docname, latitude, longitude, accuracy=None, address=None, notes=None)`
Creates an **ABM Field Visit** (new doctype). An optional multipart `file` (jpg, jpeg, png, webp, heic, heif)
is attached as a private file and set as the photo.
Returns a Visit.

## Manager dashboard

### `manager_dashboard(date_from=None, date_to=None)`
*Manager only.* Defaults to today.
```json
{ "totals": {"calls","connected","talk_time","new_leads","converted","visits","overdue_tasks"},
  "reps": [{"user","full_name","user_image","calls","connected","talk_time","outgoing","incoming","missed",
            "leads_assigned","leads_touched","visits","overdue_tasks","last_call"}],
  "lead_funnel": [{"status","color","count"}],
  "recent_calls": [Call + "user_full_name","reference_title"] (last 20 that have a recording) }
```
- Calls are counted by `start_time` in the range; a call belongs to its caller (outgoing) or receiver (incoming).
  `missed` is incoming calls that were not completed.
- `new_leads` and `lead_funnel` count leads created in the range (funnel by current status, in status order).
- `converted` counts deals created in the range from a lead.
- `leads_touched` counts distinct leads the rep called, wrote a note on, or visited in the range.
- `overdue_tasks` is the current number of open tasks past their due date (not limited to the range).
- `last_call` is the rep's latest call ever; `recent_calls` is not limited to the range.

## Settings added to ABM CRM Settings
- `call_sync_scope` (Select): "CRM numbers only" (default) or "All calls"
- `upload_recordings` (Check, default 1)

### `set_my_mobile(mobile_no)`
Saves the session user's own mobile number in international format and returns it as
`{"mobile_no": "+91..."}`. `sync_calls` needs this number, so the app asks for it when
`bootstrap.user.mobile_no` is empty.

## Tags (step 1 of the second batch)

Tags use Frappe's built-in tag system: the `Tag` doctype, the `_user_tags` column and `Tag Link`.
CRM list filters already support "Tags like …". abm_crm adds two custom fields on **Tag**:

- `abm_category` (Select): Builder, Project, Location, Budget, Other
- `abm_color` (Select): gray, blue, green, red, pink, orange, amber, yellow, cyan, teal, violet, purple

**Tag:** `{name, category, color}`

The methods live in `abm_crm/api/tags.py` and are shared by the web CRM and the app:

| Method | What it does |
|---|---|
| `get_tags()` | Every Tag with a category, color and `count` (records using it), ordered by category then name. Any CRM user can call it. |
| `get_doc_tags(doctype, name)` | `[Tag]` for one CRM Lead or CRM Deal. |
| `add_tag(doctype, name, tag, category=None, color=None)` | Creates the Tag if it doesn't exist (any CRM user may create one), then applies it. Needs write permission on the record. Returns `[Tag]` for the record. |
| `remove_tag(doctype, name, tag)` | Returns `[Tag]` for the record. |
| `update_tag(tag, category=None, color=None)` | Sets a tag's category and color. Any CRM user may do this. |

Other behaviour:
- When a deal is created from a lead, the lead's tags are copied to it.
- Mobile rows (`LeadRow`, `DealRow` and `get_record().doc`) include `tags: [Tag]`.
- `list_leads` and `list_deals` take an optional `tag` filter.

Implementation notes:
- Tag names are cleaned (spaces stripped and collapsed) and an existing tag is reused whatever its
  letter case ("lodha" → "Lodha"). Commas are refused, because `_user_tags` is comma separated.
- `category` / `color` are matched case-insensitively against the options above; anything else is an error.
  On `add_tag` they are applied to the tag even if it already exists. `update_tag` with an empty value clears it.
- `get_tags` `count` is the number of leads and deals with the tag (Tag Link rows); tags without a
  category are listed last. `get_tags` / `add_tag` / `update_tag` need a CRM role; `add_tag` / `remove_tag`
  need write permission on the record, `get_doc_tags` read permission.
- The `tag` list filter is an exact tag match (`Lodha` does not match `Lodha Park`), case-insensitive.
- `get_home().new_leads` rows include `tags` as well.

## Push notifications

**ABM Mobile Device** doctype: user, token (unique), platform, device_name, app_version, last_seen, enabled.

| Method | What it does |
|---|---|
| `register_device(token, platform="android", device_name=None, app_version=None)` | Upserts the token for the session user. A token that already belongs to another user is moved to this user. |
| `unregister_device(token)` | Removes the token if it belongs to the session user (a token already moved to someone else is left alone). |

The server sends through FCM HTTP v1, using the service-account JSON stored in ABM CRM Settings
(`fcm_service_account`, System Manager only).

Push data payload: `{"doctype": "...", "name": "...", "type": "..."}`. The app opens that record when the notification is tapped.

Pushes are sent when:
- a **CRM Notification** is inserted (Mention, Assignment, Task, WhatsApp, Automation) → push to `to_user`;
- a lead or deal is assigned to a user, if crm doesn't already create a CRM Notification for it → "New lead assigned: {title}".

`register_device` returns `{"name", "platform", "enabled"}`; `platform` is `android` or `ios`.
The app should call it after every sign-in and whenever FCM gives it a new token.

Titles: Assignment → "New lead assigned" / "New deal assigned" / "New task assigned"
("Assignment removed" when crm reports an unassignment); Mention → "You were mentioned";
Task → "Task update"; WhatsApp → "New WhatsApp message"; Automation → "CRM update".
The body is the notification text without HTML (or the message). No push is sent to the user who caused
the notification (`from_user`), nor to Administrator or Guest.

crm already creates an Assignment CRM Notification whenever a lead, deal or task is assigned through a
ToDo (`crm.api.todo.after_insert`, skipping self-assignment), including leads routed by
abm_crm's lead routing. So no separate ToDo hook is needed: assignment pushes come from the
CRM Notification hook.

Sending runs in the background queue, so saves never wait on FCM. Tokens that FCM reports as
invalid (HTTP 404 or UNREGISTERED) are disabled. If push is switched off (`push_enabled`) or no service
account is saved, nothing is sent (logged once per worker). The OAuth access token is cached for 50 minutes.

## Full CRM in the app (v2)

All methods are in `abm_crm.api.mobile`, unless noted. Normal permission checks apply.
`doctype` is CRM Lead or CRM Deal unless stated otherwise.

**Dashboard and search**

| Method | Returns |
|---|---|
| `get_dashboard()` | `{greeting_name, stats: {open_leads, open_deals, pipeline_value, currency, won_this_month, won_value_this_month, tasks_today, tasks_overdue, calls_today, talk_time_today, unread_notifications}, agenda: [AgendaItem] (today and tomorrow; tasks and events merged, sorted by time), pipeline: [{status, color, count, value}] (open deal statuses), recent: [{doctype, name, title, status, modified}] (last 8 records I touched)}` |
| `search(q, limit=20)` | `[{doctype, name, title, subtitle}]` across leads, deals, contacts and organizations. Matches name, organization, email and mobile. `q` shorter than 2 characters returns `[]`; `limit` is at most 50. |

**Notifications** (CRM Notification for the session user)

| Method | Returns |
|---|---|
| `list_notifications(start=0, page_length=30)` | `{data: [{name, type, title, body, from_user, from_full_name, read, creation, doctype, docname}], has_more, unread}` |
| `mark_notifications_read(names=None)` | Marks those, or all when `names` is empty. Returns `{unread}`. |

**Email** (Communication, the same data the web Emails tab shows)

| Method | Returns / does |
|---|---|
| `get_emails(doctype, name, start=0, page_length=None)` | With `page_length` (at most 100): `{data: [Email], has_more}`. Without it (older apps): `[Email]`, the newest 100. Email: `{name, subject, content (HTML), sender, sender_full_name, recipients, cc, bcc, sent_or_received, creation, read_by_recipient, attachments: [{file_name, file_url}], in_reply_to}`, newest first |
| `get_email_setup(doctype, name)` | `{senders: [abm_crm.api.email sender options], templates: [{name, subject}] (Email Template with reference_doctype = doctype or empty), to: [default recipient email]}` |
| `render_email_template(template, doctype, name)` | `{subject, content}`, rendered with the record |
| `send_email(doctype, name, to, subject, content, cc=None, bcc=None, sender=None, attachments=None (File names), in_reply_to=None)` | Uses `frappe.core.doctype.communication.email.make`, the same path the web composer uses, so sender rules apply. Returns the Communication name. |

**Attachments**

| Method | Returns / does |
|---|---|
| `list_attachments(doctype, name, start=0, page_length=None)` | With `page_length` (at most 100): `{data: [File], has_more}`. Without it (older apps): `[File]`, the newest 100. File: `{name, file_name, file_url, file_size, is_private, owner, creation}` |
| `upload_attachment(doctype, name)` | Multipart `file`; private by default. Returns the row. |
| `delete_attachment(file)` | Only the owner or a manager. |

**Editing records**

| Method | Returns / does |
|---|---|
| `get_form(doctype)` | Field metadata for the edit form, taken from the CRM Fields Layout (Data Fields, falling back to Side Panel): `[{section, fields: [{fieldname, label, fieldtype, options, reqd, read_only}]}]`. Select options are lists; Link fields include `options` (the doctype). |
| `link_options(doctype, txt="")` | `[{value, label}]` for Link fields, max 20, permission-checked. |
| `update_record(doctype, name, values)` | Only fields present in `get_form` and not read_only. Returns `get_record().doc`. |
| `assign(doctype, name, users)` / `unassign(doctype, name, user)` | Wraps `frappe.desk.form.assign_to`. `get_record()` also returns `assignees: [{name, full_name, user_image}]`. |
| `convert_to_deal(lead)` | Uses crm's convert function. Returns `{deal}`. |
| `create_deal(data)` | Keys: organization, lead_name, mobile_no, email, deal_value, status, deal_owner. Returns a DealRow. |
| `add_comment(doctype, name, content)` | Returns the comment. |
| `update_note(name, title=None, content=None)` / `delete_note(name)` | |
| `update_task(name, title=None, description=None, status=None, priority=None, due_date=None, assigned_to=None)` / `delete_task(name)` | |

**Contacts and organizations**

| Method | Returns |
|---|---|
| `list_contacts(search=None, start=0, page_length=20)` | `{data: [{name, full_name, email_id, mobile_no, company_name, image}], has_more}` |
| `get_contact(name)` | `{doc, deals: [DealRow], leads: [LeadRow], deals_has_more, leads_has_more}`: the first 20 of each (rows include the owner's full name); more with `list_related` |
| `create_contact(data)` | Keys: first_name, last_name, email_id, mobile_no, company_name. Returns the row. |
| `list_organizations(search=None, start=0, page_length=20)` | `{data: [{name, organization_name, website, industry, territory, organization_logo, annual_revenue}], has_more}` |
| `get_organization(name)` | `{doc, deals: [DealRow], contacts: [contact rows], deals_has_more, contacts_has_more}`: the first 20 of each; more with `list_related` |
| `list_related(doctype, name, kind, start=0, page_length=20)` | A page of a Contact's `deals` / `leads` or a CRM Organization's `deals` / `contacts`: `{data, has_more}`, newest first, permission-checked |
| `create_organization(data)` | Returns the row. |

**Calendar** (Frappe Event, linked to a CRM record through Event Participants)

AgendaItem: `{kind: "task" | "event", name, title, start, end, all_day, status, reference_doctype, reference_docname, reference_title}`

| Method | Returns / does |
|---|---|
| `list_agenda(date_from, date_to)` | My events (owner or participant) and my tasks (due in the range), merged. |
| `create_event(subject, starts_on, ends_on=None, all_day=0, description=None, reference_doctype=None, reference_docname=None)` | Event type "Private", owned by the session user. Returns an AgendaItem. |
| `update_event(name, ...)` / `delete_event(name)` | Owner only. |

**Profile**

| Method | Returns / does |
|---|---|
| `get_profile()` | `{name, full_name, first_name, last_name, email, mobile_no, user_image, roles, is_manager}` |
| `update_profile(first_name=None, last_name=None, mobile_no=None)` | Updates the session user's own profile. Optional multipart `file` sets `user_image`. |

### v2 implementation notes and deviations

Everything above is in `abm_crm/api/mobile.py`; tests are in `abm_crm/tests/test_mobile_v2.py`.

**Additions to the contract**
- `get_record().doc` now also contains every field of `get_form`, so the app can fill the edit form.
- `update_contact(name, data)` (keys as `create_contact`; a new email or mobile becomes the primary one) and
  `update_organization(name, data)` (keys as `create_organization` except `organization_name`). Contacts and
  organizations cannot be deleted from the app.
- `convert_to_deal` also accepts `deal` (dict of deal values), `existing_contact` and `existing_organization`,
  like the web's Convert to Deal dialog.
- `update_event` takes `subject, starts_on, ends_on, all_day, description, status, reference_doctype, reference_docname`.
- `upload_attachment` takes `is_private` (default 1).
- `delete_task(name)`; `update_task` keeps its old parameters, so older app builds still work.

**Dashboard**
- `open_leads` / `open_deals` count records I own (as `get_home().counts`); an open deal has a status of type Open, Ongoing or On Hold.
- `pipeline`, `pipeline_value` and `won_*` cover every deal the user may read (a rep: own, assigned or shared deals; a manager: all).
- `currency`: the deals' own currency when they all share one; otherwise values are converted with each deal's
  `exchange_rate` into the CRM base currency (FCRM Settings currency, else the system currency, else USD).
- Won this month: status type Won and `closed_date` in this month, or no `closed_date` and modified this month.
- `agenda` is today and tomorrow. `recent` is leads and deals last modified by me.

**Search**: `limit` is at most 50. Converted leads are left out (they continue as deals). When there are more
matches than `limit`, results are taken in turn from each doctype so one doctype cannot fill the list.

**Notifications**: `title` and `body` are the same as the push notification's. Marking as read only touches the
session user's notifications.

**Email**
- `get_emails` for a deal also lists the emails of the lead it was converted from (as the web timeline does), in one
  list ordered by communication date. `creation` is the communication date.
- Templates: enabled Email Templates whose `reference_doctype` is the doctype or empty. Rendering uses
  `Email Template.get_formatted_email` with the record's fields plus `doc`, exactly like the web composer.
- `send_email`: `to`, `cc`, `bcc` may be a list or a comma-separated string. Without `sender`, the default sender
  option is used. `attachments` are File names the user can read (e.g. from `upload_attachment`).
  The web's sender rules (`abm_crm.api.email.validate_outgoing_sender`) only applied to requests to
  `communication.email.make`; they now also apply to the app (via `frappe.flags.abm_crm_composer`).

**Attachments**: uploading needs write permission on the record. `delete_attachment` only deletes files attached
to a lead or deal.

**Editing**
- `get_form` leaves out hidden fields, tables (e.g. the deal's products), HTML and buttons. Fields the user can only
  read because of their perm level are marked `read_only`, as on the web.
- `update_record`: `""` clears a field. It needs write permission.
- `link_options(doctype, txt)`: `doctype` is the Link's target. For `User` it returns the enabled CRM users (like the
  web's user pickers); otherwise frappe's link search (`search_widget`) is used, which checks permissions.
- `assign` / `unassign` need write permission on the record (assigning on the web only needs read).
- `convert_to_deal` uses crm's `convert_to_deal` with `if_converted="Return Existing"`, so a retry returns the same deal.
- `create_deal` uses crm's `create_deal`: `lead_name` is split into first and last name for the new contact (an
  existing contact with the same email or mobile is reused), and `organization` is used if it exists, otherwise created.
  Needs create permission on CRM Deal.
- `add_comment` and `update_note` take plain text (escaped, one paragraph per line); comments go through
  `crm.api.comment.add_comment`, so mentions work as on the web.
- `update_task`: values left out are kept; `description=""` clears the description.

**Calendar**
- "My events" are events I created, am assigned to, or am a participant of (an Event Participants row with my email).
- Repeating events are not expanded: they are listed only when their first occurrence is in the range.
- `list_agenda` returns at most 500 events and 500 tasks, for at most 366 days. Tasks include done ones, but not
  cancelled ones. Items are sorted by start time, with all-day events first.
- `create_event` sets the category to Event and the status to Open. The lead or deal is added as an Event Participant.
  `update_event` with a new reference replaces the old lead/deal participant; `ends_on=""` clears the end.
- `delete_event`: frappe gives Desk Users no delete permission on Event, so after checking that the user owns the
  event, the delete skips the permission check.

**Profile**: `mobile_no` is normalised like `set_my_mobile` (an empty value clears it). The photo (jpg, png, webp,
heic) is saved as a public file, like web profile photos, so other users can see it. The User record is saved
without a permission check (Sales Users cannot write User records), and only the session user's own record and
these three fields are changed.

## v3: site visits, team report, lead info, idle-lead alerts, internal calls

Shared by the web CRM and the mobile app. Visit and idle-alert methods live in their own modules and are
called by path: `abm_crm.api.visits.<method>`, `abm_crm.api.idle_alerts.<method>`. Team report and call
sync changes are in `abm_crm.api.mobile`. Same auth and permission rules as above; "manager" means System
Manager or Sales Manager.

### Site visits (walk-ins) as a lifecycle

ABM Field Visit becomes a visit that is planned, held, postponed or cancelled. The existing check-in
(GPS + photo) stays: it creates or completes a visit.

**New fields on ABM Field Visit** (existing rows are migrated to status `Visited`, type `Site Visit`):

| Field | Type | Notes |
|---|---|---|
| `status` | Select | `Pending`, `Scheduled`, `Visited`, `Postponed`, `Cancelled`, `No Show`. Default `Pending`; `Scheduled` when `scheduled_on` is given. |
| `visit_type` | Select | `Site Visit` (default), `Walk-in`, `Office Meeting` |
| `project` | Data | the project or property visited |
| `scheduled_on` | Datetime | planned time. When postponed, the new time. |
| `visited_at` | Datetime | existing: when the visit happened |
| `status_reason` | Small Text | why it was cancelled, postponed or a no-show |
| `outcome` | Select | after a visit: empty, `Interested`, `Needs Follow-up`, `Not Interested`, `Booked` |
| `closing_manager`, `closing_manager_user` | Data, Link User | the person who closes the sale |
| `attended_by`, `attended_by_user` | Data, Link User | the person who attended the visit |
| `site_visit_assistant`, `site_visit_assistant_user` | Data, Link User | the assistant on site |
| `notes`, `photo`, `latitude`, `longitude`, `accuracy`, `address`, `visited_by` | existing | `visited_by` is who recorded the visit |

Each person is a **name** (`closing_manager`) plus an optional **system user** (`closing_manager_user`).
The person need not be a CRM user: send only the name. When a user is sent, the name is filled from the
user's full name. A user must be enabled.

**Status rules** (enforced on save):
- `Scheduled` and `Postponed` need `scheduled_on`.
- `Visited` sets `visited_at` to now when empty.
- `Cancelled`, `Postponed` and `No Show` keep `status_reason` (recommended, not required).
- `Visited` and `Cancelled` are final except for a manager.

**VisitRow:** `{name, status, status_color, visit_type, project, scheduled_on, visited_at, status_reason, outcome,
closing_manager, closing_manager_user, closing_manager_name, attended_by, attended_by_user, attended_by_name,
site_visit_assistant, site_visit_assistant_user, site_visit_assistant_name, notes, latitude, longitude, accuracy,
address, map_url, photo_url, reference_doctype, reference_docname, reference_title, phone, visited_by,
visited_by_name, owner, owner_name, creation, modified, visit_date}`. `*_name` is the display name (the user's
full name or the typed name). `visit_date` is `scheduled_on`, else `visited_at`, else `creation`.
`status_color` is a CRM color name: Pending gray, Scheduled blue, Visited green, Postponed orange,
Cancelled red, No Show pink.

| Method | Returns / does |
|---|---|
| `get_visit_options()` | `{statuses: [{name, color}], types: [str], outcomes: [str], projects: [str] (distinct projects used, plus tags in category Builder or Project), users: [{name, full_name, user_image}] (enabled CRM users)}` |
| `list_visits(status=None, visit_type=None, user=None, project=None, date_from=None, date_to=None, search=None, reference_doctype=None, reference_docname=None, start=0, page_length=20, order_by="date")` | `{data: [VisitRow], has_more}`. `user` matches any of closing manager, attended by, assistant, visited_by, owner. Dates filter on `visit_date`. `search` matches project, names, lead title and phone. `order_by`: `date` (newest first), `upcoming` (soonest scheduled first). Only visits on records the user can read. |
| `get_visit(name)` | VisitRow |
| `create_visit(reference_doctype, reference_docname, data)` | VisitRow. `data` keys: status, visit_type, project, scheduled_on, status_reason, outcome, the three people (name and/or user), notes, latitude, longitude, accuracy, address, visited_at. Needs write permission on the lead or deal. |
| `update_visit(name, data)` | VisitRow. Same keys. Checks the status rules. |
| `delete_visit(name)` | The creator or a manager. |
| `upload_visit_photo(name)` | Multipart `file` (image). Returns VisitRow. |
| `visit_dashboard(date_from=None, date_to=None, user=None, project=None, visit_type=None)` | See below. Defaults to the current month. |
| `get_visits(doctype, name)` | existing; rows are now VisitRows |

Creating or changing a visit adds a comment on the lead or deal ("Site visit scheduled for 12 Oct, 4:00 PM
at Lodha Palava", "Site visit postponed to ...", "Site visit completed"), so it shows in the activity feed.
When a visit gets a person who is a user, that user gets a CRM Notification ("Site visit assigned: ...").

**`visit_dashboard` result:**
```json
{ "range": {"date_from": "...", "date_to": "..."},
  "totals": {"total": 0, "pending": 0, "scheduled": 0, "visited": 0, "postponed": 0, "cancelled": 0, "no_show": 0,
             "today": 0, "upcoming_7d": 0, "overdue": 0, "booked": 0, "completion_rate": 0.0},
  "by_status": [{"status": "Visited", "color": "green", "count": 0}],
  "by_user": [{"user": "a@b.com" | null, "name": "Display name", "user_image": null, "total": 0, "visited": 0,
               "scheduled": 0, "pending": 0, "postponed": 0, "cancelled": 0, "no_show": 0,
               "as_closing_manager": 0, "as_attended_by": 0, "as_assistant": 0, "as_rep": 1}],
  "by_project": [{"project": "Lodha Palava", "total": 0, "visited": 0, "booked": 0}],
  "by_type": [{"visit_type": "Site Visit", "count": 0}],
  "by_day": [{"date": "2026-10-12", "scheduled": 0, "visited": 0}],
  "today": [VisitRow], "upcoming": [VisitRow] (next 10 scheduled, soonest first),
  "overdue": [VisitRow] (scheduled in the past, still Scheduled or Pending; max 10) }
```
`by_user` groups by system user when there is one, else by the typed name. A person counts once per visit per
role. `overdue` and `upcoming` ignore the date range. `completion_rate` is visited / (visited + cancelled + no_show).
`booked` counts visits whose `outcome` is `Booked`. Visits are counted by `visit_date` inside the range.

### Mobile: visits, check-in
`abm_crm.api.mobile.check_in(...)` now also accepts `visit` (an existing visit name): it completes that visit
(status `Visited`, GPS, address, notes, optional photo) instead of creating one. Without `visit` it creates a new
visit with status `Visited`, as before.

### Team report (manager)

| Method | Returns |
|---|---|
| `get_team_report(user=None, date_from=None, date_to=None, idle_hours=24)` | `{range, user: {name, full_name, user_image} \| null, summary: Summary, reps: [Summary + {user, full_name, user_image}] (only when user is null), by_status: [{status, color, count}], by_source: [{source, count}]}` |
| `list_team_leads(user=None, status=None, search=None, idle_only=0, date_from=None, date_to=None, idle_hours=24, sort="idle", start=0, page_length=20)` | `{data: [TeamLead], has_more}` |

`user` is a user id or None for the whole team. Non-managers always get their own data.

**Summary:** `{leads_total, leads_open, leads_new, leads_contacted, leads_idle, leads_converted, calls, connected, missed,
talk_time, visits_scheduled, visits_done, deals_created}`. `leads_total` and `leads_open` are all leads the user owns now;
`leads_new`, `leads_contacted`, `leads_converted` and the call and visit numbers fall inside the date range.
`leads_idle` is open leads with no activity for `idle_hours`. Open means the status type is Open or Ongoing.

**TeamLead:** LeadRow + `{owner_name, tags, last_activity, last_contacted, idle_minutes, calls, last_call, visits,
next_visit}`. `last_activity` is the latest of the lead's modified time, its latest call, comment and email.
`last_contacted` is the latest call, email or WhatsApp. `idle_minutes` is wall-clock minutes since `last_activity`.
`calls` and `visits` are counts for the lead in the date range. `sort`: `idle` (most idle first), `recent`
(latest activity first), `created` (newest first).

`list_leads` and `list_deals` already take `owner` as a user id; it keeps working.

### Lead info (get_record)
`get_record().doc` also has: `owner` (the user who created it), `owner_name`, `modified_by`, `modified_by_name`,
`lead_owner_name` (or `deal_owner_name`), `last_activity`, `last_contacted`, `idle_minutes`. Each call in
`get_record().calls` and in `list_calls` also has `rep` (the user whose phone made or took the call) and `rep_name`.

### Internal calls are not logged
`sync_calls` only logs calls with a **lead or deal**. It skips, and returns no call log for:
- a number that belongs to a user of this CRM (their `mobile_no` or `phone`, compared on the last 10 digits): an
  internal call;
- a number that matches only a plain Contact (Frappe makes a Contact for every user), unless the CRM setting
  `call_sync_scope` is "All calls". Internal numbers are skipped even then.

Each sync result has `skip_reason`: `null` when logged, `internal`, or `no_match`. The app removes its own local
recording of a skipped call.

`cleanup_internal_call_logs(dry_run=1)` (manager, `abm_crm.api.mobile`) finds call logs already saved for internal
numbers that are not on a lead or deal. With `dry_run=1` it returns `{count, names}`; with `dry_run=0` it deletes them
and returns `{deleted}`.

### Idle-lead alerts

An admin defines **rules**: which lead statuses to watch, the working hours, and who to notify after how long. Idle
time only counts inside working hours: with hours 10:30 to 19:30, a lead that arrives at 20:00 starts its idle clock at
10:30 the next working day.

**ABM Idle Lead Rule** doctype: `rule_name` (unique), `enabled`, `statuses` (table of CRM Lead Status), `work_start`
(Time, default 10:30), `work_end` (Time, default 19:30), `mon` to `sun` (Check; Monday to Saturday on by default),
`only_assigned` (Check: skip leads with no owner), `levels` (table: `idle_minutes` Int working minutes, `notify_owner`
Check, `notify_user` Link User, `notify_role` Link Role, `message` Small Text, optional).

A lead is idle for a rule when its status is in the rule's statuses and its **last activity** (latest of modified time,
call, comment, email) was `idle_minutes` working minutes ago. Each level fires **once per idle period**: any new
activity starts a new period. A scheduled job runs every 5 minutes. A level notifies the lead owner, the user, and every
user with the role (once each). The notification is a CRM Notification of type `Automation` (shown in the web and the
app, and pushed to phones): title "Idle lead: {lead name}", text "No activity for {n} min during working hours",
pointing at the lead.

**ABM Idle Lead Alert** doctype records each alert: `rule`, `lead`, `level` (the idle minutes), `activity_marker`
(the last activity it was raised for), `sent_to` (users), `idle_minutes`, `creation`.

| Method | Returns / does |
|---|---|
| `get_setup()` | `{rules: [Rule], statuses: [{name, color, type}], users: [{name, full_name}], roles: [str]}` (manager) |
| `save_rule(rule)` | the rule name. `rule`: all rule fields; `statuses` as a list of status names; `levels` as a list of level objects. Renaming keeps history. |
| `delete_rule(name)`, `set_rule_enabled(name, enabled)` | |
| `preview_rule(rule)` | `{idle_now: n, leads: [{name, lead_name, owner_name, status, idle_minutes}] (max 20)}`: leads that would be alerted by a level right now; sends nothing |
| `list_idle_leads(rule=None, user=None, start=0, page_length=20)` | `{data: [{name, lead_name, status, lead_owner, owner_name, idle_minutes, last_activity, rule, level}], has_more}`: leads currently idle, per rule |
| `list_alerts(rule=None, lead=None, start=0, page_length=20)` | `{data: [Alert + lead_name, rule], has_more}` |
| `run_now()` | manager only: runs the check once and returns `{alerts: n}` |

### v3 implementation notes and deviations

Where the contract above was open or the implementation differs:

- **Visit rules.** `Visited` and `Cancelled` are final for non-managers only as to the *status* (other fields such as notes can still
  be corrected). `visited_at` is set only for `Visited`; other statuses keep it empty. A non-manager cannot send `visited_at` in
  `update_visit`; on create it is accepted only when recent (last 3 days), as for check-in. A typed name replaces the user for that
  role (`closing_manager` sent without `closing_manager_user` clears the user); an empty user clears it.
- **`visit_dashboard`.** `completion_rate` is a percentage (0 to 100, one decimal). `by_day.scheduled` counts visits that have a
  `scheduled_on` (any status), `by_day.visited` counts status `Visited`, both grouped by `visit_date`. `today` is visits whose
  `visit_date` is today (any status, up to 50). `upcoming` and `upcoming_7d` use status Scheduled, Pending or Postponed with
  `scheduled_on` in the future; `overdue` uses Scheduled or Pending with `scheduled_on` in the past. `by_user` lists people by
  closing manager, attended by and assistant only (not who recorded it); typed names group case-insensitively.
  Non-managers only see visits on leads/deals they can read (lead/deal ids from `frappe.get_list`).
- **Visit rows** also keep the old `visited_by_image`, and have `photo` (the raw file URL) next to `photo_url`. `check_in` returns a VisitRow.
  The CRM Notification for an assigned person is type `Automation`: the title is in `message`
  ("Site visit assigned: {lead}"), the details in `notification_text`. The push title for any `Automation` notification is its `message`.
- **Team report.** Default range is today. Only leads that are not converted count (`converted = 0`, like the leads list). `leads_contacted`
  is the number of owned leads with a call, email or WhatsApp inside the range. `leads_converted` is owned leads that got a deal created in
  the range; `deals_created` is deals created in the range by `deal_owner`. `visits_scheduled` / `visits_done` count visits dated
  (`visit_date`) in the range with status Scheduled/Pending, or Visited, where the user is any of the three people, the recorder or the creator.
  `by_status` and `by_source` count leads created in the range (`source` empty: "Unknown"). `summary` for the whole team is the sum of `reps`
  (enabled CRM users); leads without an owner are not in it. `TeamLead.owner_name` (and `lead_owner_name`) is the lead owner's name.
  In `list_team_leads` the dates only limit `calls` and `visits` (no dates: all time); `last_call` is the latest call ever and
  `next_visit` the soonest future Scheduled/Pending/Postponed visit. `sort=idle` puts Won and Lost leads last. `idle_only` keeps open leads only.
- **Lead info.** `last_activity` also exists for deals (calls, comments and emails on the deal).
- **Internal calls.** A number counts as internal when it is the mobile or phone of any enabled system user. Results always carry
  `skip_reason` (also `no_match` for hidden numbers). `cleanup_internal_call_logs` looks at logs with no lead/deal and checks the other
  party's number (`to` for outgoing, `from` for incoming).
- **Idle alerts.** A rule with no statuses watches every Open/Ongoing status; Won/Lost statuses are watched only when listed. Converted leads are
  skipped. When several levels were passed at the same time (a new rule, or the job was down), only the highest notifies; the lower ones are
  logged as alerts with an empty `sent_to` so they do not fire later. `ABM Idle Lead Alert.lead` is a plain Data field (not a Link) so leads
  can still be deleted. `delete_rule` also deletes the rule's alerts. `list_idle_leads` and `list_alerts` are open to any CRM user, who then
  only sees their own leads; everything else is manager only. `get_setup().rules[]` use the `save_rule` shape plus `name` and `modified`
  (`work_start`/`work_end` as `HH:MM:SS`, `statuses` as names). `save_rule` takes `name` to update or rename an existing rule.
