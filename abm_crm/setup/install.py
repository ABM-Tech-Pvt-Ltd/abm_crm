import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

# Defaults for ABM CRM Settings. A single doctype stores nothing until it is saved, so unsaved
# Check fields read as 0 instead of their JSON default.
SETTINGS_DEFAULTS = {
	"include_user_email_accounts": 1,
	"include_default_outgoing": 1,
	"default_phone_region": "IN",
	"whatsapp_mode": "Click to Chat",
	"call_sync_scope": "CRM numbers only",
	"upload_recordings": 1,
	"push_enabled": 1,
}


def after_install():
	setup_custom_fields()
	setup_settings_defaults()
	setup_whatsapp_templates()
	add_campaign_section()


def after_migrate():
	setup_custom_fields()
	setup_settings_defaults()
	setup_whatsapp_templates()


def add_campaign_section():
	# patches are marked done on a fresh install without running, so run this one here once.
	# Not on every migrate: users may remove the section from the side panel.
	from abm_crm.patches.v1_0.add_campaign_section_to_side_panel import execute

	execute()


DEFAULT_WHATSAPP_TEMPLATES = [
	(
		"Introduction",
		"Hi {{ doc.first_name or '' }}, this is {{ user.first_name }}{% if brand %} from {{ brand }}{% endif %}. "
		"Thanks for your interest! When is a good time for a quick call?",
	),
	(
		"Missed your call",
		"Hi {{ doc.first_name or '' }}, I tried calling you just now. Please let me know a convenient time to talk.",
	),
	(
		"Follow-up",
		"Hi {{ doc.first_name or '' }}, just following up on our conversation. Do you have any questions I can help with?",
	),
	(
		"Share details",
		"Hi {{ doc.first_name or '' }}, as discussed, here are the details: ",
	),
	(
		"Meeting reminder",
		"Hi {{ doc.first_name or '' }}, a quick reminder about our meeting. Looking forward to speaking with you.",
	),
]


def setup_whatsapp_templates():
	"""Add a few starter templates the first time. Never touches templates that already exist."""
	if frappe.db.count("ABM WhatsApp Template"):
		return
	for i, (name, message) in enumerate(DEFAULT_WHATSAPP_TEMPLATES):
		frappe.get_doc(
			{
				"doctype": "ABM WhatsApp Template",
				"template_name": name,
				"message": message,
				"applies_to": "Both",
				"sort_order": i,
			}
		).insert(ignore_permissions=True)


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
		"CRM Call Log": [call_outcome_field()],
		"Tag": tag_fields(),
	}


TAG_CATEGORIES = ("Builder", "Project", "Location", "Budget", "Other")
TAG_COLORS = (
	"gray",
	"blue",
	"green",
	"red",
	"pink",
	"orange",
	"amber",
	"yellow",
	"cyan",
	"teal",
	"violet",
	"purple",
)


def tag_fields():
	"""Category and color for Frappe's Tag, used to group and color tags on leads and deals."""
	return [
		{
			"fieldname": "abm_category",
			"label": "Category",
			"fieldtype": "Select",
			"options": "\n" + "\n".join(TAG_CATEGORIES),
			"insert_after": "description",
			"in_list_view": 1,
			"in_standard_filter": 1,
			"module": "Abm Crm",
		},
		{
			"fieldname": "abm_color",
			"label": "Color",
			"fieldtype": "Select",
			"options": "\n" + "\n".join(TAG_COLORS),
			"insert_after": "abm_category",
			"in_list_view": 1,
			"module": "Abm Crm",
		},
	]


CALL_OUTCOMES = ("Interested", "Not Interested", "Call Back", "No Answer", "Wrong Number", "Busy", "Converted")


def call_outcome_field():
	"""What came of a call, set by the rep from the mobile app."""
	return {
		"fieldname": "abm_outcome",
		"label": "Outcome",
		"fieldtype": "Select",
		"options": "\n" + "\n".join(CALL_OUTCOMES),
		"insert_after": "status",
		"in_standard_filter": 1,
		"module": "Abm Crm",
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
