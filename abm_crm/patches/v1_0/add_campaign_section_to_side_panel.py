import json

import frappe

from abm_crm.setup.install import setup_custom_fields

CAMPAIGN_SECTION = {
	"label": "Campaign",
	"name": "abm_campaign_section",
	"opened": False,
	"columns": [
		{
			"name": "abm_campaign_column",
			"fields": ["abm_campaign", "abm_adset", "abm_ad", "abm_platform", "abm_routing_rule"],
		}
	],
}


def execute():
	"""Show campaign attribution in the lead and deal side panel. Runs once; users can remove it."""
	setup_custom_fields()  # the fields must exist before the layout references them
	for dt in ("CRM Lead", "CRM Deal"):
		name = f"{dt}-Side Panel"
		if not frappe.db.exists("CRM Fields Layout", name):
			continue
		layout = json.loads(frappe.db.get_value("CRM Fields Layout", name, "layout") or "[]")
		if any(section.get("name") == CAMPAIGN_SECTION["name"] for section in layout):
			continue
		layout.append(CAMPAIGN_SECTION)
		frappe.db.set_value("CRM Fields Layout", name, "layout", json.dumps(layout))
