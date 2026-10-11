"""Setup and reports for idle-lead alerts. The engine is in abm_crm/idle_alerts.py; contract in docs/mobile-api.md."""

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from abm_crm.api.mobile import MANAGER_ROLES, formatted, is_manager
from abm_crm.idle_alerts import DAY_FIELDS, idle_leads, normalize_rule, run_check

RULE_FLAGS = ("enabled", "only_assigned", *DAY_FIELDS)
LEVEL_FIELDS = ("idle_minutes", "notify_owner", "notify_user", "notify_role", "message")


def rule_dict(doc) -> dict:
	rule = {
		"name": doc.name,
		"rule_name": doc.rule_name,
		"work_start": str(doc.work_start)[:8],
		"work_end": str(doc.work_end)[:8],
		"statuses": [row.status for row in doc.statuses],
		"levels": [{f: row.get(f) for f in LEVEL_FIELDS} for row in doc.levels],
		"modified": doc.modified,
	}
	rule.update({f: cint(doc.get(f)) for f in RULE_FLAGS})
	return rule


@frappe.whitelist()
@formatted
def get_setup() -> dict:
	"""Rules and the choices for the setup screen."""
	frappe.only_for(MANAGER_ROLES)
	rules = frappe.get_all("ABM Idle Lead Rule", pluck="name", order_by="rule_name asc")
	return {
		"rules": [rule_dict(frappe.get_doc("ABM Idle Lead Rule", name)) for name in rules],
		"statuses": frappe.get_all(
			"CRM Lead Status", fields=["name", "color", "type"], order_by="position asc"
		),
		"users": frappe.get_all(
			"User",
			filters={"enabled": 1, "user_type": "System User", "name": ["not in", ("Administrator", "Guest")]},
			fields=["name", "full_name"],
			order_by="full_name asc",
		),
		"roles": frappe.get_all("Role", filters={"disabled": 0, "desk_access": 1}, pluck="name", order_by="name asc"),
	}


@frappe.whitelist(methods=["POST"])
def save_rule(rule: dict | str) -> str:
	"""Create or update a rule. A rule with `name` is updated (and renamed when `rule_name` differs)."""
	frappe.only_for(MANAGER_ROLES)
	rule = frappe.parse_json(rule) or {}
	new_name = (rule.get("rule_name") or "").strip()
	if not new_name:
		frappe.throw(_("Rule name is required"))
	name = rule.get("name")
	if name and frappe.db.exists("ABM Idle Lead Rule", name):
		if name != new_name:
			frappe.rename_doc("ABM Idle Lead Rule", name, new_name)
		doc = frappe.get_doc("ABM Idle Lead Rule", new_name)
	else:
		doc = frappe.new_doc("ABM Idle Lead Rule")
		doc.rule_name = new_name
	for field in RULE_FLAGS:
		if field in rule:
			doc.set(field, cint(rule[field]))
	for field in ("work_start", "work_end"):
		if rule.get(field):
			doc.set(field, rule[field])
	if "statuses" in rule:
		doc.set("statuses", [{"status": s} for s in rule["statuses"] or []])
	if "levels" in rule:
		doc.set(
			"levels",
			[{**{f: lv.get(f) for f in LEVEL_FIELDS}, "notify_owner": cint(lv.get("notify_owner"))} for lv in rule["levels"] or []],
		)
	doc.save()
	return doc.name


@frappe.whitelist(methods=["POST"])
def delete_rule(name: str) -> None:
	"""Delete a rule and its alert log."""
	frappe.only_for(MANAGER_ROLES)
	frappe.db.delete("ABM Idle Lead Alert", {"rule": name})
	frappe.delete_doc("ABM Idle Lead Rule", name)


@frappe.whitelist(methods=["POST"])
def set_rule_enabled(name: str, enabled: int) -> None:
	frappe.only_for(MANAGER_ROLES)
	frappe.db.set_value("ABM Idle Lead Rule", name, "enabled", 1 if cint(enabled) else 0)


