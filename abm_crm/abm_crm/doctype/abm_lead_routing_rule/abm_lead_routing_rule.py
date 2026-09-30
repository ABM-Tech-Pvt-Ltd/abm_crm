# Copyright (c) 2026, Aman Boora and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class ABMLeadRoutingRule(Document):
	def validate(self):
		seen = set()
		for row in self.users:
			if row.user in seen:
				frappe.throw(_("User {0} is listed more than once").format(row.user))
			seen.add(row.user)

		if self.condition:
			try:
				compile(self.condition, "<condition>", "eval")
			except SyntaxError as e:
				frappe.throw(_("Extra Condition is not a valid Python expression: {0}").format(e))
