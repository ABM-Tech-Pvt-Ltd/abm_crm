# Copyright (c) 2026, Aman Boora and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class ABMEmailSender(Document):
	def validate(self):
		if self.applies_to != "User":
			self.user = None
		if self.applies_to != "Role":
			self.role = None

		if not frappe.db.get_value("Email Account", self.email_account, "enable_outgoing"):
			frappe.throw(_("Email Account {0} does not have outgoing enabled").format(self.email_account))
