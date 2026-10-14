import json

import frappe

from abm_crm.setup.install import setup_custom_fields


def execute():
	"""Show the lead form (Lead Sync Source) in the side panel's Campaign section.

	Only where the Campaign section is still there; a team that removed it keeps its layout.
	The form's unmapped answers are a table in the Data tab instead (v1_4).
	"""
	setup_custom_fields()
	for dt in ("CRM Lead", "CRM Deal"):
		name = f"{dt}-Side Panel"
		if not frappe.db.exists("CRM Fields Layout", name):
			continue
		layout = json.loads(frappe.db.get_value("CRM Fields Layout", name, "layout") or "[]")
		section = next((s for s in layout if s.get("name") == "abm_campaign_section"), None)
		if not section or not section.get("columns"):
			continue
		present = {f for column in section["columns"] for f in column.get("fields") or []}
		if "abm_lead_sync_source" in present:
			continue
		section["columns"][0].setdefault("fields", []).insert(0, "abm_lead_sync_source")
		frappe.db.set_value("CRM Fields Layout", name, "layout", json.dumps(layout))
