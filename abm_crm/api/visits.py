"""Site visits: planned, held, postponed or cancelled visits to a lead or deal.

Used by the CRM web app and the mobile app (contract: docs/mobile-api.md, "Site visits").
Visits are ABM Field Visit records linked to a lead or deal. A manager sees every visit; anyone else
sees the visits on the leads and deals they can read, and can create or change visits on those they can
write. The photo is a private file, so it is served through `visit_photo`, which checks access to the
lead or deal instead of the visit.
"""

import datetime
import mimetypes
from functools import wraps

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, get_datetime, getdate, now_datetime, nowdate

from abm_crm.abm_crm.doctype.abm_field_visit.abm_field_visit import (
	PEOPLE,
	STATUS_COLORS,
	STATUSES,
	is_manager,
)

CRM_DOCTYPES = ("CRM Lead", "CRM Deal")
VISIT_TYPES = ("Site Visit", "Walk-in", "Office Meeting")
OUTCOMES = ("Interested", "Needs Follow-up", "Not Interested", "Booked")
OPEN_STATUSES = ("Scheduled", "Pending")
UPCOMING_STATUSES = ("Scheduled", "Pending", "Postponed")
VISIT_DATE = "coalesce(v.scheduled_on, v.visited_at, v.creation)"
EDITABLE = (
	"status",
	"visit_type",
	"project",
	"scheduled_on",
	"status_reason",
	"outcome",
	"notes",
	"latitude",
	"longitude",
	"accuracy",
	"address",
	"visited_at",
)
FROM_VISITS = """from `tabABM Field Visit` v
	left join `tabCRM Lead` l on v.reference_doctype = 'CRM Lead' and l.name = v.reference_docname
	left join `tabCRM Deal` d on v.reference_doctype = 'CRM Deal' and d.name = v.reference_docname"""
ROW_COLUMNS = f"""v.name, v.status, v.visit_type, v.project, v.scheduled_on, v.visited_at, v.status_reason,
	v.outcome, v.closing_manager, v.closing_manager_user, v.attended_by, v.attended_by_user,
	v.site_visit_assistant, v.site_visit_assistant_user, v.notes, v.latitude, v.longitude, v.accuracy,
	v.address, v.photo, v.reference_doctype, v.reference_docname, v.visited_by, v.owner, v.creation, v.modified,
	{VISIT_DATE} as visit_date,
	case when v.reference_doctype = 'CRM Lead' then l.lead_name
		else coalesce(nullif(d.organization, ''), d.lead_name) end as reference_title,
	case when v.reference_doctype = 'CRM Lead' then coalesce(nullif(l.mobile_no, ''), l.phone)
		else d.mobile_no end as phone"""


def formatted(fn):
	"""Datetimes as plain strings, like the mobile API."""

	@wraps(fn)
	def wrapper(*args, **kwargs):
		from abm_crm.api.mobile import plain

		return plain(fn(*args, **kwargs))

	return wrapper


def check_reference(doctype: str, name: str, ptype: str = "read"):
	if doctype not in CRM_DOCTYPES:
		frappe.throw(_("Only leads and deals have site visits"))
	frappe.get_doc(doctype, name).check_permission(ptype)


def photo_url(visit_name: str) -> str:
	return f"/api/method/abm_crm.api.visits.visit_photo?visit={visit_name}"


# Rows
# ----


def readable_clause() -> tuple[str, dict]:
	"""SQL limiting visits to the leads and deals the session user can read (nothing for a manager)."""
	if is_manager():
		return "", {}
	leads = frappe.get_list("CRM Lead", pluck="name", limit=1_000_000) or [""]
	deals = frappe.get_list("CRM Deal", pluck="name", limit=1_000_000) or [""]
	sql = (
		"((v.reference_doctype = 'CRM Lead' and v.reference_docname in %(_readable_leads)s)"
		" or (v.reference_doctype = 'CRM Deal' and v.reference_docname in %(_readable_deals)s))"
	)
	return sql, {"_readable_leads": tuple(leads), "_readable_deals": tuple(deals)}


