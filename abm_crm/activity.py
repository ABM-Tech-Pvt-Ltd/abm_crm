"""When a lead or deal last had activity, and when it was last contacted.

last_activity: the latest of the record's modified time, its latest call, comment and email.
last_contacted: the latest call, email or WhatsApp message.
Shared by the lead info in the mobile API, the team report and the idle-lead alerts.
"""

import frappe
from frappe.utils import get_datetime

IN_LIMIT = 500  # with more records than this, group the whole table instead of listing every name


def latest_times(doctype: str, names: list[str] | None = None) -> dict[str, dict]:
	"""{name: {"call", "comment", "email", "whatsapp"}} latest times, one grouped query per source.

	`names` limits the search; None (or a long list) reads the whole table, which is cheaper than a
	huge IN list.
	"""
	scoped = bool(names) and len(names) <= IN_LIMIT
	sources = {
		"call": (
			"CRM Call Log",
			"reference_doctype",
			"reference_docname",
			"coalesce(start_time, creation)",
			"",
		),
		"comment": ("Comment", "reference_doctype", "reference_name", "creation", "and comment_type = 'Comment'"),
		"email": (
			"Communication",
			"reference_doctype",
			"reference_name",
			"coalesce(communication_date, creation)",
			"and communication_type = 'Communication'",
		),
		"whatsapp": ("ABM WhatsApp Log", "reference_doctype", "reference_name", "creation", ""),
	}
	result: dict[str, dict] = {}
	for key, (table, type_field, name_field, expr, extra) in sources.items():
		rows = frappe.db.sql(
			f"""select {name_field}, max({expr}) from `tab{table}`
			where {type_field} = %(doctype)s {extra}
			{f"and {name_field} in %(names)s" if scoped else ""}
			group by {name_field}""",
			{"doctype": doctype, "names": tuple(names or [""])},
		)
		for name, at in rows:
			if at:
				result.setdefault(name, {})[key] = at
	return result


def activity_times(doctype: str, modified: dict) -> dict[str, tuple]:
	"""{name: (last_activity, last_contacted)} for records given as {name: modified}."""
	latest = latest_times(doctype, list(modified))
	out = {}
	for name, changed in modified.items():
		t = latest.get(name, {})
		activity = [x for x in (changed, t.get("call"), t.get("comment"), t.get("email")) if x]
		contacted = [x for x in (t.get("call"), t.get("email"), t.get("whatsapp")) if x]
		out[name] = (
			max(get_datetime(x) for x in activity) if activity else None,
			max(get_datetime(x) for x in contacted) if contacted else None,
		)
	return out


def idle_minutes(last_activity, now) -> int | None:
	"""Wall-clock minutes from the last activity to now."""
	if not last_activity:
		return None
	return max(int((get_datetime(now) - get_datetime(last_activity)).total_seconds() // 60), 0)
