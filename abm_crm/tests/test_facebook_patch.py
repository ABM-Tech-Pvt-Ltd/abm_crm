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


class TestFacebookDuplicates(IntegrationTestCase):
	def setUp(self):
		apply()

	def tearDown(self):
		for name in frappe.get_all("CRM Lead", filters={"facebook_lead_id": ["like", "TEST-FB-DUP-%"]}, pluck="name"):
			frappe.delete_doc("CRM Lead", name, force=True, ignore_permissions=True)
		for name in frappe.get_all("Failed Lead Sync Log", filters={"lead_data": ["like", "%TEST-FB-DUP-%"]}, pluck="name"):
			frappe.delete_doc("Failed Lead Sync Log", name, force=True, ignore_permissions=True)
		if not frappe.db.exists("Tag Link", {"tag": "Duplicate"}):
			frappe.delete_doc("Tag", "Duplicate", force=True, ignore_permissions=True)

	def lead(self, lead_id, phone):
		return {
			"id": lead_id,
			"field_data": [
				{"name": "full_name", "values": ["Facebook Dup Test"]},
				{"name": "phone_number", "values": [phone]},
				{"name": "email"},
			],
		}

	def test_same_person_again_is_created_and_tagged_duplicate(self):
		source = make_source()
		first = source.sync_single_lead(self.lead("TEST-FB-DUP-1", "+919957200201"), raise_exception=True)
		second = source.sync_single_lead(self.lead("TEST-FB-DUP-2", "09957200201"), raise_exception=True)
		self.assertTrue(second)
		self.assertNotEqual(first.name, second.name)
		tags = (frappe.db.get_value("CRM Lead", second.name, "_user_tags") or "").lower()
		self.assertIn("duplicate", tags)

	def test_same_facebook_lead_is_skipped_without_a_log_entry(self):
		source = make_source()
		source.sync_single_lead(self.lead("TEST-FB-DUP-3", "+919957200301"), raise_exception=True)
		self.assertIsNone(source.sync_single_lead(self.lead("TEST-FB-DUP-3", "+919957200301")))
		self.assertEqual(frappe.db.count("CRM Lead", {"facebook_lead_id": "TEST-FB-DUP-3"}), 1)
		self.assertFalse(frappe.db.exists("Failed Lead Sync Log", {"lead_data": ["like", "%TEST-FB-DUP-3%"]}))


class TestFacebookSyncWindow(IntegrationTestCase):
	def setUp(self):
		apply()

	def test_threshold_is_the_last_sync_time_not_midnight(self):
		from unittest.mock import patch

		from abm_crm.monkey_patches import SYNC_OVERLAP_HOURS, sync_threshold

		with patch("frappe.utils.get_system_timezone", return_value="Asia/Kolkata"):
			# a sync at 01:00 IST; leads from 00:04 IST must still be asked for
			threshold = sync_threshold("2026-10-17 01:00:00")
		# 01:00 IST = 19:30 UTC the day before
		expected = 1792179000 - SYNC_OVERLAP_HOURS * 3600
		self.assertEqual(threshold, expected)
		lead_at_0004_ist = 1792175640
		self.assertLess(threshold, lead_at_0004_ist)

	def test_fetch_follows_pages_and_uses_the_threshold(self):
		from unittest.mock import patch

		from crm.lead_syncing.doctype.lead_sync_source import facebook

		pages = [
			{"data": [{"id": "1"}], "paging": {"next": "https://graph.facebook.com/next"}},
			{"data": [{"id": "2"}]},
		]
		calls = []

		def fake_get(url, params=None):
			calls.append((url, params))
			return pages[len(calls) - 1]

		source = facebook.FacebookSyncSource("token", "TESTFORM-WINDOW")
		with patch.object(facebook, "make_get_request", side_effect=fake_get):
			leads = source.fetch_leads(since="2026-10-17 01:00:00")
		self.assertEqual([lead["id"] for lead in leads], ["1", "2"])
		self.assertIn("time_created", calls[0][1]["filtering"])
		self.assertEqual(calls[1], ("https://graph.facebook.com/next", None))
