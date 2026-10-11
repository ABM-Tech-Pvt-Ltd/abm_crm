"""Tests for "Site visits (walk-ins) as a lifecycle" in docs/mobile-api.md."""

import datetime
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, now_datetime, nowdate

from abm_crm.api import mobile, visits

MANAGER = "v3.manager@example.com"
REP = "v3.rep@example.com"
REP2 = "v3.rep2@example.com"
DISABLED = "v3.disabled@example.com"

no_push = patch("abm_crm.push.send_push", return_value=False)


def make_user(email, roles, enabled=1):
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
				"enabled": enabled,
				"roles": [{"role": r} for r in roles],
			}
		).insert(ignore_permissions=True)


class TestVisitsV3(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		no_push.start()

	@classmethod
	def tearDownClass(cls):
		no_push.stop()
		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")
		make_user(MANAGER, ["Sales Manager"])
		make_user(REP, ["Sales User"])
		make_user(REP2, ["Sales User"])
		make_user(DISABLED, ["Sales User"], enabled=0)
		self.token = frappe.generate_hash(length=8)
		self.project = f"Proj {self.token}"
		self.lead = self.make_lead(REP)
		self.other_lead = self.make_lead(REP2)

	def tearDown(self):
		frappe.set_user("Administrator")
		for lead in (self.lead, self.other_lead):
			for name in frappe.get_all("ABM Field Visit", filters={"reference_docname": lead.name}, pluck="name"):
				frappe.delete_doc("ABM Field Visit", name, force=True, ignore_permissions=True)
			frappe.db.delete("Comment", {"reference_name": lead.name})
			frappe.delete_doc("CRM Lead", lead.name, force=True, ignore_permissions=True)
		frappe.db.delete("CRM Notification", {"to_user": ["in", (REP, REP2, MANAGER)], "type": "Automation"})

	def make_lead(self, owner):
		return frappe.get_doc(
			{"doctype": "CRM Lead", "first_name": f"Visit {self.token}", "lead_owner": owner}
		).insert(ignore_permissions=True)

	def create(self, status="Pending", lead=None, user=MANAGER, **data):
		frappe.set_user(user)
		data = {"status": status, "project": self.project, **data}
		row = visits.create_visit("CRM Lead", (lead or self.lead).name, data)
		frappe.set_user("Administrator")
		return row

	def hours(self, hours):
		return str(now_datetime().replace(microsecond=0) + datetime.timedelta(hours=hours))

	# status rules

	def test_defaults_and_status_rules(self):
		pending = self.create()
		self.assertEqual((pending["status"], pending["visit_type"], pending["status_color"]), ("Pending", "Site Visit", "gray"))
		self.assertIsNone(pending["visited_at"])

		scheduled = self.create(status="Pending", scheduled_on=self.hours(2))
		self.assertEqual((scheduled["status"], scheduled["status_color"]), ("Scheduled", "blue"))

		for status in ("Scheduled", "Postponed"):
			with self.assertRaises(frappe.ValidationError):
				self.create(status=status)

		visited = self.create(status="Visited")
		self.assertTrue(visited["visited_at"])
		self.assertEqual(visited["status_color"], "green")

		reason = self.create(status="Cancelled", status_reason="Client travelling")
		self.assertEqual((reason["status_reason"], reason["status_color"]), ("Client travelling", "red"))

	def test_visited_and_cancelled_are_final_except_for_a_manager(self):
		visit = self.create(status="Visited", user=REP)
		frappe.set_user(REP)
		with self.assertRaises(frappe.ValidationError):
			visits.update_visit(visit["name"], {"status": "Scheduled", "scheduled_on": self.hours(1)})
		# other fields can still be corrected
		self.assertEqual(visits.update_visit(visit["name"], {"notes": "Met the family"})["notes"], "Met the family")
		frappe.set_user(MANAGER)
		changed = visits.update_visit(visit["name"], {"status": "Scheduled", "scheduled_on": self.hours(1)})
		self.assertEqual(changed["status"], "Scheduled")

		cancelled = self.create(status="Cancelled")
		frappe.set_user(REP)
		with self.assertRaises(frappe.ValidationError):
			visits.update_visit(cancelled["name"], {"status": "Pending"})

	def test_postpone_needs_new_time_and_comments(self):
		visit = self.create(scheduled_on=self.hours(1))
		frappe.set_user(REP)
		with self.assertRaises(frappe.ValidationError):
			visits.update_visit(visit["name"], {"status": "Postponed", "scheduled_on": None})
		row = visits.update_visit(
			visit["name"], {"status": "Postponed", "scheduled_on": self.hours(3), "status_reason": "Rain"}
		)
		self.assertEqual((row["status"], row["status_color"]), ("Postponed", "orange"))
		comments = frappe.get_all(
			"Comment", filters={"reference_name": self.lead.name}, pluck="content", order_by="creation asc"
		)
		self.assertTrue(any("scheduled for" in c and self.project in c for c in comments))
		self.assertTrue(any("postponed to" in c and "Rain" in c for c in comments))

	# people

	def test_people_with_and_without_a_user(self):
		row = self.create(
			closing_manager_user=REP2, attended_by="Walk-in Broker", site_visit_assistant="Ravi", status="Pending"
		)
		self.assertEqual(row["closing_manager_user"], REP2)
		self.assertEqual(row["closing_manager_name"], frappe.db.get_value("User", REP2, "full_name"))
		self.assertEqual(row["closing_manager"], row["closing_manager_name"])
		self.assertEqual((row["attended_by"], row["attended_by_user"], row["attended_by_name"]), ("Walk-in Broker", None, "Walk-in Broker"))
		self.assertEqual(row["site_visit_assistant_name"], "Ravi")

		# a typed name replaces the user
		row = visits.update_visit(row["name"], {"closing_manager": "Outside Closer"})
		self.assertEqual((row["closing_manager_user"], row["closing_manager_name"]), (None, "Outside Closer"))

		with self.assertRaises(frappe.ValidationError):
			self.create(attended_by_user=DISABLED)

	def test_person_who_is_a_user_is_notified_once(self):
		row = self.create(closing_manager_user=REP2, scheduled_on=self.hours(5))
		rows = frappe.get_all(
			"CRM Notification",
			filters={"to_user": REP2, "type": "Automation", "reference_name": self.lead.name},
			fields=["message", "notification_text", "from_user", "reference_doctype"],
		)
		self.assertEqual(len(rows), 1)
		self.assertIn("Site visit assigned", rows[0].message)
		self.assertEqual(rows[0].reference_doctype, "CRM Lead")
		self.assertEqual(rows[0].from_user, MANAGER)
		# saving again does not notify again; nor does assigning yourself
		visits.update_visit(row["name"], {"notes": "x"})
		frappe.set_user(REP)
		own = visits.create_visit("CRM Lead", self.lead.name, {"closing_manager_user": REP})
		self.assertEqual(frappe.db.count("CRM Notification", {"to_user": REP, "type": "Automation", "reference_name": self.lead.name}), 0)
		self.assertTrue(own["name"])
		self.assertEqual(frappe.db.count("CRM Notification", {"to_user": REP2, "type": "Automation", "reference_name": self.lead.name}), 1)

	# permissions

	def test_sales_user_sees_and_writes_only_their_records(self):
		mine = self.create(user=REP)
		theirs = self.create(lead=self.other_lead, user=MANAGER)

		frappe.set_user(REP)
		self.assertEqual(visits.get_visit(mine["name"])["name"], mine["name"])
		self.assertRaises(frappe.PermissionError, visits.get_visit, theirs["name"])
		self.assertRaises(frappe.PermissionError, visits.create_visit, "CRM Lead", self.other_lead.name, {"status": "Pending"})
		self.assertRaises(frappe.PermissionError, visits.update_visit, theirs["name"], {"notes": "x"})
		self.assertRaises(frappe.PermissionError, visits.delete_visit, theirs["name"])
		self.assertRaises(frappe.PermissionError, visits.get_visits, "CRM Lead", self.other_lead.name)

		names = [v["name"] for v in visits.list_visits(project=self.project)["data"]]
		self.assertEqual(names, [mine["name"]])
		self.assertEqual(visits.visit_dashboard(project=self.project)["totals"]["total"], 1)

		frappe.set_user(MANAGER)
		self.assertEqual(visits.visit_dashboard(project=self.project)["totals"]["total"], 2)

	def test_delete_is_for_the_creator_or_a_manager(self):
		mine = self.create(user=REP)
		frappe.set_user(REP2)
		self.assertRaises(frappe.PermissionError, visits.delete_visit, mine["name"])
		frappe.set_user(REP)
		visits.delete_visit(mine["name"])
		self.assertFalse(frappe.db.exists("ABM Field Visit", mine["name"]))
		other = self.create(user=REP)
		frappe.set_user(MANAGER)
		visits.delete_visit(other["name"])
		self.assertFalse(frappe.db.exists("ABM Field Visit", other["name"]))

	# list

	def seed(self):
		v1 = self.create(status="Scheduled", scheduled_on=self.hours(48), closing_manager_user=REP, attended_by="Free Name")
		v2 = self.create(
			status="Visited",
			scheduled_on=self.hours(-24),
			outcome="Booked",
			closing_manager_user=REP,
			attended_by="free name",
			site_visit_assistant_user=REP2,
		)
		v3 = self.create(status="Scheduled", scheduled_on=self.hours(-48), closing_manager_user=REP)
		v4 = self.create(status="Cancelled", visit_type="Walk-in", status_reason="No interest")
		v5 = self.create(status="Postponed", scheduled_on=self.hours(24))
		return v1, v2, v3, v4, v5

	def test_list_visits_filters_and_order(self):
		v1, v2, v3, v4, v5 = self.seed()
		listed = visits.list_visits(project=self.project)
		self.assertEqual(len(listed["data"]), 5)
		self.assertFalse(listed["has_more"])
		# newest visit date first: a visit without a schedule is dated by its creation (now)
		self.assertEqual([v["name"] for v in listed["data"]], [v1["name"], v5["name"], v4["name"], v2["name"], v3["name"]])
		for key in ("map_url", "photo_url", "reference_title", "phone", "owner_name", "visited_by_name", "visit_date", "closing_manager_name"):
			self.assertIn(key, listed["data"][0])
		self.assertEqual(listed["data"][0]["reference_title"], self.lead.lead_name)

		def names(**kw):
			return [v["name"] for v in visits.list_visits(project=self.project, **kw)["data"]]

		self.assertEqual(sorted(names(user=REP)), sorted([v1["name"], v2["name"], v3["name"]]))
		self.assertEqual(names(user=REP2), [v2["name"]])
		self.assertEqual(names(status="Cancelled"), [v4["name"]])
		self.assertEqual(names(visit_type="Walk-in"), [v4["name"]])
		self.assertEqual(sorted(names(search="Free Name")), sorted([v1["name"], v2["name"]]))
		self.assertEqual(len(names(search=self.lead.lead_name)), 5)
		self.assertEqual(names(search="no such text"), [])
		self.assertEqual(names(date_from=nowdate(), date_to=nowdate()), [v4["name"]])
		self.assertEqual(names(order_by="upcoming")[:5], [v3["name"], v2["name"], v5["name"], v1["name"], v4["name"]])
		self.assertEqual(
			names(reference_doctype="CRM Lead", reference_docname=self.other_lead.name), []
		)
		page = visits.list_visits(project=self.project, page_length=2)
		self.assertEqual((len(page["data"]), page["has_more"]), (2, True))
		self.assertEqual(len(visits.list_visits(project=self.project, start=4, page_length=2)["data"]), 1)

	def test_get_visits_returns_visit_rows(self):
		visit = self.create(status="Scheduled", scheduled_on=self.hours(3))
		rows = visits.get_visits("CRM Lead", self.lead.name)
		self.assertEqual([r["name"] for r in rows], [visit["name"]])
		self.assertEqual(rows[0]["status"], "Scheduled")
		self.assertEqual(mobile.get_record("CRM Lead", self.lead.name)["visits"][0]["status_color"], "blue")

	def test_options(self):
		self.create()
		options = visits.get_visit_options()
		self.assertEqual([s["name"] for s in options["statuses"]], ["Pending", "Scheduled", "Visited", "Postponed", "Cancelled", "No Show"])
		self.assertEqual(options["types"], ["Site Visit", "Walk-in", "Office Meeting"])
		self.assertEqual(options["outcomes"], ["Interested", "Needs Follow-up", "Not Interested", "Booked"])
		self.assertIn(self.project, options["projects"])
		self.assertIn(MANAGER, [u["name"] for u in options["users"]])

	# dashboard

	def test_dashboard_numbers(self):
		v1, v2, v3, v4, v5 = self.seed()
		frappe.set_user(MANAGER)
		date_from, date_to = add_days(nowdate(), -10), add_days(nowdate(), 10)
		board = visits.visit_dashboard(date_from, date_to, project=self.project)

		self.assertEqual(board["range"], {"date_from": str(date_from), "date_to": str(date_to)})
		self.assertEqual(
			board["totals"],
			{
				"total": 5,
				"pending": 0,
				"scheduled": 2,
				"visited": 1,
				"postponed": 1,
				"cancelled": 1,
				"no_show": 0,
				"today": 1,
				"upcoming_7d": 2,
				"overdue": 1,
				"booked": 1,
				"completion_rate": 50.0,
			},
		)
		by_status = {s["status"]: s for s in board["by_status"]}
		self.assertEqual((by_status["Scheduled"]["count"], by_status["Scheduled"]["color"], by_status["No Show"]["count"]), (2, "blue", 0))

		people = {p["name"].lower(): p for p in board["by_user"]}
		rep = people[frappe.db.get_value("User", REP, "full_name").lower()]
		self.assertEqual((rep["user"], rep["total"], rep["as_closing_manager"], rep["visited"], rep["scheduled"]), (REP, 3, 3, 1, 2))
		assistant = people[frappe.db.get_value("User", REP2, "full_name").lower()]
		self.assertEqual((assistant["total"], assistant["as_assistant"], assistant["visited"]), (1, 1, 1))
		free = people["free name"]  # typed names group case-insensitively and have no user
		self.assertEqual((free["user"], free["total"], free["as_attended_by"]), (None, 2, 2))
		self.assertEqual((free["visited"], free["scheduled"]), (1, 1))

		self.assertEqual(board["by_project"], [{"project": self.project, "total": 5, "visited": 1, "booked": 1}])
		self.assertEqual({t["visit_type"]: t["count"] for t in board["by_type"]}, {"Site Visit": 4, "Walk-in": 1})
		self.assertEqual(sum(d["scheduled"] for d in board["by_day"]), 4)
		self.assertEqual(sum(d["visited"] for d in board["by_day"]), 1)
		visited_day = str(frappe.utils.getdate(self.hours(-24)))
		self.assertEqual([d for d in board["by_day"] if d["date"] == visited_day], [{"date": visited_day, "scheduled": 1, "visited": 1}])
		self.assertEqual([v["name"] for v in board["today"]], [v4["name"]])
		self.assertEqual([v["name"] for v in board["upcoming"]], [v5["name"], v1["name"]])
		self.assertEqual([v["name"] for v in board["overdue"]], [v3["name"]])

		# the range limits the counts but not overdue / upcoming
		narrow = visits.visit_dashboard(nowdate(), nowdate(), project=self.project)
		self.assertEqual((narrow["totals"]["total"], narrow["totals"]["overdue"], narrow["totals"]["upcoming_7d"]), (1, 1, 2))
		self.assertEqual(visits.visit_dashboard(date_from, date_to, project=self.project, user=REP2)["totals"]["total"], 1)
		self.assertEqual(visits.visit_dashboard(date_from, date_to, project=self.project, visit_type="Walk-in")["totals"]["total"], 1)

	def test_dashboard_defaults_to_the_current_month(self):
		frappe.set_user(MANAGER)
		board = visits.visit_dashboard()
		first = frappe.utils.get_first_day(nowdate())
		self.assertEqual(board["range"]["date_from"], str(first))
		self.assertEqual(board["range"]["date_to"], str(frappe.utils.get_last_day(nowdate())))

	# mobile check-in

	def test_check_in_completes_a_planned_visit(self):
		planned = self.create(status="Scheduled", scheduled_on=self.hours(1), user=MANAGER)
		frappe.set_user(REP)
		row = mobile.check_in("CRM Lead", self.lead.name, 19.07, 72.87, 10, address="Site", notes="Arrived", visit=planned["name"])
		self.assertEqual(row["name"], planned["name"])
		self.assertEqual((row["status"], row["address"], row["notes"]), ("Visited", "Site", "Arrived"))
		self.assertTrue(row["visited_at"])
		self.assertEqual(row["map_url"], "https://maps.google.com/?q=19.07,72.87")
		self.assertEqual(frappe.db.count("ABM Field Visit", {"reference_docname": self.lead.name}), 1)
		frappe.set_user(MANAGER)
		with self.assertRaises(frappe.ValidationError):  # the visit belongs to another lead
			mobile.check_in("CRM Lead", self.other_lead.name, 1, 1, visit=planned["name"])
		frappe.set_user(REP)

		created = mobile.check_in("CRM Lead", self.lead.name, 19.07, 72.87)
		self.assertEqual((created["status"], created["visit_type"], created["visited_by"]), ("Visited", "Site Visit", REP))
		self.assertEqual(frappe.db.count("ABM Field Visit", {"reference_docname": self.lead.name}), 2)

	# migration

	def test_patch_marks_old_visits_visited(self):
		from abm_crm.patches.v1_2.migrate_field_visits import execute

		visit = self.create(status="Visited")
		frappe.db.set_value("ABM Field Visit", visit["name"], {"status": "Pending", "visit_type": "Walk-in"})
		other = self.create(status="Pending")
		execute()
		self.assertEqual(frappe.db.get_value("ABM Field Visit", visit["name"], ["status", "visit_type"]), ("Visited", "Site Visit"))
		self.assertEqual(frappe.db.get_value("ABM Field Visit", other["name"], "status"), "Pending")
