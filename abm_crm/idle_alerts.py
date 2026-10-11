"""Idle-lead alerts: tell people when a lead has had no activity for a while during working hours.

Rules are ABM Idle Lead Rule records. A scheduled job (every 5 minutes) calls `run_check`, which looks at
the leads each enabled rule watches, measures how long each has been idle in *working* minutes and, when a
level of the rule has been reached, sends CRM Notifications and logs an ABM Idle Lead Alert.

Every function takes `now` so it can be tested at a fixed time. Contract: docs/mobile-api.md.
"""

import datetime

import frappe
from frappe import _
from frappe.utils import cint, get_datetime, now_datetime

from abm_crm.activity import activity_times

DAY_FIELDS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")  # index = datetime.weekday()
OPEN_TYPES = ("Open", "Ongoing")
DEFAULT_MESSAGE = "No activity for {n} min during working hours"


def as_time(value) -> datetime.time:
	"""A Time field value (timedelta from the database, string or time) as a time of day."""
	if isinstance(value, datetime.time):
		return value
	if isinstance(value, datetime.timedelta):
		return (datetime.datetime.min + value).time()
	return get_datetime(f"2000-01-01 {value or '00:00:00'}").time()


def working_minutes(start, end, work_start, work_end, days) -> int:
	"""Minutes between two datetimes that fall inside working hours.

	`days` are the working weekdays (0 = Monday). A span may cover many days: each working day counts
	from its start time to its end time, clipped to the span, so a start after hours counts from the
	next working morning and non-working days count nothing.
	"""
	start, end = get_datetime(start), get_datetime(end)
	opens, closes, days = as_time(work_start), as_time(work_end), set(days)
	if end <= start or closes <= opens or not days:
		return 0
	seconds = 0.0
	day = start.date()
	while day <= end.date():
		if day.weekday() in days:
			low = max(datetime.datetime.combine(day, opens), start)
			high = min(datetime.datetime.combine(day, closes), end)
			if high > low:
				seconds += (high - low).total_seconds()
		day += datetime.timedelta(days=1)
	return int(seconds // 60)


def normalize_rule(rule) -> frappe._dict:
	"""A rule document or the dict sent by the setup screen, in one shape."""
	get = rule.get
	statuses = [s if isinstance(s, str) else s.get("status") for s in get("statuses") or []]
	levels = []
	for lv in get("levels") or []:
		levels.append(
			frappe._dict(
				idle_minutes=cint(lv.get("idle_minutes")),
				notify_owner=cint(lv.get("notify_owner")),
				notify_user=lv.get("notify_user") or None,
				notify_role=lv.get("notify_role") or None,
				message=lv.get("message") or None,
			)
		)
	levels.sort(key=lambda lv: lv.idle_minutes)
	days = {i for i, field in enumerate(DAY_FIELDS) if cint(get(field))}
	return frappe._dict(
		name=get("name"),
		rule_name=get("rule_name"),
		enabled=cint(get("enabled")),
		statuses=[s for s in statuses if s],
		only_assigned=cint(get("only_assigned")),
		work_start=as_time(get("work_start") or "10:30:00"),
		work_end=as_time(get("work_end") or "19:30:00"),
		days=days,
		levels=[lv for lv in levels if lv.idle_minutes > 0],
	)


def watched_statuses(rule) -> list[str]:
	"""The rule's statuses, or every open status when none are listed (Won and Lost only when listed)."""
	return rule.statuses or frappe.get_all("CRM Lead Status", {"type": ["in", OPEN_TYPES]}, pluck="name")


def idle_leads(rule: frappe._dict, now) -> list[dict]:
	"""Leads the rule watches with their working idle minutes and the levels reached, most idle first."""
	if not rule.levels:
		return []
	filters = {"converted": 0, "status": ["in", watched_statuses(rule) or [""]]}
	if rule.only_assigned:
		filters["lead_owner"] = ["is", "set"]
	leads = frappe.get_all(
		"CRM Lead", filters=filters, fields=["name", "lead_name", "status", "lead_owner", "modified"]
	)
	times = activity_times("CRM Lead", {lead.name: lead.modified for lead in leads})
	rows = []
	for lead in leads:
		last_activity = times[lead.name][0]
		idle = working_minutes(last_activity, now, rule.work_start, rule.work_end, rule.days)
		due = [lv for lv in rule.levels if idle >= lv.idle_minutes]
		if due:
			rows.append(
				{**lead, "last_activity": last_activity, "idle_minutes": idle, "due": due}
			)
	rows.sort(key=lambda r: -r["idle_minutes"])
	return rows


def run_check(now=None) -> int:
	"""Scheduled job: raise every alert that is due. Returns the number of alerts sent."""
	now = get_datetime(now) if now else now_datetime()
	sent = 0
	for name in frappe.get_all("ABM Idle Lead Rule", {"enabled": 1}, pluck="name"):
		sent += process_rule(frappe.get_doc("ABM Idle Lead Rule", name), now)
	return sent


def process_rule(rule_doc, now) -> int:
	rule = normalize_rule(rule_doc)
	rows = idle_leads(rule, now)
	if not rows:
		return 0
	existing = frappe.get_all(
		"ABM Idle Lead Alert",
		filters={"rule": rule_doc.name, "lead": ["in", [r["name"] for r in rows]]},
		fields=["lead", "level", "activity_marker"],
	)
	done = {(a.lead, a.level, get_datetime(a.activity_marker)) for a in existing}
	role_cache: dict = {}
	sent = 0
	for row in rows:
		marker = get_datetime(row["last_activity"]).replace(microsecond=0)
		pending = [lv for lv in row["due"] if (row["name"], lv.idle_minutes, marker) not in done]
		if not pending:
			continue
		# when several levels were passed at once (a new rule, or the job was down) only the highest speaks
		top = pending[-1]
		for lv in pending:
			recipients = notify(rule_doc, row, lv, role_cache) if lv is top else []
			frappe.get_doc(
				{
					"doctype": "ABM Idle Lead Alert",
					"rule": rule_doc.name,
					"lead": row["name"],
					"level": lv.idle_minutes,
					"idle_minutes": row["idle_minutes"],
					"activity_marker": marker,
					"sent_to": ", ".join(recipients),
				}
			).insert(ignore_permissions=True)
		sent += 1
	return sent


def recipients_for(level, lead: dict, role_cache: dict | None = None) -> list[str]:
	"""The owner, the user and the users of the role, once each, enabled users only."""
	role_cache = role_cache if role_cache is not None else {}
	users = []
	if level.notify_owner and lead.get("lead_owner"):
		users.append(lead["lead_owner"])
	if level.notify_user:
		users.append(level.notify_user)
	if level.notify_role:
		if level.notify_role not in role_cache:
			role_cache[level.notify_role] = frappe.get_all(
				"Has Role", filters={"parenttype": "User", "role": level.notify_role}, pluck="parent"
			)
		users += role_cache[level.notify_role]
	users = list(dict.fromkeys(u for u in users if u and u not in ("Administrator", "Guest")))
	if not users:
		return []
	enabled = set(frappe.get_all("User", filters={"name": ["in", users], "enabled": 1}, pluck="name"))
	return [u for u in users if u in enabled]


def notify(rule_doc, lead: dict, level, role_cache: dict) -> list[str]:
	"""Send the CRM Notification for a level to each recipient. Returns the users notified."""
	recipients = recipients_for(level, lead, role_cache)
	text = (level.message or DEFAULT_MESSAGE).replace("{n}", str(lead["idle_minutes"])).replace(
		"{lead}", lead.get("lead_name") or lead["name"]
	)
	for user in recipients:
		frappe.get_doc(
			{
				"doctype": "CRM Notification",
				"type": "Automation",
				"to_user": user,
				"message": _("Idle lead: {0}").format(lead.get("lead_name") or lead["name"]),
				"notification_text": text,
				"reference_doctype": "CRM Lead",
				"reference_name": lead["name"],
			}
		).insert(ignore_permissions=True)
	return recipients