def visit_conditions(
	status=None,
	visit_type=None,
	user=None,
	project=None,
	date_from=None,
	date_to=None,
	search=None,
	reference_doctype=None,
	reference_docname=None,
) -> tuple[list[str], dict]:
	"""WHERE conditions (and values) for the filters shared by the list and the dashboard."""
	where, values = [], {}
	clause, clause_values = readable_clause()
	if clause:
		where.append(clause)
		values.update(clause_values)
	if status:
		where.append("v.status = %(status)s")
		values["status"] = status
	if visit_type:
		where.append("v.visit_type = %(visit_type)s")
		values["visit_type"] = visit_type
	if project:
		where.append("v.project = %(project)s")
		values["project"] = project
	if user:
		where.append(
			"(v.closing_manager_user = %(user)s or v.attended_by_user = %(user)s"
			" or v.site_visit_assistant_user = %(user)s or v.visited_by = %(user)s or v.owner = %(user)s)"
		)
		values["user"] = user
	if date_from:
		where.append(f"{VISIT_DATE} >= %(date_from)s")
		values["date_from"] = day_start(date_from)
	if date_to:
		where.append(f"{VISIT_DATE} < %(date_to)s")
		values["date_to"] = add_days(day_start(date_to), 1)
	if reference_doctype and reference_docname:
		where.append("v.reference_doctype = %(ref_doctype)s and v.reference_docname = %(ref_name)s")
		values.update(ref_doctype=reference_doctype, ref_name=reference_docname)
	if search and search.strip():
		where.append(
			"""(v.project like %(search)s or v.closing_manager like %(search)s or v.attended_by like %(search)s
			or v.site_visit_assistant like %(search)s or l.lead_name like %(search)s
			or d.organization like %(search)s or d.lead_name like %(search)s
			or l.mobile_no like %(search)s or l.phone like %(search)s or d.mobile_no like %(search)s)"""
		)
		escaped = search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
		values["search"] = f"%{escaped}%"
	return where, values


def day_start(value) -> datetime.datetime:
	return datetime.datetime.combine(getdate(value), datetime.time.min)


def query_rows(where: list[str], values: dict, order: str, limit: int, start: int = 0) -> list[dict]:
	"""VisitRows for the matching visits, with two queries in all (visits, then their users)."""
	rows = frappe.db.sql(
		f"""select {ROW_COLUMNS} {FROM_VISITS}
		{"where " + " and ".join(where) if where else ""}
		order by {order} limit %(_limit)s offset %(_start)s""",
		{**values, "_limit": limit, "_start": start},
		as_dict=True,
	)
	return visit_rows(rows)


def user_map(rows: list[dict]) -> dict:
	names = set()
	for r in rows:
		names.update(
			r.get(f)
			for f in ("visited_by", "owner", *(f"{p}_user" for p in PEOPLE))
			if r.get(f)
		)
	if not names:
		return {}
	return {
		u.name: u
		for u in frappe.get_all(
			"User", filters={"name": ["in", list(names)]}, fields=["name", "full_name", "user_image"]
		)
	}


def visit_rows(rows: list[dict]) -> list[dict]:
	"""Turn query rows into VisitRows."""
	users = user_map(rows)

	def full_name(user):
		return (users.get(user) and users[user].full_name) or user

	out = []
	for r in rows:
		row = dict(r)
		row["status_color"] = STATUS_COLORS.get(row["status"], "gray")
		for p in PEOPLE:
			user = row.get(f"{p}_user")
			row[f"{p}_name"] = (full_name(user) if user else row.get(p)) or None
		row["visited_by_name"] = full_name(row["visited_by"]) if row.get("visited_by") else None
		row["visited_by_image"] = users.get(row.get("visited_by")) and users[row["visited_by"]].user_image
		row["owner_name"] = full_name(row["owner"])
		row["photo_url"] = photo_url(row["name"]) if row.get("photo") else None
		has_location = row.get("latitude") or row.get("longitude")
		row["map_url"] = (
			f"https://maps.google.com/?q={row['latitude']},{row['longitude']}" if has_location else None
		)
		out.append(row)
	return out


def get_row(name: str) -> dict:
	rows = frappe.db.sql(
		f"select {ROW_COLUMNS} {FROM_VISITS} where v.name = %s", name, as_dict=True
	)
	if not rows:
		raise frappe.DoesNotExistError(_("Visit {0} not found").format(name))
	return visit_rows(rows)[0]


# Lifecycle API
# -------------


