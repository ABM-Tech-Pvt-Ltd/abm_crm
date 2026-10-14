from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from abm_crm import lead_routing

FORM = "TESTFORM-ANSWERS"
FIELD_DATA = [
	{"name": "full_name", "values": ["Form Answers Test"]},
	{"name": "phone_number", "values": ["+919957200401"]},
	{"name": "what_is_your_budget?", "values": ["1-2 Cr"]},
	{"name": "preferred_location", "values": ["Thane", "Wakad"]},
	{"name": "email"},  # left blank on the form
]


class TestFormAnswers(IntegrationTestCase):
	def setUp(self):
		# questions as crm stores them for a synced form: two mapped, two not
		frappe.db.delete("Facebook Lead Form Question", {"parent": FORM})
		for key, label, mapped in (
			("full_name", "Full name", "first_name"),
			("phone_number", "Phone number", "mobile_no"),
			("what_is_your_budget?", "What is your budget?", None),
		):
			frappe.get_doc(
				{
					"doctype": "Facebook Lead Form Question",
					"parent": FORM,
					"parenttype": "Facebook Lead Form",
					"parentfield": "questions",
					"key": key,
					"label": label,
					"mapped_to_crm_field": mapped,
				}
			).db_insert()

	def tearDown(self):
		frappe.db.delete("Facebook Lead Form Question", {"parent": FORM})
		for name in frappe.get_all("CRM Lead", filters={"facebook_lead_id": ["like", "TEST-FA-%"]}, pluck="name"):
			frappe.delete_doc("CRM Lead", name, force=True, ignore_permissions=True)

	def test_only_unmapped_answers_are_kept(self):
		self.assertEqual(
			lead_routing.unmapped_answers(FIELD_DATA, FORM),
			# question label when crm knows it, else the key made readable; blank answers dropped
			"What is your budget?: 1-2 Cr\nPreferred location: Thane, Wakad",
		)
		self.assertIsNone(lead_routing.unmapped_answers([], FORM))

	def test_new_facebook_lead_gets_its_answers(self):
		with (
			patch.object(lead_routing, "get_sync_source_token", return_value="token"),
			patch.object(lead_routing, "fetch_facebook_lead", return_value={"campaign_id": "C1", "field_data": FIELD_DATA}),
		):
			lead = frappe.get_doc(
				{
					"doctype": "CRM Lead",
					"first_name": "Form Answers Test",
					"facebook_lead_id": "TEST-FA-1",
					"facebook_form_id": FORM,
				}
			).insert(ignore_permissions=True)
		self.assertIn("What is your budget?: 1-2 Cr", lead.abm_form_answers)
		self.assertEqual(lead.abm_campaign_id, "C1")
