import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

# Defaults for ABM CRM Settings. A single doctype stores nothing until it is saved, so unsaved
# Check fields read as 0 instead of their JSON default.
SETTINGS_DEFAULTS = {
	"include_user_email_accounts": 1,
	"include_default_outgoing": 1,
	"default_phone_region": "IN",
}


def after_install():
	setup_custom_fields()
	setup_settings_defaults()


def after_migrate():
	setup_custom_fields()
	setup_settings_defaults()


def setup_settings_defaults():
	"""Store defaults for settings that were never saved. Keeps values users already set."""
	for field, value in SETTINGS_DEFAULTS.items():
		stored = frappe.db.sql(
			"select 1 from `tabSingles` where doctype=%s and field=%s", ("ABM CRM Settings", field)
		)
		if not stored:
			frappe.db.set_single_value("ABM CRM Settings", field, value)


def setup_custom_fields():
	"""Create or update abm_crm's custom fields on crm doctypes. Safe to run repeatedly."""
	create_custom_fields(get_custom_fields(), ignore_validate=True, update=True)


def get_custom_fields():
	# Set "module": "Abm Crm" on each field so it is owned by this app.
	return {
		"CRM Lead": [*campaign_fields(), routing_rule_field()],
		"CRM Deal": [*campaign_fields(), routing_rule_field()],
	}


def campaign_fields():
	"""Where a lead came from. Filled from Facebook for synced leads, or mapped from web forms."""
	fields = [
		("abm_campaign_section", "Campaign", "Section Break"),
		("abm_campaign", "Campaign", "Data"),
		("abm_adset", "Ad Set", "Data"),
		("abm_ad", "Ad", "Data"),
		("abm_platform", "Platform", "Data"),
		("abm_campaign_column", None, "Column Break"),
		("abm_campaign_id", "Campaign ID", "Data"),
		("abm_adset_id", "Ad Set ID", "Data"),
		("abm_ad_id", "Ad ID", "Data"),
		("abm_lead_sync_source", "Lead Sync Source", "Link"),
	]
	result = []
	for fieldname, label, fieldtype in fields:
		field = {
			"fieldname": fieldname,
			"label": label,
			"fieldtype": fieldtype,
			"module": "Abm Crm",
		}
		if fieldtype == "Section Break":
			field["collapsible"] = 1
		if fieldtype == "Link":
			field["options"] = "Lead Sync Source"
		if fieldtype == "Data":
			field["in_standard_filter"] = fieldname in ("abm_campaign", "abm_platform")
		result.append(field)
	return result


def routing_rule_field():
	return {
		"fieldname": "abm_routing_rule",
		"label": "Routing Rule",
		"fieldtype": "Link",
		"options": "ABM Lead Routing Rule",
		"read_only": 1,
		"module": "Abm Crm",
	}