@frappe.whitelist()
def get_visit_options() -> dict:
	"""Choices for the visit form and filters."""
	from abm_crm.api.mobile import crm_users

	projects = set(frappe.db.sql_list("select distinct project from `tabABM Field Visit` where ifnull(project, '') != ''"))
	projects.update(
		frappe.get_all("Tag", filters={"abm_category": ["in", ["Builder", "Project"]]}, pluck="name")
	)
	return {
		"statuses": [{"name": s, "color": STATUS_COLORS[s]} for s in STATUSES],
		"types": list(VISIT_TYPES),
		"outcomes": list(OUTCOMES),
		"projects": sorted(projects, key=str.lower),
		"users": crm_users(),
	}


@frappe.whitelist()
@formatted
def list_visits(
	status: str | None = None,
	visit_type: str | None = None,
	user: str | None = None,
	project: str | None = None,
	date_from: str | None = None,
	date_to: str | None = None,
	search: str | None = None,
	reference_doctype: str | None = None,
	reference_docname: str | None = None,
	start: int = 0,
	page_length: int = 20,
	order_by: str = "date",
) -> dict:
	"""Visits on records the user can read, newest first (`order_by` "upcoming": soonest scheduled first)."""
	start = max(cint(start), 0)
	page_length = min(max(cint(page_length) or 20, 1), 100)
	where, values = visit_conditions(
		status,
		visit_type,
		user,
		project,
		date_from,
		date_to,
		search,
		reference_doctype,
		reference_docname,
	)
	if order_by == "upcoming":
		order = "v.scheduled_on is null, v.scheduled_on asc, v.creation desc"
	else:
		order = f"{VISIT_DATE} desc, v.creation desc"
	rows = query_rows(where, values, order, page_length + 1, start)
	return {"data": rows[:page_length], "has_more": len(rows) > page_length}


@frappe.whitelist()
@formatted
def get_visit(name: str) -> dict:
	visit = frappe.get_doc("ABM Field Visit", name)
	check_reference(visit.reference_doctype, visit.reference_docname)
	return get_row(name)


@frappe.whitelist(methods=["POST"])
@formatted
def create_visit(reference_doctype: str, reference_docname: str, data: dict | str | None = None) -> dict:
	"""Plan or record a visit. Needs write permission on the lead or deal."""
	check_reference(reference_doctype, reference_docname, "write")
	visit = frappe.get_doc(
		{"doctype": "ABM Field Visit", "reference_doctype": reference_doctype, "reference_docname": reference_docname}
	)
	apply_values(visit, frappe.parse_json(data) or {})
	visit.insert(ignore_permissions=True)
	return get_row(visit.name)


@frappe.whitelist(methods=["POST"])
@formatted
def update_visit(name: str, data: dict | str | None = None) -> dict:
	"""Change a visit. Needs write permission on the lead or deal; the status rules apply."""
	visit = frappe.get_doc("ABM Field Visit", name)
	check_reference(visit.reference_doctype, visit.reference_docname, "write")
	apply_values(visit, frappe.parse_json(data) or {})
	visit.save(ignore_permissions=True)
	return get_row(name)


def apply_values(visit, data: dict) -> None:
	for field in EDITABLE:
		if field not in data:
			continue
		if field == "visited_at" and not is_manager() and not visit.is_new():
			continue  # the time of a visit is set when it is marked visited
		value = data[field]
		if field in ("latitude", "longitude", "accuracy"):
			value = flt(value) if value not in (None, "") else None
		visit.set(field, value if value != "" else None)
	for person in PEOPLE:
		user_key = f"{person}_user"
		if user_key in data:
			visit.set(user_key, data[user_key] or None)
			if not data[user_key]:
				visit.set(person, data.get(person) or None)
		elif person in data:
			# a typed name replaces the user
			visit.set(user_key, None)
			visit.set(person, data[person] or None)


@frappe.whitelist(methods=["POST"])
def delete_visit(name: str) -> None:
	"""The person who created the visit, or a manager."""
	visit = frappe.get_doc("ABM Field Visit", name)
	check_reference(visit.reference_doctype, visit.reference_docname)
	if visit.owner != frappe.session.user and not is_manager():
		frappe.throw(_("Only the creator of a visit or a manager can delete it"), frappe.PermissionError)
	frappe.delete_doc("ABM Field Visit", name, ignore_permissions=True)


