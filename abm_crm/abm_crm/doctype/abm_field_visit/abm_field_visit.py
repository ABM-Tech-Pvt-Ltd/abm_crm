# Copyright (c) 2026, Aman Boora and contributors
# For license information, please see license.txt

import datetime

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime, now_datetime

CRM_DOCTYPES = ("CRM Lead", "CRM Deal")
MANAGER_ROLES = ("System Manager", "Sales Manager")
STATUSES = ("Pending", "Scheduled", "Visited", "Postponed", "Cancelled", "No Show")
FINAL_STATUSES = ("Visited", "Cancelled")
NEEDS_SCHEDULE = ("Scheduled", "Postponed")
STATUS_COLORS = {
	"Pending": "gray",
	"Scheduled": "blue",
	"Visited": "green",
	"Postponed": "orange",
	"Cancelled": "red",
	"No Show": "pink",
}
PEOPLE = ("closing_manager", "attended_by", "site_visit_assistant")


class ABMFieldVisit(Document):
	def validate(self):
		if self.reference_doctype not in CRM_DOCTYPES:
			frappe.throw(_("A site visit must be linked to a lead or a deal"))
		if not frappe.db.exists(self.reference_doctype, self.reference_docname):
			frappe.throw(_("{0} {1} not found").format(_(self.reference_doctype), self.reference_docname))
		frappe.get_doc(self.reference_doctype, self.reference_docname).check_permission("read")
		self.fill_people()
		self.check_status()

	def fill_people(self):
		"""A person is a name plus an optional user. A user must be enabled and fills the name."""
		for field in PEOPLE:
			user = self.get(f"{field}_user")
			if user:
				if not frappe.db.get_value("User", user, "enabled"):
					frappe.throw(_("{0} is not an enabled user").format(user))
				self.set(field, frappe.db.get_value("User", user, "full_name") or user)
			elif self.get(field):
				self.set(field, self.get(field).strip())

	def check_status(self):
		before = None if self.is_new() else self.get_doc_before_save()
		if self.status not in STATUSES:
			frappe.throw(_("Unknown visit status {0}").format(self.status))
		if self.is_new() and self.status == "Pending" and self.scheduled_on:
			self.status = "Scheduled"
		if before and before.status in FINAL_STATUSES and before.status != self.status and not is_manager():
			frappe.throw(_("A {0} visit can only be changed by a manager").format(_(before.status)))
		if self.status in NEEDS_SCHEDULE and not self.scheduled_on:
			frappe.throw(_("A {0} visit needs a scheduled time").format(_(self.status)))
		if self.status == "Visited" and not self.visited_at:
			self.visited_at = now_datetime()

	def before_insert(self):
		# reps can only record their own visit; a check-in time is accepted only when it is recent
		if not is_manager():
			self.visited_by = frappe.session.user
		self.visited_by = self.visited_by or frappe.session.user
		if self.status == "Visited":
			self.visited_at = recent_or_now(self.visited_at) if not is_manager() else (self.visited_at or now_datetime())
		elif not is_manager():
			self.visited_at = None

	def after_insert(self):
		from abm_crm.api.visits import visit_saved

		visit_saved(self, None)

	def on_update(self):
		if not self.flags.in_insert:
			from abm_crm.api.visits import visit_saved

			visit_saved(self, self.get_doc_before_save())


def is_manager() -> bool:
	return bool(set(MANAGER_ROLES) & set(frappe.get_roles()))


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
