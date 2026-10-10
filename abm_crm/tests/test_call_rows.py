import time

import frappe
from frappe.tests import IntegrationTestCase

from abm_crm.monkey_patches import apply

EMAIL = "call.rows@example.com"
NUMBER = "+919800077701"


class TestCallRows(IntegrationTestCase):
	def setUp(self):
		apply()
		if not frappe.db.exists("User", EMAIL):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": EMAIL,
					"first_name": "Call Rows",
					"mobile_no": "+919800077799",
					"send_welcome_email": 0,
					"roles": [{"role": "Sales Manager"}, {"role": "Sales User"}],
				}
			).insert(ignore_permissions=True)
		self.lead = frappe.get_doc(
			{"doctype": "CRM Lead", "first_name": "Call Rows Lead", "mobile_no": NUMBER}
		).insert(ignore_permissions=True)
		frappe.set_user(EMAIL)

	def tearDown(self):
		frappe.set_user("Administrator")
		for name in frappe.get_all("CRM Call Log", filters={"reference_docname": self.lead.name}, pluck="name"):
			frappe.delete_doc("CRM Call Log", name, force=True, ignore_permissions=True)
		frappe.delete_doc("CRM Lead", self.lead.name, force=True, ignore_permissions=True)

	def sync_one(self):
		from abm_crm.api.mobile import sync_calls

		ms = int(time.time() * 1000) - 60000
		result = sync_calls(
			[{"device_call_id": "7001", "number": NUMBER, "type": "outgoing", "start": ms, "duration": 15}],
			"callrows12345678",
		)
		return result[0]["call_log"]

	def call_names(self):
		from crm.api.activities import get_activities

		return [c["name"] for c in get_activities(self.lead.name)[1]]

	def test_synced_call_is_listed_once_and_not_linked_twice(self):
		call_log = self.sync_one()
		self.assertTrue(call_log)
		self.assertEqual(frappe.get_doc("CRM Call Log", call_log).links, [])  # referenced, not linked
		self.assertEqual(self.call_names(), [call_log])

	def test_calls_saved_with_both_reference_and_link_are_listed_once(self):
		call_log = self.sync_one()
		doc = frappe.get_doc("CRM Call Log", call_log)
		doc.link_with_reference_doc("CRM Lead", self.lead.name)  # how older syncs saved them
		doc.save(ignore_permissions=True)
		self.assertEqual(self.call_names(), [call_log])