@frappe.whitelist(methods=["POST"])
@formatted
def upload_visit_photo(name: str) -> dict:
	"""Attach the photo sent as the multipart field `file`."""
	from abm_crm.api.mobile import IMAGE_EXTENSIONS, attach_file, check_extension, uploaded_file

	visit = frappe.get_doc("ABM Field Visit", name)
	check_reference(visit.reference_doctype, visit.reference_docname, "write")
	upload = uploaded_file()
	if not upload:
		frappe.throw(_("Send the photo as the file field"))
	check_extension(upload[0], IMAGE_EXTENSIONS)
	file = attach_file(upload[0], upload[1], "ABM Field Visit", name, "photo")
	frappe.db.set_value("ABM Field Visit", name, "photo", file.file_url)
	return get_row(name)


# Activity feed and notifications
# -------------------------------

TYPE_LABELS = {"Site Visit": "Site visit", "Walk-in": "Walk-in", "Office Meeting": "Office meeting"}


def when(value) -> str:
	return get_datetime(value).strftime("%d %b, %I:%M %p").lstrip("0")


def visit_summary(visit) -> str:
	label = TYPE_LABELS.get(visit.visit_type, "Site visit")
	place = f" at {visit.project}" if visit.project else ""
	if visit.status == "Visited":
		return f"{label} completed{place}"
	if visit.status in ("Scheduled", "Pending") and visit.scheduled_on:
		return f"{label} scheduled for {when(visit.scheduled_on)}{place}"
	if visit.status == "Postponed":
		return f"{label} postponed to {when(visit.scheduled_on)}{place}"
	if visit.status == "Cancelled":
		return f"{label} cancelled{place}"
	if visit.status == "No Show":
		return f"{label}: no show{place}"
	return f"{label} added{place}"


def same_time(a, b) -> bool:
	return (get_datetime(a) if a else None) == (get_datetime(b) if b else None)


def visit_saved(visit, before) -> None:
	"""After a visit is created or changed: comment on the lead or deal and tell new people."""
	changed = (
		before is None
		or before.status != visit.status
		or (visit.status in UPCOMING_STATUSES and same_time(before.scheduled_on, visit.scheduled_on) is False)
	)
	if changed:
		text = visit_summary(visit)
		reason = visit.status_reason if visit.status in ("Cancelled", "Postponed", "No Show") else None
		html = f"<p>{frappe.utils.escape_html(text)}</p>"
		if reason:
			html += f"<p>{frappe.utils.escape_html(reason)}</p>"
		frappe.get_doc(
			{
				"doctype": "Comment",
				"comment_type": "Comment",
				"reference_doctype": visit.reference_doctype,
				"reference_name": visit.reference_docname,
				"content": html,
			}
		).insert(ignore_permissions=True)
	elif before.outcome != visit.outcome and visit.outcome:
		frappe.get_doc(
			{
				"doctype": "Comment",
				"comment_type": "Comment",
				"reference_doctype": visit.reference_doctype,
				"reference_name": visit.reference_docname,
				"content": f"<p>{frappe.utils.escape_html(_('Site visit outcome: {0}').format(_(visit.outcome)))}</p>",
			}
		).insert(ignore_permissions=True)

	for person in PEOPLE:
		user = visit.get(f"{person}_user")
		if user and (before is None or before.get(f"{person}_user") != user):
			notify_person(visit, user)


def notify_person(visit, user: str) -> None:
	if user == frappe.session.user:
		return
	title = reference_title(visit.reference_doctype, visit.reference_docname)
	detail = f"Site visit assigned: {title}"
	if visit.scheduled_on:
		detail += f", {when(visit.scheduled_on)}"
	if visit.project:
		detail += f" at {visit.project}"
	frappe.get_doc(
		{
			"doctype": "CRM Notification",
			"type": "Automation",
			"from_user": frappe.session.user,
			"to_user": user,
			"message": f"Site visit assigned: {title}",
			"notification_text": detail,
			"reference_doctype": visit.reference_doctype,
			"reference_name": visit.reference_docname,
		}
	).insert(ignore_permissions=True)


def reference_title(doctype: str, name: str) -> str:
	if doctype == "CRM Lead":
		return frappe.db.get_value("CRM Lead", name, "lead_name") or name
	org, lead_name = frappe.db.get_value("CRM Deal", name, ["organization", "lead_name"]) or (None, None)
	return org or lead_name or name


# Dashboard
# ---------


