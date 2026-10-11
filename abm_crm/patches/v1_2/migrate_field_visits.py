import frappe


def execute():
	"""Visits recorded before the visit lifecycle are completed site visits."""
	frappe.reload_doc("abm_crm", "doctype", "abm_field_visit")
	frappe.db.sql(
		"""update `tabABM Field Visit` set status = 'Visited', visit_type = 'Site Visit'
		where ifnull(status, '') in ('', 'Pending') and visited_at is not null"""
	)
