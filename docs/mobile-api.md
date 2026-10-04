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
- Returns `{"data": [LeadRow], "has_more": bool}`.

### `list_deals(...)`
Same as `list_leads`, returning DealRows.

### `get_record(doctype, name)`
`doctype` is `CRM Lead` or `CRM Deal`. Returns:
```json
{ "doc": {LeadRow/DealRow fields + "territory","industry","website","job_title","annual_revenue","lost_reason",
          "abm_adset","abm_ad","abm_platform"},
  "notes": [{"name","title","content","owner","creation"}],
  "tasks": [Task],
  "calls": [Call],
  "comments": [{"name","content","owner","creation"}],
  "visits": [Visit],
  "whatsapp": [{"name","message","sent_by","creation"}] }
```
Each list is newest first, with at most 50 items.

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
| `search(q, limit=20)` | `[{doctype, name, title, subtitle}]` across leads, deals, contacts and organizations. Matches name, organization, email and mobile. |

**Notifications** (CRM Notification for the session user)

| Method | Returns |
|---|---|
| `list_notifications(start=0, page_length=30)` | `{data: [{name, type, title, body, from_user, from_full_name, read, creation, doctype, docname}], has_more, unread}` |
| `mark_notifications_read(names=None)` | Marks those, or all when `names` is empty. Returns `{unread}`. |

**Email** (Communication, the same data the web Emails tab shows)

| Method | Returns / does |
|---|---|
| `get_emails(doctype, name)` | `[{name, subject, content (HTML), sender, sender_full_name, recipients, cc, bcc, sent_or_received, creation, read_by_recipient, attachments: [{file_name, file_url}], in_reply_to}]`, newest first |
| `get_email_setup(doctype, name)` | `{senders: [abm_crm.api.email sender options], templates: [{name, subject}] (Email Template with reference_doctype = doctype or empty), to: [default recipient email]}` |
| `render_email_template(template, doctype, name)` | `{subject, content}`, rendered with the record |
| `send_email(doctype, name, to, subject, content, cc=None, bcc=None, sender=None, attachments=None (File names), in_reply_to=None)` | Uses `frappe.core.doctype.communication.email.make`, the same path the web composer uses, so sender rules apply. Returns the Communication name. |

**Attachments**

| Method | Returns / does |
|---|---|
| `list_attachments(doctype, name)` | `[{name, file_name, file_url, file_size, is_private, owner, creation}]` |
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
| `get_contact(name)` | `{doc, deals: [DealRow], leads: [LeadRow]}` |
| `create_contact(data)` | Keys: first_name, last_name, email_id, mobile_no, company_name. Returns the row. |
| `list_organizations(search=None, start=0, page_length=20)` | `{data: [{name, organization_name, website, industry, territory, organization_logo, annual_revenue}], has_more}` |
| `get_organization(name)` | `{doc, deals: [DealRow], contacts: [contact rows]}` |
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
- `get_emails` for a deal also lists the emails of the lead it was converted from (as the web timeline does), at most 100.
  `creation` is the communication date.
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
