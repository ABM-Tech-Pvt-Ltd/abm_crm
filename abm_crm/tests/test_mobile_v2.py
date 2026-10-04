"""Tests for the "Full CRM in the app (v2)" part of the mobile API (docs/mobile-api.md)."""

import io
import random
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, now_datetime, nowdate
from frappe.utils.password import update_password
from PIL import Image

from abm_crm.api import mobile

REP = "v2.rep@example.com"
REP2 = "v2.rep2@example.com"
MANAGER = "v2.manager@example.com"
PASSWORD = "Mobile#V2Test2026"


def make_user(email, roles):
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
				"roles": [{"role": r} for r in roles],
			}
		).insert(ignore_permissions=True)
	update_password(email, PASSWORD)


def png_bytes():
	buffer = io.BytesIO()
	Image.new("RGB", (4, 4), tuple(random.randrange(256) for _ in range(3))).save(buffer, "PNG")
	return buffer.getvalue()


# crm fetches exchange rates over the network for deals not in the base currency
no_exchange_rate_fetch = patch("crm.fcrm.doctype.crm_deal.crm_deal.get_exchange_rate", return_value=0.5)
# CRM Notifications push to the app; nothing must leave the test
no_push = patch("abm_crm.push.send_push", return_value=False)


class TestMobileV2(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		no_exchange_rate_fetch.start()
		no_push.start()

	@classmethod
	def tearDownClass(cls):
		no_exchange_rate_fetch.stop()
		no_push.stop()
		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")
		make_user(REP, ["Sales User"])
		make_user(REP2, ["Sales User"])
		make_user(MANAGER, ["Sales Manager"])
		self.token = frappe.generate_hash(length=8)
		self.created = []  # (doctype, name), deleted in reverse order in tearDown
		self.lead = self.make_lead(REP, email=f"{self.token}@lead.example.com")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.flags.mute_emails = False
		for doctype, name in reversed(self.created):
			if frappe.db.exists(doctype, name):
				frappe.delete_doc(doctype, name, force=True, ignore_permissions=True, delete_permanently=True)

	def track(self, doctype, name):
		self.created.append((doctype, name))
		return name

	def make_lead(self, owner, **fields):
		lead = frappe.get_doc(
			{
				"doctype": "CRM Lead",
				"first_name": "V2 Test",
				"organization": f"V2 Org {self.token}",
				"lead_owner": owner,
				**fields,
			}
		).insert(ignore_permissions=True)
		self.track("CRM Lead", lead.name)
		return lead

	def make_deal(self, owner, status="Qualification", value=1000, **fields):
		deal = frappe.get_doc(
			{
				"doctype": "CRM Deal",
				"deal_owner": owner,
				"status": status,
				"deal_value": value,
				"currency": "INR",
				**fields,
			}
		).insert(ignore_permissions=True)
		self.track("CRM Deal", deal.name)
		return deal

	def track_files(self, **filters):
		for name in frappe.get_all("File", filters=filters, pluck="name"):
			self.track("File", name)

	# dashboard and search

	def test_dashboard_numbers(self):
		frappe.set_user(REP)
		before = mobile.get_dashboard()

		frappe.set_user("Administrator")
		self.make_deal(REP, "Qualification", 1000)
		self.make_deal(REP, "Won", 500, closed_date=nowdate())
		self.make_deal(REP2, "Qualification", 7000)  # not visible to REP
		frappe.set_user(REP)
		task = mobile.create_task("CRM Lead", self.lead.name, "Dashboard task", due_date=str(now_datetime()))
		self.track("CRM Task", task["name"])
		event = mobile.create_event("Site visit", str(now_datetime().replace(microsecond=0)))
		self.track("Event", event["name"])

		after = mobile.get_dashboard()
		stats, old = after["stats"], before["stats"]
		self.assertEqual(stats["currency"], "INR")
		self.assertEqual(stats["open_deals"] - old["open_deals"], 1)
		self.assertEqual(stats["pipeline_value"] - old["pipeline_value"], 1000)
		self.assertEqual(stats["won_this_month"] - old["won_this_month"], 1)
		self.assertEqual(stats["won_value_this_month"] - old["won_value_this_month"], 500)
		self.assertEqual(stats["tasks_today"] - old["tasks_today"], 1)
		self.assertEqual(stats["open_leads"] - old["open_leads"], 0)

		qualification = next(p for p in after["pipeline"] if p["status"] == "Qualification")
		qualification_before = next(p for p in before["pipeline"] if p["status"] == "Qualification")
		self.assertEqual(qualification["count"] - qualification_before["count"], 1)
		self.assertNotIn("Won", [p["status"] for p in after["pipeline"]])

		agenda = {(i["kind"], i["name"]) for i in after["agenda"]}
		self.assertIn(("task", task["name"]), agenda)
		self.assertIn(("event", event["name"]), agenda)
		self.assertTrue(set(after) >= {"greeting_name", "stats", "agenda", "pipeline", "recent"})

	def test_search_respects_permissions(self):
		other = self.make_lead(REP2)
		org = frappe.get_doc(
			{"doctype": "CRM Organization", "organization_name": f"V2 Org {self.token}"}
		).insert(ignore_permissions=True)
		self.track("CRM Organization", org.name)

		frappe.set_user(REP)
		results = mobile.search(self.token, limit=50)
		found = {(r["doctype"], r["name"]) for r in results}
		self.assertIn(("CRM Lead", self.lead.name), found)
		self.assertNotIn(("CRM Lead", other.name), found)
		self.assertIn(("CRM Organization", org.name), found)
		lead = next(r for r in results if r["name"] == self.lead.name)
		self.assertEqual(lead["title"], self.lead.lead_name)
		self.assertIn(self.token, lead["subtitle"])

		frappe.set_user(REP2)
		found = {r["name"] for r in mobile.search(self.token, limit=50)}
		self.assertIn(other.name, found)
		self.assertNotIn(self.lead.name, found)
		self.assertEqual(mobile.search("  "), [])

	# notifications

	def test_notifications_mark_read(self):
		names = []
		for user, text in ((REP, "first"), (REP, "second"), (REP2, "other")):
			doc = frappe.get_doc(
				{
					"doctype": "CRM Notification",
					"type": "Mention",
					"from_user": MANAGER,
					"to_user": user,
					"notification_text": f"<p>{text} {self.token}</p>",
					"reference_doctype": "CRM Lead",
					"reference_name": self.lead.name,
				}
			).insert(ignore_permissions=True)
			names.append(self.track("CRM Notification", doc.name))

		frappe.set_user(REP)
		data = mobile.list_notifications()
		mine = [n for n in data["data"] if self.token in (n["body"] or "")]
		self.assertEqual({n["name"] for n in mine}, set(names[:2]))
		self.assertEqual(mine[0]["title"], "You were mentioned")
		self.assertEqual(mine[0]["doctype"], "CRM Lead")
		self.assertEqual(mine[0]["docname"], self.lead.name)
		self.assertEqual(mine[0]["read"], 0)
		unread = data["unread"]
		self.assertGreaterEqual(unread, 2)

		self.assertEqual(mobile.mark_notifications_read([names[0]])["unread"], unread - 1)
		# another user's notification is never touched
		mobile.mark_notifications_read([names[2]])
		self.assertEqual(frappe.db.get_value("CRM Notification", names[2], "read"), 0)
		self.assertEqual(mobile.mark_notifications_read()["unread"], 0)
		self.assertEqual(frappe.db.get_value("CRM Notification", names[1], "read"), 1)
		self.assertEqual(frappe.db.get_value("CRM Notification", names[2], "read"), 0)

	# email

	def test_emails_list_send_and_template(self):
		frappe.flags.mute_emails = True
		template = frappe.get_doc(
			{
				"doctype": "Email Template",
				"name": f"V2 Template {self.token}",
				"subject": "Hello {{ first_name }}",
				"response": "<p>About {{ doc.organization }}</p>",
				"reference_doctype": "CRM Lead",
				"enabled": 1,
			}
		).insert(ignore_permissions=True)
		self.track("Email Template", template.name)

		frappe.set_user(REP)
		setup = mobile.get_email_setup("CRM Lead", self.lead.name)
		self.assertEqual(setup["to"], [self.lead.email])
		self.assertIn(template.name, [t["name"] for t in setup["templates"]])
		rendered = mobile.render_email_template(template.name, "CRM Lead", self.lead.name)
		self.assertEqual(rendered["subject"], "Hello V2 Test")
		self.assertIn(self.lead.organization, rendered["content"])

		with patch.object(mobile, "uploaded_file", return_value=("v2-quote.txt", b"quote")):
			file = mobile.upload_attachment("CRM Lead", self.lead.name)
		self.track("File", file["name"])

		name = mobile.send_email(
			"CRM Lead",
			self.lead.name,
			[self.lead.email],
			rendered["subject"],
			rendered["content"],
			cc="cc.v2@example.com",
			attachments=[file["name"]],
		)
		self.track("Communication", name)
		self.track_files(attached_to_doctype="Communication", attached_to_name=name)
		comm = frappe.get_doc("Communication", name)
		self.assertEqual((comm.reference_doctype, comm.reference_name), ("CRM Lead", self.lead.name))
		self.assertEqual(comm.sent_or_received, "Sent")

		emails = mobile.get_emails("CRM Lead", self.lead.name)
		self.assertEqual(emails[0]["name"], name)
		self.assertEqual(emails[0]["subject"], "Hello V2 Test")
		self.assertIn("cc.v2@example.com", emails[0]["cc"])
		self.assertIn(self.lead.email, emails[0]["recipients"])
		self.assertEqual([a["file_name"] for a in emails[0]["attachments"]], ["v2-quote.txt"])

		frappe.set_user(REP2)
		self.assertRaises(frappe.PermissionError, mobile.get_emails, "CRM Lead", self.lead.name)
		self.assertRaises(
			frappe.PermissionError, mobile.send_email, "CRM Lead", self.lead.name, "x@example.com", "s", "c"
		)

	# attachments

	def test_attachments_upload_delete_permissions(self):
		frappe.set_user(REP)
		with patch.object(mobile, "uploaded_file", return_value=("v2-photo.png", png_bytes())):
			first = mobile.upload_attachment("CRM Lead", self.lead.name)
			second = mobile.upload_attachment("CRM Lead", self.lead.name)
			self.track("File", first["name"])
			self.track("File", second["name"])
			self.assertEqual(first["is_private"], 1)
			self.assertTrue(first["file_url"].startswith("/private/files/"))

			frappe.set_user(REP2)
			self.assertRaises(frappe.PermissionError, mobile.upload_attachment, "CRM Lead", self.lead.name)
			self.assertRaises(frappe.PermissionError, mobile.list_attachments, "CRM Lead", self.lead.name)
			self.assertRaises(frappe.PermissionError, mobile.delete_attachment, first["name"])

		frappe.set_user(REP)
		names = [f["name"] for f in mobile.list_attachments("CRM Lead", self.lead.name)]
		self.assertEqual(set(names), {first["name"], second["name"]})
		mobile.delete_attachment(first["name"])
		self.assertFalse(frappe.db.exists("File", first["name"]))

		frappe.set_user(MANAGER)
		mobile.delete_attachment(second["name"])
		self.assertFalse(frappe.db.exists("File", second["name"]))

	# editing records

	def test_get_form_follows_layout(self):
		from crm.fcrm.doctype.crm_fields_layout.crm_fields_layout import get_fields_layout

		frappe.set_user(REP)
		for doctype in ("CRM Lead", "CRM Deal"):
			layout_type = (
				"Data Fields"
				if frappe.db.exists("CRM Fields Layout", {"dt": doctype, "type": "Data Fields"})
				else "Side Panel"
			)
			in_layout = {
				f["fieldname"]
				for tab in get_fields_layout(doctype, layout_type)
				for s in tab.get("sections") or []
				for c in s.get("columns") or []
				for f in c.get("fields") or []
				if isinstance(f, dict)
			}
			form = mobile.get_form(doctype)
			fields = [f for s in form for f in s["fields"]]
			self.assertTrue(fields)
			self.assertTrue({f["fieldname"] for f in fields} <= in_layout)
			for f in fields:
				self.assertTrue(set(f) >= {"fieldname", "label", "fieldtype", "options", "reqd", "read_only"})
				if f["fieldtype"] == "Select":
					self.assertIsInstance(f["options"], list)
				if f["fieldtype"] == "Link":
					self.assertTrue(f["options"])
		self.assertRaises(frappe.ValidationError, mobile.get_form, "Contact")

	def test_update_record_only_editable_layout_fields(self):
		layout = [
			{
				"section": "Details",
				"fields": [
					{"fieldname": "website", "label": "Website", "fieldtype": "Data", "options": None,
					 "reqd": 0, "read_only": 0},
					{"fieldname": "job_title", "label": "Job Title", "fieldtype": "Data", "options": None,
					 "reqd": 0, "read_only": 1},
				],
			}
		]
		frappe.set_user(REP)
		with patch.object(mobile, "form_sections", return_value=layout):
			doc = mobile.update_record("CRM Lead", self.lead.name, {"website": "https://v2.example.com"})
			self.assertEqual(doc["website"], "https://v2.example.com")
			self.assertEqual(frappe.db.get_value("CRM Lead", self.lead.name, "website"), "https://v2.example.com")

			# read only in the layout
			self.assertRaises(
				frappe.ValidationError, mobile.update_record, "CRM Lead", self.lead.name, {"job_title": "CEO"}
			)
			# not in the layout at all
			self.assertRaises(
				frappe.ValidationError, mobile.update_record, "CRM Lead", self.lead.name, {"converted": 1}
			)
			self.assertEqual(frappe.db.get_value("CRM Lead", self.lead.name, "converted"), 0)

			frappe.set_user(REP2)
			self.assertRaises(
				frappe.PermissionError, mobile.update_record, "CRM Lead", self.lead.name, {"website": "x"}
			)

	def test_link_options(self):
		frappe.set_user(REP)
		users = mobile.link_options("User", REP.split("@")[0])
		self.assertIn(REP, [u["value"] for u in users])
		statuses = mobile.link_options("CRM Lead Status", "")
		self.assertIn("New", [s["value"] for s in statuses])
		self.assertLessEqual(len(statuses), 20)

	def test_assign_and_unassign(self):
		frappe.set_user(REP)
		assignees = mobile.assign("CRM Lead", self.lead.name, [REP2])
		self.assertIn(REP2, [a["name"] for a in assignees])
		record = mobile.get_record("CRM Lead", self.lead.name)
		self.assertIn(REP2, [a["name"] for a in record["assignees"]])
		self.assertTrue(set(record["assignees"][0]) >= {"name", "full_name", "user_image"})

		assignees = mobile.unassign("CRM Lead", self.lead.name, REP2)
		self.assertNotIn(REP2, [a["name"] for a in assignees])
		self.assertFalse(
			frappe.db.exists(
				"ToDo",
				{"reference_type": "CRM Lead", "reference_name": self.lead.name, "allocated_to": REP2, "status": "Open"},
			)
		)
		for todo in frappe.get_all("ToDo", filters={"reference_name": self.lead.name}, pluck="name"):
			self.track("ToDo", todo)

		other = self.make_lead(REP2)
		self.assertRaises(frappe.PermissionError, mobile.assign, "CRM Lead", other.name, [REP])

	def test_convert_to_deal_and_create_deal(self):
		lead = self.make_lead(REP, email=f"convert.{self.token}@example.com", mobile_no="+91 70000 11111")
		frappe.set_user(REP2)
		self.assertRaises(frappe.PermissionError, mobile.convert_to_deal, lead.name)

		frappe.set_user(REP)
		deal = mobile.convert_to_deal(lead.name)["deal"]
		self.track("CRM Deal", deal)
		self.track_created_contact_and_org(deal)
		self.assertEqual(frappe.db.get_value("CRM Deal", deal, "lead"), lead.name)
		self.assertEqual(frappe.db.get_value("CRM Lead", lead.name, "converted"), 1)
		# a retry returns the same deal
		self.assertEqual(mobile.convert_to_deal(lead.name)["deal"], deal)

		row = mobile.create_deal(
			{
				"organization": f"V2 New Org {self.token}",
				"lead_name": "Deal Person",
				"email": f"deal.{self.token}@example.com",
				"deal_value": 2500,
				"status": "Qualification",
			}
		)
		self.track("CRM Deal", row["name"])
		self.track_created_contact_and_org(row["name"])
		self.assertEqual(row["deal_owner"], REP)
		self.assertEqual(row["organization"], f"V2 New Org {self.token}")
		self.assertEqual(row["deal_value"], 2500)
		self.assertEqual(row["email"], f"deal.{self.token}@example.com")

	def track_created_contact_and_org(self, deal):
		doc = frappe.get_doc("CRM Deal", deal)
		for c in doc.contacts:
			self.track("Contact", c.contact)
		if doc.organization:
			self.track("CRM Organization", doc.organization)

	def test_comments_notes_and_tasks(self):
		frappe.set_user(REP)
		comment = mobile.add_comment("CRM Lead", self.lead.name, "Spoke to <b>them</b>\nCall again")
		self.track("Comment", comment["name"])
		self.assertIn("&lt;b&gt;", comment["content"])
		self.assertIn(comment["name"], [c["name"] for c in mobile.get_record("CRM Lead", self.lead.name)["comments"]])

		note = mobile.add_note("CRM Lead", self.lead.name, "First")
		self.track("FCRM Note", note["name"])
		note = mobile.update_note(note["name"], title="Renamed", content="Second")
		self.assertEqual(note["title"], "Renamed")
		self.assertIn("Second", note["content"])
		mobile.delete_note(note["name"])
		self.assertFalse(frappe.db.exists("FCRM Note", note["name"]))

		task = mobile.create_task("CRM Lead", self.lead.name, "Old title")
		self.track("CRM Task", task["name"])
		task = mobile.update_task(task["name"], title="New title", priority="High", description="Bring papers")
		self.assertEqual((task["title"], task["priority"], task["status"]), ("New title", "High", "Todo"))
		self.assertEqual(task["description"], "Bring papers")

		frappe.set_user(REP2)
		self.assertRaises(frappe.PermissionError, mobile.add_comment, "CRM Lead", self.lead.name, "x")
		frappe.set_user(REP)
		mobile.delete_task(task["name"])
		self.assertFalse(frappe.db.exists("CRM Task", task["name"]))

	# contacts and organizations

	def test_contacts_crud(self):
		frappe.set_user(REP)
		email = f"contact.{self.token}@example.com"
		row = mobile.create_contact(
			{"first_name": "Cora", "last_name": self.token, "email_id": email, "mobile_no": "+91 70000 22222"}
		)
		self.track("Contact", row["name"])
		self.assertEqual((row["email_id"], row["mobile_no"]), (email, "+91 70000 22222"))
		self.assertRaises(frappe.ValidationError, mobile.create_contact, {"last_name": "x"})

		listed = mobile.list_contacts(search=self.token)["data"]
		self.assertEqual([c["name"] for c in listed], [row["name"]])

		# a lead with the contact's email is listed with it
		lead = self.make_lead(REP, email=email)
		deal = self.make_deal(REP, contacts=[{"contact": row["name"], "is_primary": 1}])
		detail = mobile.get_contact(row["name"])
		self.assertEqual(detail["doc"]["first_name"], "Cora")
		self.assertIn(lead.name, [r["name"] for r in detail["leads"]])
		self.assertIn(deal.name, [r["name"] for r in detail["deals"]])

		updated = mobile.update_contact(row["name"], {"mobile_no": "+91 70000 33333", "company_name": None})
		self.assertEqual(updated["mobile_no"], "+91 70000 33333")
		self.assertEqual(len(updated["phone_nos"]), 2)

	def test_organizations_crud(self):
		frappe.set_user(REP)
		row = mobile.create_organization(
			{"organization_name": f"V2 Company {self.token}", "website": "https://v2c.example.com"}
		)
		self.track("CRM Organization", row["name"])
		self.assertEqual(row["website"], "https://v2c.example.com")
		self.assertRaises(frappe.ValidationError, mobile.create_organization, {"website": "x"})

		listed = mobile.list_organizations(search=self.token)["data"]
		self.assertEqual([o["name"] for o in listed], [row["name"]])

		deal = self.make_deal(REP, organization=row["name"])
		contact = mobile.create_contact({"first_name": "Org", "last_name": "Person", "company_name": row["name"]})
		self.track("Contact", contact["name"])
		detail = mobile.get_organization(row["name"])
		self.assertIn(deal.name, [d["name"] for d in detail["deals"]])
		self.assertIn(contact["name"], [c["name"] for c in detail["contacts"]])

		updated = mobile.update_organization(row["name"], {"website": "https://new.example.com"})
		self.assertEqual(updated["website"], "https://new.example.com")

	# calendar

	def test_events_crud_and_agenda(self):
		today = nowdate()
		start = f"{today} 10:00:00"
		frappe.set_user(REP)
		event = mobile.create_event(
			"Meet client", start, f"{today} 11:00:00", reference_doctype="CRM Lead", reference_docname=self.lead.name
		)
		self.track("Event", event["name"])
		self.assertEqual(event["kind"], "event")
		self.assertEqual((event["reference_docname"], event["reference_title"]), (self.lead.name, self.lead.lead_name))
		self.assertEqual(frappe.db.get_value("Event", event["name"], "event_type"), "Private")

		task = mobile.create_task("CRM Lead", self.lead.name, "Agenda task", due_date=f"{today} 09:00:00")
		self.track("CRM Task", task["name"])

		# an event someone else created, with REP as a participant
		frappe.set_user("Administrator")
		shared = frappe.get_doc(
			{
				"doctype": "Event",
				"subject": "Team review",
				"event_type": "Private",
				"starts_on": f"{today} 15:00:00",
				"event_participants": [
					{"reference_doctype": "CRM Lead", "reference_docname": self.lead.name, "email": REP}
				],
			}
		).insert(ignore_permissions=True)
		self.track("Event", shared.name)

		frappe.set_user(REP)
		agenda = mobile.list_agenda(today, today)
		keys = [(i["kind"], i["name"]) for i in agenda]
		self.assertIn(("event", event["name"]), keys)
		self.assertIn(("event", shared.name), keys)
		self.assertIn(("task", task["name"]), keys)
		self.assertLess(keys.index(("task", task["name"])), keys.index(("event", event["name"])))
		self.assertLess(keys.index(("event", event["name"])), keys.index(("event", shared.name)))
		self.assertNotIn(("event", event["name"]), [(i["kind"], i["name"]) for i in mobile.list_agenda(
			add_days(today, 2), add_days(today, 3))])

		# participants may see, only the owner may change
		self.assertRaises(frappe.PermissionError, mobile.update_event, shared.name, subject="x")
		frappe.set_user(REP2)
		self.assertNotIn(event["name"], [i["name"] for i in mobile.list_agenda(today, today)])
		self.assertRaises(frappe.PermissionError, mobile.update_event, event["name"], subject="x")
		self.assertRaises(frappe.PermissionError, mobile.delete_event, event["name"])

		frappe.set_user(REP)
		updated = mobile.update_event(event["name"], subject="Meet client again", ends_on="")
		self.assertEqual(updated["title"], "Meet client again")
		self.assertIsNone(updated["end"])
		self.assertEqual(updated["reference_docname"], self.lead.name)
		mobile.delete_event(event["name"])
		self.assertFalse(frappe.db.exists("Event", event["name"]))

	# profile

	def test_profile_update(self):
		frappe.set_user(REP)
		profile = mobile.get_profile()
		self.assertEqual((profile["name"], profile["is_manager"]), (REP, False))
		self.assertEqual(profile["roles"], ["Sales User"])

		frappe.db.set_single_value("ABM CRM Settings", "default_phone_region", "IN")
		with patch.object(mobile, "uploaded_file", return_value=("v2-me.png", png_bytes())):
			profile = mobile.update_profile(first_name="Ravi", last_name="Rep", mobile_no="98765 43210")
		self.track_files(attached_to_doctype="User", attached_to_name=REP)
		self.assertEqual((profile["first_name"], profile["last_name"]), ("Ravi", "Rep"))
		self.assertEqual(profile["full_name"], "Ravi Rep")
		self.assertEqual(profile["mobile_no"], "+919876543210")
		self.assertTrue(profile["user_image"].startswith("/files/"))

		self.assertRaises(frappe.ValidationError, mobile.update_profile, first_name=" ")
		self.assertRaises(frappe.ValidationError, mobile.update_profile, mobile_no="123")
		# only the session user's own record is touched
		self.assertNotEqual(frappe.db.get_value("User", REP2, "first_name"), "Ravi")


class TestBrandAndPassword(IntegrationTestCase):
	def test_brand_is_public_and_inline(self):
		from abm_crm.api.mobile import get_brand

		brand = get_brand()
		self.assertIn("name", brand)
		self.assertTrue(brand["logo"] is None or brand["logo"].startswith(("data:", "http", "/")))

	def test_change_password(self):
		from frappe.utils.password import check_password, update_password

		from abm_crm.api.mobile import change_password

		email = "pw.change@example.com"
		if not frappe.db.exists("User", email):
			frappe.get_doc({"doctype": "User", "email": email, "first_name": "Pw", "send_welcome_email": 0,
				"roles": [{"role": "Sales User"}]}).insert(ignore_permissions=True)
		update_password(email, "OldPass#2026x")
		frappe.set_user(email)
		try:
			self.assertRaises(frappe.AuthenticationError, change_password, "wrong", "NewPass#2026y")
			change_password("OldPass#2026x", "NewPass#2026y-Strong")
			self.assertEqual(check_password(email, "NewPass#2026y-Strong", delete_tracker_cache=False), email)
		finally:
			frappe.set_user("Administrator")
