import io
import random
import time
from unittest.mock import patch

import frappe
from frappe.desk.form.assign_to import add as assign
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, now_datetime
from frappe.utils.password import update_password
from PIL import Image

from abm_crm.api import mobile

REP = "mobile.rep@example.com"
REP2 = "mobile.rep2@example.com"
MANAGER = "mobile.manager@example.com"
OUTSIDER = "mobile.outsider@example.com"
PASSWORD = "Mobile#Test2026"
REP_NUMBER = "+91 70000 00010"
LEAD_NUMBER = "+91 70000 00011"
UNKNOWN_NUMBER = "+91 70000 00099"


def make_user(email, roles, mobile_no=None):
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
				"mobile_no": mobile_no,
				"roles": [{"role": r} for r in roles],
			}
		).insert(ignore_permissions=True)
	update_password(email, PASSWORD)


def make_lead(**fields):
	return frappe.get_doc({"doctype": "CRM Lead", "first_name": "Mobile Test", **fields}).insert(
		ignore_permissions=True
	)


def png_bytes():
	buffer = io.BytesIO()
	Image.new("RGB", (4, 4), tuple(random.randrange(256) for _ in range(3))).save(buffer, "PNG")
	return buffer.getvalue()


def phone_call(device_call_id, number=LEAD_NUMBER, type="outgoing", duration=30):
	return {
		"device_call_id": device_call_id,
		"number": number,
		"type": type,
		"start": int(time.time() * 1000),
		"duration": duration,
	}


