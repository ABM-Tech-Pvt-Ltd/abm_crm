import frappe
from frappe.tests import IntegrationTestCase

from abm_crm.monkey_patches import apply

BLANK = {
	"id": "TEST-FB-PATCH-1",
	"field_data": [
		{"name": "full_name", "values": ["Blank Field Test"]},
		{"name": "phone_number", "values": ["+919957200101"]},
		{"name": "email"},  # left empty on the form: Facebook sends no "values"
		{"name": "inbox_url"},
	],
}


def make_source():
	from crm.lead_syncing.doctype.lead_sync_source.facebook import FacebookSyncSource

	source = FacebookSyncSource("token", "TESTFORM-PATCH")
	source.form_questions_mapping = {"email": "email", "full_name": "first_name", "phone_number": "mobile_no"}
	return source


class TestFacebookBlankFields(IntegrationTestCase):
	def setUp(self):
		apply()

	def tearDown(self):
		for name in frappe.get_all("CRM Lead", filters={"facebook_lead_id": ["like", "TEST-FB-PATCH-%"]}, pluck="name"):
			frappe.delete_doc("CRM Lead", name, force=True, ignore_permissions=True)
		for name in frappe.get_all("Failed Lead Sync Log", filters={"lead_data": ["like", "%TEST-FB-PATCH-%"]}, pluck="name"):
			frappe.delete_doc("Failed Lead Sync Log", name, force=True, ignore_permissions=True)

	def test_lead_with_blank_field_is_created(self):
		lead = make_source().sync_single_lead(BLANK, raise_exception=True)
		self.assertEqual(lead.first_name, "Blank Field Test")
		self.assertEqual(lead.mobile_no, "+919957200101")
		self.assertFalse(lead.email)
		self.assertEqual(lead.source, "Facebook")

	def test_same_lead_twice_is_not_duplicated(self):
		source = make_source()
		source.sync_single_lead(BLANK, raise_exception=True)
		source.sync_single_lead(BLANK)  # crm logs it as a duplicate and carries on
		self.assertEqual(frappe.db.count("CRM Lead", {"facebook_lead_id": BLANK["id"]}), 1)

	def test_patch_is_idempotent(self):
		from crm.lead_syncing.doctype.lead_sync_source.facebook import FacebookSyncSource

		before = FacebookSyncSource.sync_single_lead
		apply()
		apply()
		self.assertIs(FacebookSyncSource.sync_single_lead, before)
