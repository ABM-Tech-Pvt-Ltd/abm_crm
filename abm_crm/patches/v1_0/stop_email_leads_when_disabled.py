import frappe


def execute():
	"""Existing email accounts with "Create lead from incoming email" off still had "Append To" set
	to CRM Lead, so Frappe kept creating a lead for every incoming email. Clear it (see
	abm_crm.api.email_account.sync_lead_creation, which keeps it that way on every save)."""
	if not frappe.get_meta("Email Account").has_field("create_lead_from_incoming_email"):
		return
	accounts = frappe.get_all(
		"Email Account", filters={"create_lead_from_incoming_email": 0}, pluck="name"
	)
	for name in accounts:
		# direct updates: saving an Email Account logs in to the mail server
		frappe.db.set_value("Email Account", {"name": name, "append_to": "CRM Lead"}, "append_to", None)
		frappe.db.set_value(
			"IMAP Folder",
			{"parenttype": "Email Account", "parent": name, "append_to": "CRM Lead"},
			"append_to",
			None,
		)
	frappe.clear_cache(doctype="Email Account")
