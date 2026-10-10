import frappe

from abm_crm.duplicates import lead_phone_key
from abm_crm.setup.install import setup_custom_fields


def execute():
	"""Fill the phone key on existing leads, so duplicate detection works for them too."""
	setup_custom_fields()  # the field must exist before it is filled
	frappe.reload_doctype("CRM Lead")
	for lead in frappe.get_all("CRM Lead", fields=["name", "mobile_no", "phone", "abm_phone_key"]):
		key = lead_phone_key(lead)
		if key != (lead.abm_phone_key or None):
			frappe.db.set_value("CRM Lead", lead.name, "abm_phone_key", key, update_modified=False)