@frappe.whitelist()
@formatted
def preview_rule(rule: dict | str) -> dict:
	"""Leads a level of this rule would alert right now. Sends nothing and saves nothing."""
	frappe.only_for(MANAGER_ROLES)
	rows = idle_leads(normalize_rule(frappe.parse_json(rule) or {}), now_datetime())
	names = owner_names(rows)
	return {
		"idle_now": len(rows),
		"leads": [
			{
				"name": r["name"],
				"lead_name": r["lead_name"],
				"owner_name": names.get(r["lead_owner"]),
				"status": r["status"],
				"idle_minutes": r["idle_minutes"],
			}
			for r in rows[:20]
		],
	}


def owner_names(rows: list[dict]) -> dict:
	users = {r["lead_owner"] for r in rows if r.get("lead_owner")}
	if not users:
		return {}
	return dict(
		frappe.get_all("User", filters={"name": ["in", list(users)]}, fields=["name", "full_name"], as_list=True)
	)


def page(rows: list, start, page_length) -> tuple[list, bool]:
	start, page_length = max(cint(start), 0), min(max(cint(page_length) or 20, 1), 100)
	return rows[start : start + page_length], start + page_length < len(rows)


@frappe.whitelist()
@formatted
def list_idle_leads(
	rule: str | None = None, user: str | None = None, start: int = 0, page_length: int = 20
) -> dict:
	"""Leads that are idle now, per rule (a lead can be idle for several rules). Others see their own leads."""
	if not is_manager():
		user = frappe.session.user
	now = now_datetime()
	names = [rule] if rule else frappe.get_all("ABM Idle Lead Rule", {"enabled": 1}, pluck="name")
	rows = []
	for name in names:
		for r in idle_leads(normalize_rule(frappe.get_doc("ABM Idle Lead Rule", name)), now):
			if user and r["lead_owner"] != user:
				continue
			rows.append({**r, "rule": name, "level": r["due"][-1].idle_minutes})
	rows.sort(key=lambda r: -r["idle_minutes"])
	data, has_more = page(rows, start, page_length)
	owners = owner_names(data)
	return {
		"data": [
			{
				"name": r["name"],
				"lead_name": r["lead_name"],
				"status": r["status"],
				"lead_owner": r["lead_owner"],
				"owner_name": owners.get(r["lead_owner"]),
				"idle_minutes": r["idle_minutes"],
				"last_activity": r["last_activity"],
				"rule": r["rule"],
				"level": r["level"],
			}
			for r in data
		],
		"has_more": has_more,
	}


@frappe.whitelist()
@formatted
def list_alerts(
	rule: str | None = None, lead: str | None = None, start: int = 0, page_length: int = 20
) -> dict:
	"""The alert log, newest first. Others see the alerts on their own leads."""
	filters = {}
	if rule:
		filters["rule"] = rule
	if lead:
		filters["lead"] = lead
	if not is_manager():
		own = frappe.get_all("CRM Lead", {"lead_owner": frappe.session.user}, pluck="name")
		filters["lead"] = ["in", [lead] if lead in own else own or [""]]
	start, page_length = max(cint(start), 0), min(max(cint(page_length) or 20, 1), 100)
	rows = frappe.get_all(
		"ABM Idle Lead Alert",
		filters=filters,
		fields=["name", "rule", "lead", "level", "idle_minutes", "activity_marker", "sent_to", "creation"],
		order_by="creation desc",
		start=start,
		page_length=page_length + 1,
	)
	data = rows[:page_length]
	names = dict(
		frappe.get_all(
			"CRM Lead", filters={"name": ["in", [r.lead for r in data] or [""]]}, fields=["name", "lead_name"], as_list=True
		)
	)
	return {"data": [{**r, "lead_name": names.get(r.lead)} for r in data], "has_more": len(rows) > page_length}


@frappe.whitelist(methods=["POST"])
def run_now() -> dict:
	"""Run the idle-lead check once, now."""
	frappe.only_for(MANAGER_ROLES)
	return {"alerts": run_check()}