class TestMobileAPI(IntegrationTestCase):
	def setUp(self):
		make_user(REP, ["Sales User"], mobile_no=REP_NUMBER)
		make_user(REP2, ["Sales User"])
		make_user(MANAGER, ["Sales Manager"])
		make_user(OUTSIDER, [])
		frappe.db.set_single_value("ABM CRM Settings", "call_sync_scope", "CRM numbers only")
		frappe.db.set_single_value("ABM CRM Settings", "upload_recordings", 1)
		# login attempts are tracked per IP; tests have no request
		frappe.local.request_ip = "127.0.0.1"
		# data is rolled back only after the whole class, so each test searches its own organization
		self.org = f"Mobile Test {frappe.generate_hash(length=8)}"
		self.lead = make_lead(lead_owner=REP, mobile_no=LEAD_NUMBER, organization=self.org)
		self.files = []

	def tearDown(self):
		frappe.set_user("Administrator")
		for name in self.files:
			if frappe.db.exists("File", name):
				frappe.delete_doc("File", name, ignore_permissions=True)

	def track_file(self, file_url):
		self.files += frappe.get_all("File", filters={"file_url": file_url}, pluck="name")

	# login

	def test_login_reuses_keys(self):
		first = mobile.login(REP, PASSWORD)
		self.assertTrue(first["api_key"] and first["api_secret"])
		self.assertEqual(first["roles"], ["Sales User"])
		self.assertFalse(first["is_manager"])

		second = mobile.login(REP, PASSWORD)
		self.assertEqual(second["api_key"], first["api_key"])
		self.assertEqual(second["api_secret"], first["api_secret"])
		self.assertTrue(mobile.login(MANAGER, PASSWORD)["is_manager"])

	def test_login_rejects_user_without_crm_role(self):
		self.assertRaises(frappe.PermissionError, mobile.login, OUTSIDER, PASSWORD)

	def test_logout_rotates_secret(self):
		keys = mobile.login(REP, PASSWORD)
		frappe.set_user(REP)
		mobile.logout()
		frappe.set_user("Administrator")
		self.assertNotEqual(mobile.login(REP, PASSWORD)["api_secret"], keys["api_secret"])

	# calls

	def test_sync_calls_matches_and_maps(self):
		frappe.set_user(REP)
		result = mobile.sync_calls(
			[
				phone_call("1"),
				phone_call("2", type="missed", duration=0),
				phone_call("3", type="rejected", duration=0),
				phone_call("4", type="outgoing", duration=0),
				phone_call("5", type="incoming", duration=12),
			],
			"dev-a",
		)
		self.assertEqual([r["call_log"] for r in result], [f"abm-dev-a-{i}" for i in range(1, 6)])
		self.assertTrue(all(r["reference_docname"] == self.lead.name for r in result))
		self.assertEqual(result[0]["reference_title"], self.lead.lead_name)
		self.assertEqual([r["upload_recording"] for r in result], [True, False, False, False, True])

		logs = {
			r["call_log"]: frappe.get_doc("CRM Call Log", r["call_log"]) for r in result if r["call_log"]
		}
		outgoing = logs["abm-dev-a-1"]
		self.assertEqual((outgoing.type, outgoing.status), ("Outgoing", "Completed"))
		self.assertEqual((outgoing.caller, outgoing.get("from"), outgoing.to), (REP, REP_NUMBER, LEAD_NUMBER))
		self.assertEqual(outgoing.telephony_medium, "Manual")
		self.assertEqual(outgoing.reference_doctype, "CRM Lead")
		# referenced, not also linked: crm lists calls from both, so a link would show the call twice
		self.assertEqual(outgoing.reference_docname, self.lead.name)
		self.assertFalse(outgoing.has_link("CRM Lead", self.lead.name))

		self.assertEqual((logs["abm-dev-a-2"].type, logs["abm-dev-a-2"].status), ("Incoming", "No Answer"))
		self.assertEqual(logs["abm-dev-a-2"].receiver, REP)
		self.assertEqual(logs["abm-dev-a-2"].get("from"), LEAD_NUMBER)
		self.assertEqual(logs["abm-dev-a-3"].status, "Busy")
		self.assertEqual(logs["abm-dev-a-4"].status, "No Answer")
		self.assertEqual((logs["abm-dev-a-5"].type, logs["abm-dev-a-5"].status), ("Incoming", "Completed"))

	def test_sync_calls_needs_own_number(self):
		frappe.set_user(REP2)
		self.assertRaises(frappe.ValidationError, mobile.sync_calls, [phone_call("1")], "dev-g")

	def test_sync_calls_is_idempotent(self):
		frappe.set_user(REP)
		calls = [phone_call("10"), phone_call("11", duration=5)]
		first = mobile.sync_calls(calls, "dev-b")
		before = frappe.db.count("CRM Call Log", {"name": ["like", "abm-dev-b-%"]})
		second = mobile.sync_calls(calls, "dev-b")
		self.assertEqual(first, second)
		self.assertEqual(frappe.db.count("CRM Call Log", {"name": ["like", "abm-dev-b-%"]}), before)
		self.assertEqual(before, 2)

	def test_sync_calls_scope(self):
		frappe.set_user(REP)
		result = mobile.sync_calls([phone_call("20", number=UNKNOWN_NUMBER)], "dev-c")
		self.assertIsNone(result[0]["call_log"])
		self.assertFalse(frappe.db.exists("CRM Call Log", "abm-dev-c-20"))

		frappe.db.set_single_value("ABM CRM Settings", "call_sync_scope", "All calls")
		result = mobile.sync_calls([phone_call("20", number=UNKNOWN_NUMBER)], "dev-c")
		self.assertEqual(result[0]["call_log"], "abm-dev-c-20")
		self.assertIsNone(result[0]["reference_doctype"])

	def test_upload_recording_permission(self):
		frappe.set_user(REP)
		log = mobile.sync_calls([phone_call("30")], "dev-d")[0]["call_log"]

		upload = ("abm-test-recording.m4a", frappe.generate_hash().encode())
		with patch.object(mobile, "uploaded_file", return_value=upload):
			frappe.set_user(REP2)
			self.assertRaises(frappe.PermissionError, mobile.upload_recording, log)

			frappe.set_user(REP)
			url = mobile.upload_recording(log)["recording_url"]
			self.track_file(url)

		self.assertTrue(url.startswith("/private/files/"))
		self.assertEqual(frappe.db.get_value("CRM Call Log", log, "recording_url"), url)
		file = frappe.get_doc("File", {"file_url": url})
		self.assertEqual((file.attached_to_doctype, file.attached_to_name), ("CRM Call Log", log))
		# nothing left to upload on the next sync
		self.assertFalse(mobile.sync_calls([phone_call("30")], "dev-d")[0]["upload_recording"])

		with patch.object(mobile, "uploaded_file", return_value=("page.html", b"<b>x</b>")):
			self.assertRaises(frappe.ValidationError, mobile.upload_recording, log)

	def test_set_call_outcome_creates_note_and_task(self):
		frappe.set_user(REP)
		log = mobile.sync_calls([phone_call("40")], "dev-e")[0]["call_log"]
		follow_up = add_days(now_datetime(), 2).replace(microsecond=0)

		call = mobile.set_call_outcome(log, "Call Back", note="Busy now\nCall after 5", next_follow_up=str(follow_up))
		self.assertEqual(call["abm_outcome"], "Call Back")
		self.assertTrue(call["note"])

		note = frappe.get_doc("FCRM Note", call["note"])
		self.assertEqual((note.reference_doctype, note.reference_docname), ("CRM Lead", self.lead.name))
		self.assertIn("Call after 5", note.content)

		task = frappe.get_doc("CRM Task", {"reference_docname": self.lead.name, "title": "Follow up"})
		self.assertEqual(task.assigned_to, REP)
		self.assertEqual(str(task.due_date), str(follow_up))

		self.assertRaises(frappe.ValidationError, mobile.set_call_outcome, log, "Maybe")
		frappe.set_user(REP2)
		self.assertRaises(frappe.PermissionError, mobile.set_call_outcome, log, "Interested")

	# leads

	def test_list_leads_respects_permissions(self):
		assigned = make_lead(lead_owner=REP2, organization=self.org)
		assign({"assign_to": [REP], "doctype": "CRM Lead", "name": assigned.name})
		# assigning makes the CRM set the lead owner; keep REP2 as owner so only the ToDo grants access
		frappe.db.set_value("CRM Lead", assigned.name, "lead_owner", REP2)
		other = make_lead(lead_owner=REP2, organization=self.org)

		frappe.set_user(REP)
		names = {r["name"] for r in mobile.list_leads(search=self.org, page_length=100)["data"]}
		self.assertIn(self.lead.name, names)
		self.assertIn(assigned.name, names)
		self.assertNotIn(other.name, names)

		mine = mobile.list_leads(search=self.org, owner="me")["data"]
		self.assertEqual([r["name"] for r in mine], [self.lead.name])

		record = mobile.get_record("CRM Lead", self.lead.name)
		self.assertEqual(record["doc"]["mobile_no"], LEAD_NUMBER)
		self.assertRaises(frappe.PermissionError, mobile.get_record, "CRM Lead", other.name)

	def test_list_leads_paging_and_order(self):
		frappe.set_user(REP)
		for _ in range(2):
			make_lead(lead_owner=REP, organization=self.org)
		page = mobile.list_leads(search=self.org, page_length=2, order_by="creation desc; drop")
		self.assertEqual(len(page["data"]), 2)
		self.assertTrue(page["has_more"])

	# visits and dashboard

	def test_check_in(self):
		frappe.set_user(REP)
		upload = ("abm-test-visit.png", png_bytes())
		with patch.object(mobile, "uploaded_file", return_value=upload):
			visit = mobile.check_in("CRM Lead", self.lead.name, "28.6139391", "77.2090212", 12.5, notes="Met")
		self.track_file(visit["photo"])

		self.assertEqual(visit["visited_by"], REP)
		self.assertAlmostEqual(visit["latitude"], 28.6139391, places=6)
		self.assertTrue(visit["photo"].startswith("/private/files/"))
		visits = mobile.get_record("CRM Lead", self.lead.name)["visits"]
		self.assertEqual(visits[0]["name"], visit["name"])

		self.assertRaises(frappe.ValidationError, mobile.check_in, "CRM Lead", self.lead.name, 200, 10)
		other = make_lead(lead_owner=REP2)
		self.assertRaises(frappe.PermissionError, mobile.check_in, "CRM Lead", other.name, 1, 1)

	def test_manager_dashboard(self):
		# other tests in this class add data too (rolled back at the end), so compare before / after
		frappe.set_user(MANAGER)
		before_data = mobile.manager_dashboard()
		before = before_data["totals"]
		rep_before = next(r for r in before_data["reps"] if r["user"] == REP)

		frappe.set_user(REP)
		mobile.sync_calls(
			[phone_call("50", duration=40), phone_call("51", type="missed", duration=0)], "dev-f"
		)
		mobile.check_in("CRM Lead", self.lead.name, 10, 10)
		self.assertRaises(frappe.PermissionError, mobile.manager_dashboard)

		frappe.set_user(MANAGER)
		data = mobile.manager_dashboard()
		totals = data["totals"]
		self.assertEqual(totals["calls"] - before["calls"], 2)
		self.assertEqual(totals["connected"] - before["connected"], 1)
		self.assertEqual(totals["talk_time"] - before["talk_time"], 40)
		self.assertEqual(totals["visits"] - before["visits"], 1)

		rep = next(r for r in data["reps"] if r["user"] == REP)
		changed = {k: rep[k] - rep_before[k] for k in ("calls", "outgoing", "missed", "leads_touched", "visits")}
		self.assertEqual(changed, {"calls": 2, "outgoing": 1, "missed": 1, "leads_touched": 1, "visits": 1})
		self.assertGreaterEqual(rep["leads_assigned"], 1)
		self.assertTrue(rep["last_call"])
		self.assertIn("New", [s["status"] for s in data["lead_funnel"]])

	def test_home_and_tasks(self):
		frappe.set_user(REP)
		task = mobile.create_task("CRM Lead", self.lead.name, "Call back", due_date=str(now_datetime()))
		self.assertEqual(task["assigned_to"], REP)
		home = mobile.get_home()
		self.assertIn(task["name"], [t["name"] for t in home["tasks_today"]])
		self.assertIn(self.lead.name, [lead["name"] for lead in home["new_leads"]])

		mobile.update_task(task["name"], status="Done")
		self.assertIn(task["name"], [t["name"] for t in mobile.list_tasks("done")["data"]])
		self.assertNotIn(task["name"], [t["name"] for t in mobile.list_tasks("today")["data"]])


class TestSetMyMobile(IntegrationTestCase):
	def test_saves_international_number(self):
		from abm_crm.api.mobile import set_my_mobile

		frappe.db.set_single_value("ABM CRM Settings", "default_phone_region", "IN")
		self.assertEqual(set_my_mobile("98765 43210")["mobile_no"], "+919876543210")
		self.assertEqual(frappe.db.get_value("User", frappe.session.user, "mobile_no"), "+919876543210")
		self.assertRaises(frappe.ValidationError, set_my_mobile, "123")
