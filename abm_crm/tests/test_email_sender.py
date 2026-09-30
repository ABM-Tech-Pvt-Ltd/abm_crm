import frappe
from frappe.tests import IntegrationTestCase

from abm_crm.api.email import _get_sender_options

USER = "sender.test@example.com"


class TestSenderOptions(IntegrationTestCase):
	def setUp(self):
		if not frappe.db.exists("User", USER):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": USER,
					"first_name": "Sender",
					"send_welcome_email": 0,
					"roles": [{"role": "Sales User"}],
				}
			).insert(ignore_permissions=True)
		for name, email in (("ABM Test Sales", "sales@abm.test"), ("ABM Test Support", "support@abm.test")):
			if not frappe.db.exists("Email Account", name):
				account = frappe.new_doc("Email Account")
				account.update(
					{"email_account_name": name, "email_id": email, "enable_outgoing": 1, "smtp_server": "localhost"}
				)
				account.name = name
				account.db_insert()  # skip the SMTP login check
		for name in frappe.get_all("ABM Email Sender", pluck="name"):
			frappe.delete_doc("ABM Email Sender", name, force=True)

	def test_role_and_everyone_rules(self):
		frappe.get_doc(
			{"doctype": "ABM Email Sender", "email_account": "ABM Test Sales", "applies_to": "Role", "role": "Sales User", "is_default": 1}
		).insert()
		frappe.get_doc(
			{"doctype": "ABM Email Sender", "email_account": "ABM Test Support", "applies_to": "Everyone"}
		).insert()
		options = _get_sender_options(USER)
		self.assertEqual([o["value"] for o in options][:2], ["sales@abm.test", "support@abm.test"])
		self.assertTrue(options[0]["is_default"])

	def test_rules_for_other_users_are_ignored(self):
		frappe.get_doc(
			{"doctype": "ABM Email Sender", "email_account": "ABM Test Sales", "applies_to": "User", "user": "Administrator"}
		).insert()
		self.assertNotIn("sales@abm.test", [o["value"] for o in _get_sender_options(USER)])
