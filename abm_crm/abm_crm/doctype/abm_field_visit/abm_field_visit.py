# Copyright (c) 2026, Aman Boora and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
import datetime

from frappe.utils import get_datetime, now_datetime

CRM_DOCTYPES = ("CRM Lead", "CRM Deal")
MANAGER_ROLES = ("System Manager", "Sales Manager")


class ABMFieldVisit(Document):
	def validate(self):
		if self.reference_doctype not in CRM_DOCTYPES:
			frappe.throw(_("A site visit must be linked to a lead or a deal"))
		if not frappe.db.exists(self.reference_doctype, self.reference_docname):
			frappe.throw(_("{0} {1} not found").format(_(self.reference_doctype), self.reference_docname))
		frappe.get_doc(self.reference_doctype, self.reference_docname).check_permission("read")

	def before_insert(self):
		# reps can only record their own visit, made now (manager dashboards count these)
		if not set(frappe.get_roles()) & set(MANAGER_ROLES):
			self.visited_by = frappe.session.user
			self.visited_at = recent_or_now(self.visited_at)
		self.visited_by = self.visited_by or frappe.session.user
		self.visited_at = self.visited_at or now_datetime()


def recent_or_now(value):
	"""A visit time from the app (an offline check-in synced later), if it is from the last 3 days."""
	now = now_datetime()
	try:
		at = get_datetime(value) if value else None
	except Exception:
		at = None
	if at and now - datetime.timedelta(days=3) <= at <= now + datetime.timedelta(minutes=5):
		return min(at, now)
	return now