@frappe.whitelist()
@formatted
def visit_dashboard(
	date_from: str | None = None,
	date_to: str | None = None,
	user: str | None = None,
	project: str | None = None,
	visit_type: str | None = None,
) -> dict:
	"""Visit numbers for the month (or the given range): totals, by status, person, project, type and day."""
	today = getdate(nowdate())
	date_from = date_from or today.replace(day=1).isoformat()
	date_to = date_to or add_days(add_days(today.replace(day=1), 32).replace(day=1), -1).isoformat()
	base, values = visit_conditions(visit_type=visit_type, user=user, project=project)
	ranged, ranged_values = visit_conditions(
		visit_type=visit_type, user=user, project=project, date_from=date_from, date_to=date_to
	)
	where = " where " + " and ".join(ranged) if ranged else ""
	from_v = "from `tabABM Field Visit` v"
	booked = "sum(case when v.outcome = 'Booked' then 1 else 0 end)"

	by_status_rows = frappe.db.sql(
		f"select v.status, count(*), {booked} {from_v}{where} group by v.status", ranged_values
	)
	counts = {s: cint(c) for s, c, _b in by_status_rows}
	booked_total = sum(cint(b) for _s, _c, b in by_status_rows)
	by_type = frappe.db.sql(
		f"select v.visit_type, count(*) {from_v}{where} group by v.visit_type order by 2 desc", ranged_values
	)
	project_where = f"{where} and" if where else " where"
	by_project = frappe.db.sql(
		f"""select v.project, count(*), sum(case when v.status = 'Visited' then 1 else 0 end), {booked}
		{from_v}{project_where} ifnull(v.project, '') != '' group by v.project order by 2 desc, 1 limit 50""",
		ranged_values,
	)
	by_day = frappe.db.sql(
		f"""select date({VISIT_DATE}) as day,
			sum(case when v.scheduled_on is not null then 1 else 0 end),
			sum(case when v.status = 'Visited' then 1 else 0 end)
		{from_v}{where} group by day order by day""",
		ranged_values,
	)
	people = frappe.db.sql(
		f"""select v.name, v.status, v.closing_manager, v.closing_manager_user, v.attended_by, v.attended_by_user,
			v.site_visit_assistant, v.site_visit_assistant_user {from_v}{where}""",
		ranged_values,
		as_dict=True,
	)

	now = now_datetime()
	tomorrow = add_days(day_start(today), 1)
	extra = frappe.db.sql(
		f"""select
			sum(case when {VISIT_DATE} >= %(today)s and {VISIT_DATE} < %(tomorrow)s then 1 else 0 end),
			sum(case when v.status in %(upcoming_statuses)s and v.scheduled_on >= %(now)s
				and v.scheduled_on < %(week)s then 1 else 0 end),
			sum(case when v.status in %(open_statuses)s and v.scheduled_on < %(now)s then 1 else 0 end)
		{from_v}{" where " + " and ".join(base) if base else ""}""",
		{
			**values,
			"today": day_start(today),
			"tomorrow": tomorrow,
			"now": now,
			"week": add_days(now, 7),
			"upcoming_statuses": UPCOMING_STATUSES,
			"open_statuses": OPEN_STATUSES,
		},
	)[0]
	today_n, upcoming_n, overdue_n = (cint(x) for x in extra)

	def listing(extra_where, extra_values, order, limit):
		return query_rows(
			[*base, extra_where], {**values, **extra_values}, order, limit
		)

	today_rows = listing(
		f"{VISIT_DATE} >= %(today)s and {VISIT_DATE} < %(tomorrow)s",
		{"today": day_start(today), "tomorrow": tomorrow},
		f"{VISIT_DATE} asc",
		50,
	)
	upcoming_rows = listing(
		"v.status in %(upcoming_statuses)s and v.scheduled_on >= %(now)s",
		{"upcoming_statuses": UPCOMING_STATUSES, "now": now},
		"v.scheduled_on asc",
		10,
	)
	overdue_rows = listing(
		"v.status in %(open_statuses)s and v.scheduled_on < %(now)s",
		{"open_statuses": OPEN_STATUSES, "now": now},
		"v.scheduled_on asc",
		10,
	)

	visited, cancelled, no_show = counts.get("Visited", 0), counts.get("Cancelled", 0), counts.get("No Show", 0)
	finished = visited + cancelled + no_show
	totals = {
		"total": sum(counts.values()),
		**{s.lower().replace(" ", "_"): counts.get(s, 0) for s in STATUSES},
		"today": today_n,
		"upcoming_7d": upcoming_n,
		"overdue": overdue_n,
		"booked": booked_total,
		"completion_rate": round(visited * 100 / finished, 1) if finished else 0.0,
	}
	return {
		"range": {"date_from": date_from, "date_to": date_to},
		"totals": totals,
		"by_status": [{"status": s, "color": STATUS_COLORS[s], "count": counts.get(s, 0)} for s in STATUSES],
		"by_user": by_user(people),
		"by_project": [
			{"project": p, "total": cint(t), "visited": cint(v), "booked": cint(b)}
			for p, t, v, b in by_project
		],
		"by_type": [{"visit_type": t, "count": cint(c)} for t, c in by_type],
		"by_day": [{"date": str(d), "scheduled": cint(s), "visited": cint(v)} for d, s, v in by_day],
		"today": today_rows,
		"upcoming": upcoming_rows,
		"overdue": overdue_rows,
	}


