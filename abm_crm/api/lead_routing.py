import frappe
from frappe import _

from abm_crm.lead_routing import route

MANAGER_ROLES = ("System Manager", "Sales Manager")
RULE_FIELDS = (
	"rule_name",
	"enabled",
	"priority",
	"lead_source",
	"lead_sync_source",
	"facebook_lead_form",
	"platform",
	"campaign_match",
	"campaign",
	"adset",
	"ad",
	"territory",
	"condition",
	"strategy",
	"fallback_user",
)


@frappe.whitelist()
def get_routing_setup() -> dict:
	"""Rules plus every option the Lead Routing settings page needs, in one call."""
	frappe.only_for(MANAGER_ROLES)

	rules = []
	for name in frappe.get_all("ABM Lead Routing Rule", order_by="priority desc, creation asc", pluck="name"):
		doc = frappe.get_doc("ABM Lead Routing Rule", name)
		rule = {f: doc.get(f) for f in (*RULE_FIELDS, "name", "last_user", "assigned_count")}
		rule["users"] = [
			{"user": r.user, "active": r.active, "max_open_leads": r.max_open_leads} for r in doc.users
		]
		rules.append(rule)

	return {
		"rules": rules,
		"users": frappe.get_all(
			"User",
			filters={"enabled": 1, "user_type": "System User", "name": ["not in", ["Administrator", "Guest"]]},
			fields=["name", "full_name"],
			order_by="full_name asc",
		),
		"lead_sources": frappe.get_all("CRM Lead Source", pluck="name", order_by="name asc"),
		"sync_sources": frappe.get_all(
			"Lead Sync Source", fields=["name", "facebook_lead_form", "enabled"], order_by="name asc"
		),
		"facebook_forms": frappe.get_all(
			"Facebook Lead Form", fields=["name", "form_name", "page"], order_by="form_name asc"
		),
		"territories": frappe.get_all("CRM Territory", pluck="name", order_by="name asc"),
		# values already seen on leads, offered as suggestions
		"campaigns": distinct_values("abm_campaign"),
		"adsets": distinct_values("abm_adset"),
		"ads": distinct_values("abm_ad"),
	}


def distinct_values(field: str, limit: int = 200) -> list[str]:
	return frappe.db.sql_list(
		f"""select distinct `{field}` from `tabCRM Lead`
		where ifnull(`{field}`, '') != '' order by creation desc limit %s""",
		(limit,),
	)


@frappe.whitelist()
def save_routing_rule(rule: dict) -> str:
	frappe.only_for(MANAGER_ROLES)
	rule = frappe._dict(frappe.parse_json(rule))

	if rule.get("name"):
		name = rule.name
		new_name = (rule.get("rule_name") or "").strip()
		if new_name and new_name != name:
			# the rule name is the document name (Frappe resets it on save), so rename first;
			# links on already routed leads follow the rename
			name = frappe.rename_doc("ABM Lead Routing Rule", name, new_name)
		doc = frappe.get_doc("ABM Lead Routing Rule", name)
	else:
		doc = frappe.new_doc("ABM Lead Routing Rule")

	doc.update({f: rule.get(f) for f in RULE_FIELDS if f in rule})
	doc.set("users", [])
	for row in rule.get("users") or []:
		if row.get("user"):
			doc.append(
				"users",
				{
					"user": row["user"],
					"active": row.get("active", 1),
					"max_open_leads": row.get("max_open_leads") or 0,
				},
			)

	doc.save()
	return doc.name


@frappe.whitelist()
def set_rule_enabled(name: str, enabled: int) -> None:
	frappe.only_for(MANAGER_ROLES)
	frappe.db.set_value("ABM Lead Routing Rule", name, "enabled", 1 if frappe.utils.cint(enabled) else 0)


@frappe.whitelist()
def delete_routing_rule(name: str) -> None:
	frappe.only_for(MANAGER_ROLES)
	frappe.delete_doc("ABM Lead Routing Rule", name)


@frappe.whitelist()
def test_routing(lead: str) -> dict:
	"""Dry run: which rule and user an existing lead would get if it arrived now."""
	frappe.only_for(MANAGER_ROLES)
	doc = frappe.get_doc("CRM Lead", lead)
	result = route(doc, dry_run=True)
	return {
		"lead": doc.name,
		"lead_name": doc.lead_name,
		"campaign": doc.get("abm_campaign"),
		"rule": result and result["rule"],
		"user": result and result["user"],
		"message": _("Matches rule {0}, would assign to {1}").format(result["rule"], result["user"])
		if result
		else _("No rule matches. Frappe Assignment Rules (if any) would apply."),
	}
