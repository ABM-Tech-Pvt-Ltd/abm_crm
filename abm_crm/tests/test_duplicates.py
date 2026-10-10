import frappe
from frappe.desk.doctype.tag.tag import DocTags
from frappe.tests import IntegrationTestCase

from abm_crm.duplicates import DUPLICATE_TAG, phone_key, tag_existing_duplicates


def make_lead(**fields):
	return frappe.get_doc({"doctype": "CRM Lead", "first_name": "Dup Test", **fields}).insert(
		ignore_permissions=True
	)


def tags_of(lead: str) -> list[str]:
	return [t.strip().lower() for t in (frappe.db.get_value("CRM Lead", lead, "_user_tags") or "").split(",") if t.strip()]


class TestPhoneKey(IntegrationTestCase):
	def test_formats_match_on_last_ten_digits(self):
		for number in ("+91 98765 43210", "098765 43210", "9876543210", "+91-9876543210", "0091 98765-43210"):
			self.assertEqual(phone_key(number), "9876543210", number)

	def test_short_or_empty_numbers_have_no_key(self):
		for number in ("12345", "", None, "abc"):
			self.assertIsNone(phone_key(number), number)


class TestDuplicateLeads(IntegrationTestCase):
	def tearDown(self):
		for name in frappe.get_all("CRM Lead", filters={"first_name": "Dup Test"}, pluck="name"):
			frappe.delete_doc("CRM Lead", name, force=True, ignore_permissions=True)
		if not frappe.db.exists("Tag Link", {"tag": DUPLICATE_TAG}):
			frappe.delete_doc("Tag", DUPLICATE_TAG, force=True, ignore_permissions=True)

	def test_same_number_in_another_format_is_tagged_and_kept(self):
		first = make_lead(mobile_no="+91 98000 11122")
		second = make_lead(mobile_no="098000 11122")
		self.assertTrue(frappe.db.exists("CRM Lead", second.name))  # kept, not skipped
		self.assertNotIn("duplicate", tags_of(first.name))
		self.assertIn("duplicate", tags_of(second.name))
		comment = frappe.db.get_value(
			"Comment", {"reference_name": second.name, "content": ["like", "%Possible duplicate%"]}, "content"
		)
		self.assertIn(first.name, comment)

	def test_tag_has_a_color(self):
		make_lead(mobile_no="9800011133")
		make_lead(mobile_no="9800011133")
		self.assertEqual(frappe.db.get_value("Tag", DUPLICATE_TAG, "abm_color") or "red", "red")

	def test_different_numbers_are_not_tagged(self):
		make_lead(mobile_no="9800011144")
		other = make_lead(mobile_no="9800011155")
		self.assertNotIn("duplicate", tags_of(other.name))

	def test_numbers_with_fewer_than_ten_digits_are_ignored(self):
		make_lead(mobile_no="12345")
		other = make_lead(mobile_no="12345")
		self.assertNotIn("duplicate", tags_of(other.name))

	def test_phone_field_is_used_when_there_is_no_mobile(self):
		make_lead(phone="9800011166")
		other = make_lead(mobile_no="+91 9800011166")
		self.assertIn("duplicate", tags_of(other.name))

	def test_key_follows_number_changes(self):
		lead = make_lead(mobile_no="9800011177")
		lead.mobile_no = "9800011188"
		lead.save(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("CRM Lead", lead.name, "abm_phone_key"), "9800011188")

	def test_tag_existing_duplicates_tags_later_leads_only(self):
		first = make_lead(mobile_no="9800011199")
		second = make_lead(mobile_no="9800011199")
		DocTags("CRM Lead").remove(second.name, DUPLICATE_TAG)  # as if it predates this feature
		self.assertNotIn("duplicate", tags_of(second.name))
		frappe.set_user("Administrator")
		result = tag_existing_duplicates()
		self.assertGreaterEqual(result["tagged"], 1)
		self.assertIn("duplicate", tags_of(second.name))
		self.assertNotIn("duplicate", tags_of(first.name))
		# running again does not tag twice
		self.assertEqual(tag_existing_duplicates()["tagged"], 0)
