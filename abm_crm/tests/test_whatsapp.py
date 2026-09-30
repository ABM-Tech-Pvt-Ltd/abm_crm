from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from abm_crm.api.whatsapp import send_whatsapp_template, to_whatsapp_number


class TestWhatsAppNumbers(IntegrationTestCase):
	def setUp(self):
		frappe.db.set_single_value("ABM CRM Settings", "default_phone_region", "IN")

	def test_local_numbers_get_country_code(self):
		for number in ("9876543210", "09876543210", "+91 98765 43210", "0091 9876543210"):
			self.assertEqual(to_whatsapp_number(number), "919876543210")

	def test_invalid_numbers_are_rejected(self):
		self.assertRaises(frappe.ValidationError, to_whatsapp_number, "12345")

	def test_meta_error_is_explained(self):
		def fail(**kwargs):
			frappe.throw("Failed to send message (#131030) Recipient phone number not in allowed list")

		with patch("crm.api.whatsapp.send_whatsapp_template", side_effect=fail):
			with self.assertRaises(frappe.ValidationError) as ctx:
				send_whatsapp_template("CRM Lead", "any", "hello_world", "9876543210")
		self.assertIn("allowed list", str(ctx.exception))
		self.assertIn("+919876543210", str(ctx.exception))