def by_user(visits: list[dict]) -> list[dict]:
	"""Per person: their visits by status and in each role. A person counts once per visit per role."""
	roles = {"closing_manager": "as_closing_manager", "attended_by": "as_attended_by", "site_visit_assistant": "as_assistant"}
	people = {}
	for v in visits:
		for field, counter in roles.items():
			user, name = v.get(f"{field}_user"), (v.get(field) or "").strip()
			if not user and not name:
				continue
			key = user or name.lower()
			entry = people.setdefault(
				key,
				{
					"user": user,
					"name": name or user,
					"user_image": None,
					"visits": {},
					"as_closing_manager": 0,
					"as_attended_by": 0,
					"as_assistant": 0,
				},
			)
			entry[counter] += 1
			entry["visits"][v["name"]] = v["status"]
	users = {
		u.name: u
		for u in frappe.get_all(
			"User",
			filters={"name": ["in", [p["user"] for p in people.values() if p["user"]] or [""]]},
			fields=["name", "full_name", "user_image"],
		)
	}
	result = []
	for p in people.values():
		statuses = list(p.pop("visits").values())
		user = users.get(p["user"])
		if user:
			p["name"], p["user_image"] = user.full_name or user.name, user.user_image
		p["total"] = len(statuses)
		for s in STATUSES:
			p[s.lower().replace(" ", "_")] = statuses.count(s)
		result.append(p)
	result.sort(key=lambda p: (-p["total"], p["name"].lower()))
	return [
		{
			k: p[k]
			for k in (
				"user",
				"name",
				"user_image",
				"total",
				"visited",
				"scheduled",
				"pending",
				"postponed",
				"cancelled",
				"no_show",
				"as_closing_manager",
				"as_attended_by",
				"as_assistant",
			)
		}
		for p in result
	]


# On a lead or deal
# -----------------


@frappe.whitelist()
@formatted
def get_visits(doctype: str, name: str) -> list[dict]:
	"""Visits to a lead or deal, newest first. A deal also shows the visits made while it was a lead."""
	check_reference(doctype, name)
	conditions = ["(v.reference_doctype = %(doctype)s and v.reference_docname = %(name)s)"]
	values = {"doctype": doctype, "name": name}
	if doctype == "CRM Deal":
		lead = frappe.db.get_value("CRM Deal", name, "lead")
		if lead:
			conditions.append("(v.reference_doctype = 'CRM Lead' and v.reference_docname = %(lead)s)")
			values["lead"] = lead
	return query_rows(
		[f"({' or '.join(conditions)})"], values, f"{VISIT_DATE} desc, v.creation desc", 200
	)


@frappe.whitelist()
def visit_photo(visit: str):
	"""The visit's photo, for anyone who can read the visited lead or deal."""
	row = frappe.db.get_value(
		"ABM Field Visit", visit, ["reference_doctype", "reference_docname", "photo"], as_dict=True
	)
	if not row or not row.photo:
		raise frappe.DoesNotExistError(_("No photo for this visit"))
	check_reference(row.reference_doctype, row.reference_docname)

	# only the file uploaded for this visit; never another file whose URL was typed into `photo`
	file_name = frappe.db.get_value(
		"File",
		{"file_url": row.photo, "attached_to_doctype": "ABM Field Visit", "attached_to_name": visit},
		"name",
	)
	if not file_name:
		raise frappe.DoesNotExistError(_("Photo file not found"))
	file = frappe.get_doc("File", file_name)

	frappe.local.response.filename = file.file_name
	frappe.local.response.filecontent = file.get_content()
	frappe.local.response.type = "download"
	frappe.local.response.display_content_as = "inline"
	frappe.local.response.content_type = mimetypes.guess_type(file.file_name)[0] or "image/jpeg"
