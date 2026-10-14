import json

import frappe

from abm_crm.lead_routing import migrate_text_answers
from abm_crm.setup.install import setup_custom_fields

FORM_ANSWERS_SECTION = {
	"label": "Form Answers",
	"name": "abm_form_answers_section",
	"opened": True,
	"columns": [{"name": "abm_form_answers_column", "fields": ["abm_form_answer_rows"]}],
}


def execute():
	"""Replace the "Other Form Answers" text with the Form Answers table.

	- the old text field leaves the side panel (the side panel cannot show a table);
	- the table gets its own section in the Data tab;
	- leads and deals with old text but no rows get rows parsed from the text. The text is kept, hidden.
	"""
	setup_custom_fields()
	remove_text_field_from_side_panel()
	add_form_answers_section()
	migrate_text_answers()


def remove_text_field_from_side_panel():
	for dt in ("CRM Lead", "CRM Deal"):
		name = f"{dt}-Side Panel"
		if not frappe.db.exists("CRM Fields Layout", name):
			continue
		layout = json.loads(frappe.db.get_value("CRM Fields Layout", name, "layout") or "[]")
		changed = False
		for section in layout:
			for column in section.get("columns") or []:
				if "abm_form_answers" in (column.get("fields") or []):
					column["fields"] = [f for f in column["fields"] if f != "abm_form_answers"]
					changed = True
		if changed:
			frappe.db.set_value("CRM Fields Layout", name, "layout", json.dumps(layout))


def add_form_answers_section():
	"""Add the Form Answers section at the end of the lead and deal Data tab, unless the table is
	already placed. Also run on install (patches are skipped on a fresh install)."""
	for dt in ("CRM Lead", "CRM Deal"):
		name = f"{dt}-Data Fields"
		# without a saved layout crm shows every field of the doctype, the table included
		if not frappe.db.exists("CRM Fields Layout", name):
			continue
		layout = json.loads(frappe.db.get_value("CRM Fields Layout", name, "layout") or "[]")
		if "abm_form_answer_rows" in json.dumps(layout):
			continue
		# a layout is a list of sections, or of tabs that hold sections
		has_tabs = any("sections" in item for item in layout if isinstance(item, dict))
		sections = layout[0].setdefault("sections", []) if has_tabs else layout
		sections.append(json.loads(json.dumps(FORM_ANSWERS_SECTION)))
		frappe.db.set_value("CRM Fields Layout", name, "layout", json.dumps(layout))
