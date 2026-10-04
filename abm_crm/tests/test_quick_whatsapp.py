import frappe
from frappe.tests import IntegrationTestCase

from abm_crm.api.quick_whatsapp import get_contact_links, get_quick_whatsapp, log_quick_whatsapp


class TestQuickWhatsApp(IntegrationTestCase):
	def setUp(self):
		frappe.db.set_single_value("ABM CRM Settings", "default_phone_region", "IN")
		for name in frappe.get_all("ABM WhatsApp Template", pluck="name"):
			frappe.delete_doc("ABM WhatsApp Template", name, force=True)
		frappe.get_doc(
			{
				"doctype": "ABM WhatsApp Template",
				"template_name": "Hello",
				"message": "Hi {{ doc.first_name }}, this is {{ user.first_name }}",
				"applies_to": "Both",
			}
		).insert()
		frappe.get_doc(
			{
				"doctype": "ABM WhatsApp Template",
				"template_name": "Deals only",
				"message": "Deal message",
				"applies_to": "CRM Deal",
			}
		).insert()
		self.lead = frappe.get_doc(
			{"doctype": "CRM Lead", "first_name": "Ravi", "mobile_no": "98765 43210"}
		).insert(ignore_permissions=True)

	def test_templates_render_and_number_is_international(self):
		data = get_quick_whatsapp("CRM Lead", self.lead.name)
		self.assertEqual(data["wa_number"], "919876543210")
		self.assertEqual([t["name"] for t in data["templates"]], ["Hello"])
		self.assertTrue(data["templates"][0]["message"].startswith("Hi Ravi, this is"))

	def test_contact_links(self):
		links = get_contact_links("CRM Lead", self.lead.name)
		self.assertEqual(links["tel"], "+919876543210")
		self.assertEqual(links["wa_number"], "919876543210")

	def test_log_creates_history_and_comment(self):
		log_quick_whatsapp("CRM Lead", self.lead.name, "Hello there", "Hello")
		history = get_quick_whatsapp("CRM Lead", self.lead.name)["history"]
		self.assertEqual(history[0]["message"], "Hello there")
		self.assertTrue(
			frappe.db.exists(
				"Comment",
				{"reference_name": self.lead.name, "content": ["like", "%WhatsApp message opened%"]},
			)
		)

	def test_missing_number_explains(self):
		lead = frappe.get_doc({"doctype": "CRM Lead", "first_name": "NoPhone"}).insert(ignore_permissions=True)
		data = get_quick_whatsapp("CRM Lead", lead.name)
		self.assertIsNone(data["wa_number"])
		self.assertIn("mobile number", data["error"])

	def test_only_crm_doctypes(self):
		self.assertRaises(frappe.ValidationError, get_quick_whatsapp, "User", "Administrator")
