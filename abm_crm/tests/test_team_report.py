"""Tests for "Team report" and "Lead info" in docs/mobile-api.md."""

import datetime

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, now_datetime, nowdate

from abm_crm.api import mobile

MANAGER = "team.manager@example.com"
REP = "team.rep@example.com"
REP2 = "team.rep2@example.com"


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


class TestTeamReport(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		for email, role in ((MANAGER, "Sales Manager"), (REP, "Sales User"), (REP2, "Sales User")):
			make_user(email, [role])
		# these users own nothing else: clear leftovers of an interrupted run
		self.cleanup()
		self.open_status = frappe.get_all("CRM Lead Status", {"type": "Open"}, pluck="name", order_by="position asc")[0]
		self.lost_status = frappe.get_all("CRM Lead Status", {"type": "Lost"}, pluck="name")[0]
		self.token = frappe.generate_hash(length=6)
		self.fresh = self.lead(REP, f"Fresh {self.token}")
		self.stale = self.lead(REP, f"Stale {self.token}")
		self.lost = self.lead(REP, f"Lost {self.token}")
		self.other = self.lead(REP2, f"Other {self.token}")
		old = add_days(now_datetime(), -3).replace(microsecond=0)
		frappe.db.set_value("CRM Lead", self.lost.name, "status", self.lost_status, update_modified=False)
		for lead in (self.stale, self.lost):
			frappe.db.set_value("CRM Lead", lead.name, "modified", old, update_modified=False)
		self.call(self.fresh)
		frappe.get_doc(
			{
				"doctype": "ABM Field Visit",
				"reference_doctype": "CRM Lead",
				"reference_docname": self.fresh.name,
				"status": "Scheduled",
				"scheduled_on": now_datetime(),
				"attended_by_user": REP,
			}
		).insert(ignore_permissions=True)

	def tearDown(self):
		self.cleanup()

	def cleanup(self):
		frappe.set_user("Administrator")
		leads = frappe.get_all("CRM Lead", {"lead_owner": ["in", (REP, REP2)]}, pluck="name")
		for doctype, field in (("ABM Field Visit", "reference_docname"), ("CRM Call Log", "reference_docname"), ("Comment", "reference_name")):
			frappe.db.delete(doctype, {field: ["in", leads or [""]]})
		for name in leads:
			frappe.delete_doc("CRM Lead", name, force=True, ignore_permissions=True)

	def lead(self, owner, name, **fields):
		return frappe.get_doc(
			{"doctype": "CRM Lead", "first_name": name, "lead_owner": owner, "status": self.open_status, **fields}
		).insert(ignore_permissions=True)

	def call(self, lead, caller=REP):
		return frappe.get_doc(
			{
				"doctype": "CRM Call Log",
				"id": frappe.generate_hash(length=10),
				"telephony_medium": "Manual",
				"type": "Outgoing",
				"status": "Completed",
				"from": "+917000020001",
				"to": "+917000020002",
				"duration": 30,
				"start_time": now_datetime(),
				"caller": caller,
				"reference_doctype": "CRM Lead",
				"reference_docname": lead.name,
			}
		).insert(ignore_permissions=True)

	def report(self, **kwargs):
		frappe.set_user(MANAGER)
		return mobile.get_team_report(date_from=nowdate(), date_to=nowdate(), **kwargs)

	def test_summary_for_one_rep(self):
		report = self.report(user=REP)
		self.assertEqual(report["user"]["name"], REP)
		self.assertEqual(report["reps"], [])
		self.assertEqual(
			report["summary"],
			{
				"leads_total": 3,
				"leads_open": 2,
				"leads_new": 3,
				"leads_contacted": 1,
				"leads_idle": 1,
				"leads_converted": 0,
				"calls": 1,
				"connected": 1,
				"missed": 0,
				"talk_time": 30,
				"visits_scheduled": 1,
				"visits_done": 0,
				"deals_created": 0,
			},
		)
		by_status = {s["status"]: s["count"] for s in report["by_status"]}
		self.assertEqual((by_status[self.open_status], by_status[self.lost_status]), (2, 1))
		self.assertEqual(report["by_source"], [{"source": "Unknown", "count": 3}])
		# a long idle limit counts nothing idle; a short one counts the fresh lead too only when it is old enough
		self.assertEqual(self.report(user=REP, idle_hours=24 * 7)["summary"]["leads_idle"], 0)
		self.assertEqual(self.report(user=REP, idle_hours=1)["summary"]["leads_idle"], 1)

	def test_team_report_lists_reps_and_sums_them(self):
		report = self.report()
		self.assertIsNone(report["user"])
		reps = {r["user"]: r for r in report["reps"]}
		self.assertEqual((reps[REP]["leads_total"], reps[REP2]["leads_total"], reps[REP2]["calls"]), (3, 1, 0))
		self.assertEqual(reps[REP]["full_name"], frappe.db.get_value("User", REP, "full_name"))
		for key in ("leads_total", "calls", "leads_idle", "visits_scheduled"):
			self.assertEqual(report["summary"][key], sum(r[key] for r in report["reps"]))

	def test_range_limits_the_numbers_but_not_ownership(self):
		frappe.set_user(MANAGER)
		old = mobile.get_team_report(user=REP, date_from=add_days(nowdate(), -30), date_to=add_days(nowdate(), -20))
		self.assertEqual((old["summary"]["leads_total"], old["summary"]["leads_open"]), (3, 2))
		self.assertEqual((old["summary"]["leads_new"], old["summary"]["calls"], old["summary"]["visits_scheduled"]), (0, 0, 0))

	def test_a_sales_user_only_sees_themselves(self):
		frappe.set_user(REP)
		report = mobile.get_team_report(user=REP2, date_from=nowdate(), date_to=nowdate())
		self.assertEqual(report["user"]["name"], REP)
		self.assertEqual(report["summary"]["leads_total"], 3)
		leads = mobile.list_team_leads(user=REP2)["data"]
		self.assertEqual({lead["lead_owner"] for lead in leads}, {REP})

	def test_lead_wise_list_sorted_by_idle(self):
		frappe.get_doc(
			{
				"doctype": "ABM Field Visit",
				"reference_doctype": "CRM Lead",
				"reference_docname": self.fresh.name,
				"status": "Scheduled",
				"scheduled_on": add_days(now_datetime(), 1),
			}
		).insert(ignore_permissions=True)
		frappe.set_user(MANAGER)
		listed = mobile.list_team_leads(user=REP, date_from=nowdate(), date_to=nowdate())
		self.assertEqual([lead["name"] for lead in listed["data"]], [self.stale.name, self.fresh.name, self.lost.name])
		stale, fresh = listed["data"][0], listed["data"][1]
		self.assertGreaterEqual(stale["idle_minutes"], 3 * 24 * 60 - 1)
		self.assertLess(fresh["idle_minutes"], 5)
		self.assertEqual((stale["calls"], stale["last_call"], stale["last_contacted"], stale["visits"]), (0, None, None, 0))
		self.assertEqual((fresh["calls"], fresh["visits"]), (1, 1))
		self.assertTrue(fresh["last_call"] and fresh["last_contacted"] and fresh["next_visit"])
		self.assertEqual(fresh["owner_name"], frappe.db.get_value("User", REP, "full_name"))
		for key in ("lead_name", "status", "mobile_no", "lead_owner", "tags", "last_activity"):
			self.assertIn(key, fresh)

		self.assertEqual([lead["name"] for lead in mobile.list_team_leads(user=REP, idle_only=1)["data"]], [self.stale.name])
		self.assertEqual(
			[lead["name"] for lead in mobile.list_team_leads(user=REP, sort="recent")["data"]][0], self.fresh.name
		)
		self.assertEqual([lead["name"] for lead in mobile.list_team_leads(user=REP, sort="created")["data"]][0], self.lost.name)
		self.assertEqual([lead["name"] for lead in mobile.list_team_leads(user=REP, status=self.lost_status)["data"]], [self.lost.name])
		self.assertEqual([lead["name"] for lead in mobile.list_team_leads(user=REP, search=f"Fresh {self.token}")["data"]], [self.fresh.name])
		page = mobile.list_team_leads(user=REP, page_length=2)
		self.assertEqual((len(page["data"]), page["has_more"]), (2, True))
		self.assertEqual(len(mobile.list_team_leads(user=REP, start=2, page_length=2)["data"]), 1)
		# the whole team
		everyone = mobile.list_team_leads(search=self.token)["data"]
		self.assertEqual({lead["name"] for lead in everyone}, {self.fresh.name, self.stale.name, self.lost.name, self.other.name})

	def test_comment_counts_as_activity(self):
		frappe.set_user("Administrator")
		frappe.get_doc(
			{"doctype": "Comment", "comment_type": "Comment", "reference_doctype": "CRM Lead", "reference_name": self.stale.name, "content": "<p>Spoke</p>"}
		).insert(ignore_permissions=True)
		frappe.set_user(MANAGER)
		row = next(lead for lead in mobile.list_team_leads(user=REP)["data"] if lead["name"] == self.stale.name)
		self.assertLess(row["idle_minutes"], 5)
		self.assertIsNone(row["last_contacted"])  # a comment is not contact

	def test_lead_info_in_get_record(self):
		frappe.set_user(MANAGER)
		doc = mobile.get_record("CRM Lead", self.fresh.name)["doc"]
		self.assertEqual(doc["lead_owner_name"], frappe.db.get_value("User", REP, "full_name"))
		self.assertEqual(doc["owner"], "Administrator")
		self.assertEqual(doc["owner_name"], frappe.db.get_value("User", "Administrator", "full_name"))
		self.assertTrue(doc["modified_by_name"])
		self.assertTrue(doc["last_activity"] and doc["last_contacted"])
		self.assertLess(doc["idle_minutes"], 5)
		stale = mobile.get_record("CRM Lead", self.stale.name)["doc"]
		self.assertGreaterEqual(stale["idle_minutes"], 3 * 24 * 60 - 1)
		self.assertIsNone(stale["last_contacted"])

		calls = mobile.get_record("CRM Lead", self.fresh.name)["calls"]
		self.assertEqual((calls[0]["rep"], calls[0]["rep_name"]), (REP, frappe.db.get_value("User", REP, "full_name")))
		frappe.set_user(MANAGER)
		listed = mobile.list_calls(scope="team", date_from=nowdate(), date_to=nowdate())["data"]
		self.assertIn(REP, [c["rep"] for c in listed])
		self.assertTrue(all("rep_name" in c for c in listed))
