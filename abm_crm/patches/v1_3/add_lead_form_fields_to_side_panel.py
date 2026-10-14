import json

import frappe

from abm_crm.setup.install import setup_custom_fields

NEW_FIELDS = ("abm_lead_sync_source", "abm_form_answers")


def execute():
	"""Show the lead form (Lead Sync Source) and its unmapped answers in the side panel's Campaign section.

	Only where the Campaign section is still there; a team that removed it keeps its layout.
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
		fields = section["columns"][0].setdefault("fields", [])
		present = {f for column in section["columns"] for f in column.get("fields") or []}
		if "abm_lead_sync_source" not in present:
			fields.insert(0, "abm_lead_sync_source")
		if "abm_form_answers" not in present:
			fields.append("abm_form_answers")
		frappe.db.set_value("CRM Fields Layout", name, "layout", json.dumps(layout))
