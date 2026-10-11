# Copyright (c) 2026, Aman Boora and contributors
# For license information, please see license.txt

from frappe import _
import frappe
from frappe.model.document import Document


class ABMIdleLeadRule(Document):
	def validate(self):
		from abm_crm.idle_alerts import as_time

		if as_time(self.work_end) <= as_time(self.work_start):
			frappe.throw(_("Work End must be after Work Start"))
		if not any(self.get(day) for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")):
			frappe.throw(_("Pick at least one working day"))
		if not self.levels:
			frappe.throw(_("Add at least one alert level"))
		seen = set()
		for row in self.levels:
			if (row.idle_minutes or 0) <= 0:
				frappe.throw(_("Row {0}: idle minutes must be more than 0").format(row.idx))
			if row.idle_minutes in seen:
				frappe.throw(_("Row {0}: there is already a level at {1} minutes").format(row.idx, row.idle_minutes))
			seen.add(row.idle_minutes)
			if not (row.notify_owner or row.notify_user or row.notify_role):
				frappe.throw(_("Row {0}: choose who to notify").format(row.idx))
		statuses = [row.status for row in self.statuses]
		if len(statuses) != len(set(statuses)):
			frappe.throw(_("A status is listed more than once"))
