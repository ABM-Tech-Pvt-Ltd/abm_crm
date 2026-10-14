from unittest.mock import patch

import frappe
from crm.fcrm.doctype.crm_lead.crm_lead import convert_to_deal
from frappe.tests import IntegrationTestCase

from abm_crm import lead_routing
from abm_crm.api import mobile

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
			for deal in frappe.get_all("CRM Deal", filters={"lead": name}, pluck="name"):
				frappe.delete_doc("CRM Deal", deal, force=True, ignore_permissions=True)
			frappe.delete_doc("CRM Lead", name, force=True, ignore_permissions=True)

	def make_facebook_lead(self, lead_id="TEST-FA-1"):
		with (
			patch.object(lead_routing, "get_sync_source_token", return_value="token"),
			patch.object(lead_routing, "fetch_facebook_lead", return_value={"campaign_id": "C1", "field_data": FIELD_DATA}),
		):
			return frappe.get_doc(
				{
					"doctype": "CRM Lead",
					"first_name": "Form Answers Test",
					"facebook_lead_id": lead_id,
					"facebook_form_id": FORM,
				}
			).insert(ignore_permissions=True)

	def answers(self, doc):
		return [(r.question, r.answer) for r in doc.abm_form_answer_rows]

	def test_only_unmapped_answers_are_kept(self):
		self.assertEqual(
			lead_routing.unmapped_answers(FIELD_DATA, FORM),
			# question label when crm knows it, else the key made readable; blank answers dropped
			[
				{"question": "What is your budget?", "answer": "1-2 Cr", "question_key": "what_is_your_budget?"},
				{"question": "Preferred location", "answer": "Thane, Wakad", "question_key": "preferred_location"},
			],
		)
		self.assertEqual(lead_routing.unmapped_answers([], FORM), [])

	def test_new_facebook_lead_gets_its_answers(self):
		lead = self.make_facebook_lead()
		self.assertEqual(self.answers(lead), [("What is your budget?", "1-2 Cr"), ("Preferred location", "Thane, Wakad")])
		self.assertEqual(lead.abm_form_answer_rows[0].question_key, "what_is_your_budget?")
		self.assertFalse(lead.abm_form_answers)  # the old text field is no longer written
		self.assertEqual(lead.abm_campaign_id, "C1")

	def test_deal_copies_answers(self):
		lead = self.make_facebook_lead()
		deal = frappe.get_doc("CRM Deal", convert_to_deal(lead.name))
		self.assertEqual(self.answers(deal), self.answers(lead))
		# the deal has its own rows; the lead keeps its own
		self.assertEqual(frappe.db.count("ABM Lead Form Answer", {"parenttype": "CRM Lead", "parent": lead.name}), 2)

		record = mobile.get_record("CRM Deal", deal.name)["doc"]
		self.assertEqual(
			record["form_answers"],
			[
				{"question": "What is your budget?", "answer": "1-2 Cr"},
				{"question": "Preferred location", "answer": "Thane, Wakad"},
			],
		)
		self.assertNotIn("abm_form_answers", record)
		self.assertNotIn("abm_form_answer_rows", record)
		fields = [f["fieldname"] for f in mobile.form_fields("CRM Lead")]
		self.assertNotIn("abm_form_answer_rows", fields)

	def test_old_text_becomes_rows(self):
		self.assertEqual(
			lead_routing.answers_from_text("Budget: 1-2 Cr\n\nTime: 10:30 am\ncall after 6\n"),
			# split on the first ": "; a line without one continues the answer above
			[
				{"question": "Budget", "answer": "1-2 Cr", "question_key": None},
				{"question": "Time", "answer": "10:30 am\ncall after 6", "question_key": None},
			],
		)
		old = frappe.get_doc(
			{"doctype": "CRM Lead", "first_name": "Form Answers Test", "facebook_lead_id": "TEST-FA-OLD"}
		)
		old.flags.skip_lead_routing = True
		with patch.object(lead_routing, "get_sync_source_token", return_value=None):
			old.insert(ignore_permissions=True)
		frappe.db.set_value("CRM Lead", old.name, "abm_form_answers", "Budget: 1-2 Cr\nCity: Pune")
		has_rows = self.make_facebook_lead("TEST-FA-2")
		frappe.db.set_value("CRM Lead", has_rows.name, "abm_form_answers", "Ignored: yes")

		lead_routing.migrate_text_answers()
		lead_routing.migrate_text_answers()  # safe to run again
		old.reload()
		self.assertEqual(self.answers(old), [("Budget", "1-2 Cr"), ("City", "Pune")])
		self.assertEqual(old.abm_form_answers, "Budget: 1-2 Cr\nCity: Pune")  # the text is kept
		has_rows.reload()
		self.assertEqual(len(has_rows.abm_form_answer_rows), 2)
