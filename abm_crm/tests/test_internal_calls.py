"""Tests for "Internal calls are not logged" in docs/mobile-api.md."""

import time

import frappe
from frappe.tests import IntegrationTestCase

from abm_crm.api import mobile

REP = "internal.rep@example.com"
COLLEAGUE = "internal.colleague@example.com"
MANAGER = "internal.manager@example.com"
REP_NUMBER = "+91 70000 10001"
COLLEAGUE_MOBILE = "+91 70000 10002"
COLLEAGUE_PHONE = "070000 10003"
LEAD_NUMBER = "+91 70000 10009"
CONTACT_NUMBER = "+91 70000 10008"
UNKNOWN_NUMBER = "+91 70000 10007"
DEVICE = "internalcalls1"


def make_user(email, roles, **fields):
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
				"roles": [{"role": r} for r in roles],
				**fields,
			}
		).insert(ignore_permissions=True)


def phone_call(device_call_id, number, type="outgoing", duration=20):
	return {
		"device_call_id": device_call_id,
		"number": number,
		"type": type,
		"start": int(time.time() * 1000) - 5000,
		"duration": duration,
	}


class TestInternalCalls(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		make_user(REP, ["Sales User"], mobile_no=REP_NUMBER)
		make_user(COLLEAGUE, ["Sales User"], mobile_no=COLLEAGUE_MOBILE, phone=COLLEAGUE_PHONE)
		make_user(MANAGER, ["Sales Manager"])
		frappe.db.set_single_value("ABM CRM Settings", "call_sync_scope", "CRM numbers only")
		self.token = frappe.generate_hash(length=6)
		self.lead = frappe.get_doc(
			{"doctype": "CRM Lead", "first_name": f"Internal {self.token}", "mobile_no": LEAD_NUMBER, "lead_owner": REP}
		).insert(ignore_permissions=True)
		self.contact = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": f"Plain {self.token}",
				"phone_nos": [{"phone": CONTACT_NUMBER, "is_primary_mobile_no": 1}],
			}
		).insert(ignore_permissions=True)
		self.logs = []

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.set_single_value("ABM CRM Settings", "call_sync_scope", "CRM numbers only")
		for name in set(self.logs) | set(frappe.get_all("CRM Call Log", filters={"id": ["like", f"abm-{DEVICE}-%"]}, pluck="name")):
			if frappe.db.exists("CRM Call Log", name):
				frappe.delete_doc("CRM Call Log", name, force=True, ignore_permissions=True)
		frappe.delete_doc("CRM Lead", self.lead.name, force=True, ignore_permissions=True)
		frappe.delete_doc("Contact", self.contact.name, force=True, ignore_permissions=True)

	def sync(self, *calls):
		frappe.set_user(REP)
		result = mobile.sync_calls(list(calls), DEVICE)
		frappe.set_user("Administrator")
		return result

	def test_calls_to_colleagues_are_skipped_in_any_scope(self):
		for scope in ("CRM numbers only", "All calls"):
			frappe.db.set_single_value("ABM CRM Settings", "call_sync_scope", scope)
			result = self.sync(
				phone_call(f"{scope[:3]}1", COLLEAGUE_MOBILE),
				phone_call(f"{scope[:3]}2", "+917000010003", type="incoming"),  # their phone, another format
				phone_call(f"{scope[:3]}3", "70000 10002", type="missed", duration=0),
			)
			self.assertEqual([r["skip_reason"] for r in result], ["internal"] * 3)
			self.assertEqual([r["call_log"] for r in result], [None] * 3)
		self.assertFalse(frappe.db.exists("CRM Call Log", {"id": ["like", f"abm-{DEVICE}-%"]}))

	def test_lead_calls_are_logged_and_keep_every_key(self):
		result = self.sync(phone_call("1", LEAD_NUMBER))[0]
		self.logs.append(result["call_log"])
		self.assertEqual(result["call_log"], f"abm-{DEVICE}-1")
		self.assertIsNone(result["skip_reason"])
		self.assertEqual(
			(result["reference_doctype"], result["reference_docname"], result["reference_title"], result["upload_recording"]),
			("CRM Lead", self.lead.name, self.lead.lead_name, True),
		)
		self.assertEqual(result["device_call_id"], "1")

	def test_plain_contacts_and_unknown_numbers_follow_the_scope(self):
		result = self.sync(phone_call("1", CONTACT_NUMBER), phone_call("2", UNKNOWN_NUMBER))
		self.assertEqual([(r["call_log"], r["skip_reason"]) for r in result], [(None, "no_match")] * 2)

		frappe.db.set_single_value("ABM CRM Settings", "call_sync_scope", "All calls")
		result = self.sync(phone_call("1", CONTACT_NUMBER), phone_call("2", UNKNOWN_NUMBER))
		self.assertEqual([r["skip_reason"] for r in result], [None, None])
		self.assertEqual([r["call_log"] for r in result], [f"abm-{DEVICE}-1", f"abm-{DEVICE}-2"])
		self.assertIsNone(result[0]["reference_doctype"])

	def test_hidden_numbers_are_no_match(self):
		self.assertEqual(self.sync(phone_call("1", ""))[0]["skip_reason"], "no_match")

	def test_cleanup_dry_run_and_delete(self):
		def log(name, type, party, doctype=None, docname=None):
			doc = frappe.get_doc(
				{
					"doctype": "CRM Call Log",
					"id": name,
					"telephony_medium": "Manual",
					"type": type,
					"status": "Completed",
					"from": party if type == "Incoming" else REP_NUMBER,
					"to": REP_NUMBER if type == "Incoming" else party,
					"duration": 5,
					"reference_doctype": doctype,
					"reference_docname": docname,
				}
			).insert(ignore_permissions=True)
			self.logs.append(doc.name)
			return doc.name

		out = log(f"abm-{DEVICE}-c1", "Outgoing", COLLEAGUE_MOBILE)
		inc = log(f"abm-{DEVICE}-c2", "Incoming", "+917000010003")
		on_lead = log(f"abm-{DEVICE}-c3", "Outgoing", COLLEAGUE_MOBILE, "CRM Lead", self.lead.name)
		unknown = log(f"abm-{DEVICE}-c4", "Outgoing", UNKNOWN_NUMBER)
		# the rep's own number is on every outgoing call; only the other party counts
		rep_own = log(f"abm-{DEVICE}-c5", "Outgoing", CONTACT_NUMBER)

		frappe.set_user(REP)
		self.assertRaises(frappe.PermissionError, mobile.cleanup_internal_call_logs)

		frappe.set_user(MANAGER)
		dry = mobile.cleanup_internal_call_logs()
		self.assertEqual(dry["count"], len(dry["names"]))
		self.assertTrue({out, inc} <= set(dry["names"]))
		self.assertFalse({on_lead, unknown, rep_own} & set(dry["names"]))
		self.assertTrue(frappe.db.exists("CRM Call Log", out))
		self.assertEqual(mobile.cleanup_internal_call_logs(dry_run=1)["count"], dry["count"])

		done = mobile.cleanup_internal_call_logs(dry_run=0)
		self.assertEqual(done, {"deleted": dry["count"]})
		self.assertFalse(frappe.db.exists("CRM Call Log", out))
		self.assertFalse(frappe.db.exists("CRM Call Log", inc))
		for keep in (on_lead, unknown, rep_own):
			self.assertTrue(frappe.db.exists("CRM Call Log", keep))
		self.assertEqual(mobile.cleanup_internal_call_logs(), {"count": 0, "names": []})
