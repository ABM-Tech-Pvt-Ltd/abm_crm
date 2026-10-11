"""Tests for "Idle-lead alerts" in docs/mobile-api.md. 2026-10-12 is a Monday."""

import datetime
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, now_datetime

from abm_crm import idle_alerts
from abm_crm.api import idle_alerts as api
from abm_crm.idle_alerts import normalize_rule, process_rule, working_minutes

MANAGER = "idle.manager@example.com"
OWNER = "idle.owner@example.com"
OTHER = "idle.other@example.com"
OFF = "idle.disabled@example.com"
START, END = datetime.time(10, 30), datetime.time(19, 30)
MON_TO_SAT = {0, 1, 2, 3, 4, 5}
MON_TO_FRI = {0, 1, 2, 3, 4}

no_push = patch("abm_crm.push.send_push", return_value=False)


def at(day, hour, minute=0):
	"""A moment in the week of Monday 12 Oct 2026 (day 0 = Monday)."""
	return datetime.datetime(2026, 10, 12 + day, hour, minute)


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


class TestWorkingMinutes(IntegrationTestCase):
	def minutes(self, start, end, days=MON_TO_SAT):
		return working_minutes(start, end, START, END, days)

	def test_same_day(self):
		self.assertEqual(self.minutes(at(0, 11), at(0, 12, 30)), 90)

	def test_lead_arriving_at_8pm_starts_at_1030_next_day(self):
		self.assertEqual(self.minutes(at(0, 20), at(1, 10, 15)), 0)
		self.assertEqual(self.minutes(at(0, 20), at(1, 10, 45)), 15)
		self.assertEqual(self.minutes(at(0, 20), at(1, 11, 35)), 65)

	def test_start_before_hours_counts_from_opening(self):
		self.assertEqual(self.minutes(at(0, 9), at(0, 10, 45)), 15)

	def test_end_after_closing_stops_at_closing(self):
		self.assertEqual(self.minutes(at(0, 19), at(0, 23)), 30)

	def test_boundaries(self):
		self.assertEqual(self.minutes(at(0, 10, 30), at(0, 19, 30)), 540)
		self.assertEqual(self.minutes(at(0, 19, 30), at(1, 10, 30)), 0)
		self.assertEqual(self.minutes(at(0, 12), at(0, 12)), 0)
		self.assertEqual(self.minutes(at(0, 13), at(0, 12)), 0)
		self.assertEqual(self.minutes(at(0, 10, 29), at(0, 10, 31)), 1)

	def test_multi_day_span_counts_full_days_and_partial_ends(self):
		# Monday 12:00 to 19:30 (450), all of Tuesday (540), Wednesday 10:30 to 12:00 (90)
		self.assertEqual(self.minutes(at(0, 12), at(2, 12)), 450 + 540 + 90)
		self.assertEqual(self.minutes(at(0, 10, 30), at(7, 10, 30)), 6 * 540)  # a week with Sunday off

	def test_non_working_days_are_skipped(self):
		# Saturday 19:00-19:30 and Monday 10:30-10:45; Sunday counts nothing
		self.assertEqual(self.minutes(at(5, 19), at(7, 10, 45)), 30 + 15)
		self.assertEqual(self.minutes(at(6, 11), at(6, 15)), 0)
		# with Saturday off too: Friday 19:00 to Monday 11:00
		self.assertEqual(self.minutes(at(4, 19), at(7, 11), MON_TO_FRI), 30 + 30)

	def test_accepts_database_time_values_and_no_days(self):
		self.assertEqual(working_minutes(at(0, 11), at(0, 12), datetime.timedelta(hours=10, minutes=30), "19:30:00", MON_TO_SAT), 60)
		self.assertEqual(working_minutes(at(0, 11), at(0, 12), START, END, set()), 0)
		self.assertEqual(working_minutes(at(0, 11), at(0, 12), END, START, MON_TO_SAT), 0)


class TestIdleAlerts(IntegrationTestCase):
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
		make_user(OWNER, ["Sales User"])
		make_user(OTHER, ["Sales User"])
		make_user(OFF, ["Sales User"], enabled=0)
		self.token = frappe.generate_hash(length=6)
		self.status = self.make_status(f"Idle Open {self.token}", "Open")
		self.lost_status = self.make_status(f"Idle Lost {self.token}", "Lost")
		self.role = frappe.get_doc({"doctype": "Role", "role_name": f"Idle Role {self.token}", "desk_access": 1}).insert().name
		for user in (OWNER, OTHER, OFF):
			frappe.get_doc("User", user).add_roles(self.role)
		self.lead = self.make_lead(OWNER, self.status, at(0, 10, 30))
		self.created_statuses = [self.status, self.lost_status]

		frappe.set_user(MANAGER)
		self.rule = api.save_rule(
			{
				"rule_name": f"Idle {self.token}",
				"enabled": 1,
				"statuses": [self.status],
				"work_start": "10:30:00",
				"work_end": "19:30:00",
				"mon": 1, "tue": 1, "wed": 1, "thu": 1, "fri": 1, "sat": 1, "sun": 0,
				"levels": [
					{"idle_minutes": 60, "notify_owner": 1},
					{"idle_minutes": 120, "notify_owner": 1, "notify_user": OWNER, "notify_role": self.role, "message": "Stuck for {n} min"},
				],
			}
		)
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.delete("ABM Idle Lead Alert", {"rule": ["like", f"Idle %{self.token}"]})
		frappe.db.delete("CRM Notification", {"to_user": ["in", (OWNER, OTHER, OFF, MANAGER)], "type": "Automation"})
		for name in frappe.get_all("ABM Idle Lead Rule", {"rule_name": ["like", f"%{self.token}"]}, pluck="name"):
			frappe.delete_doc("ABM Idle Lead Rule", name, force=True, ignore_permissions=True)
		for lead in frappe.get_all("CRM Lead", {"status": ["in", (self.status, self.lost_status)]}, pluck="name"):
			frappe.db.delete("Comment", {"reference_name": lead})
			frappe.delete_doc("CRM Lead", lead, force=True, ignore_permissions=True)
		for status in (self.status, self.lost_status):
			frappe.delete_doc("CRM Lead Status", status, force=True, ignore_permissions=True)
		frappe.db.delete("Has Role", {"role": self.role})
		frappe.delete_doc("Role", self.role, force=True, ignore_permissions=True)

	def make_status(self, name, type):
		return frappe.get_doc(
			{"doctype": "CRM Lead Status", "lead_status": name, "type": type, "color": "gray", "position": 900}
		).insert(ignore_permissions=True).name

	def make_lead(self, owner, status, modified):
		lead = frappe.get_doc(
			{"doctype": "CRM Lead", "first_name": f"Idle {self.token}", "lead_owner": owner, "status": self.status}
		).insert(ignore_permissions=True)
		# a lost status needs a lost reason on save; set it directly
		frappe.db.set_value("CRM Lead", lead.name, {"status": status, "modified": modified}, update_modified=False)
		return lead

	def fire(self, now):
		return process_rule(frappe.get_doc("ABM Idle Lead Rule", self.rule), now)

	def notifications(self, user=None):
		filters = {"type": "Automation", "reference_name": self.lead.name}
		if user:
			filters["to_user"] = user
		return frappe.get_all("CRM Notification", filters=filters, fields=["to_user", "message", "notification_text", "reference_doctype"])

	def alerts(self):
		return frappe.get_all(
			"ABM Idle Lead Alert",
			filters={"rule": self.rule, "lead": self.lead.name},
			fields=["level", "idle_minutes", "sent_to", "activity_marker"],
			order_by="level asc, creation asc",
		)

	# engine

	def test_a_level_fires_once_per_idle_period(self):
		self.assertEqual(self.fire(at(0, 11)), 0)  # 30 minutes idle: below the first level
		self.assertEqual(self.alerts(), [])

		self.assertEqual(self.fire(at(0, 11, 40)), 1)  # 70 minutes
		self.assertEqual([a.level for a in self.alerts()], [60])
		notes = self.notifications()
		self.assertEqual([(n.to_user, n.reference_doctype) for n in notes], [(OWNER, "CRM Lead")])
		self.assertEqual(notes[0].message, f"Idle lead: {self.lead.lead_name}")
		self.assertEqual(notes[0].notification_text, "No activity for 70 min during working hours")

		self.assertEqual(self.fire(at(0, 11, 50)), 0)  # same period, same level: nothing again
		self.assertEqual(len(self.notifications()), 1)

		self.assertEqual(self.fire(at(0, 12, 40)), 1)  # 130 minutes: the second level
		self.assertEqual([a.level for a in self.alerts()], [60, 120])
		self.assertEqual(self.fire(at(0, 13)), 0)
		self.assertEqual(len(self.alerts()), 2)

	def test_new_activity_starts_a_new_period(self):
		self.fire(at(0, 11, 40))
		self.assertEqual(len(self.alerts()), 1)
		frappe.db.set_value("CRM Lead", self.lead.name, "modified", at(0, 13), update_modified=False)
		self.assertEqual(self.fire(at(0, 13, 30)), 0)  # only 30 minutes since the new activity
		self.assertEqual(self.fire(at(0, 14, 15)), 1)  # 75 minutes: the first level fires again
		alerts = self.alerts()
		self.assertEqual([a.level for a in alerts], [60, 60])
		self.assertEqual(len({a.activity_marker for a in alerts}), 2)

	def test_a_comment_counts_as_activity(self):
		comment = frappe.get_doc(
			{"doctype": "Comment", "comment_type": "Comment", "reference_doctype": "CRM Lead", "reference_name": self.lead.name, "content": "<p>Called</p>"}
		).insert(ignore_permissions=True)
		frappe.db.set_value("Comment", comment.name, "creation", at(0, 12, 30), update_modified=False)
		self.assertEqual(self.fire(at(0, 13)), 0)  # 30 minutes since the comment; 150 since the lead changed
		self.assertEqual(self.fire(at(0, 13, 45)), 1)  # 75 minutes

	def test_idle_time_only_counts_inside_working_hours(self):
		frappe.db.set_value("CRM Lead", self.lead.name, "modified", at(0, 20), update_modified=False)
		self.assertEqual(self.fire(at(1, 10, 45)), 0)  # 15 working minutes
		self.assertEqual(self.fire(at(1, 11, 35)), 1)  # 65

	def test_weekend_is_skipped(self):
		frappe.db.set_value("CRM Lead", self.lead.name, "modified", at(5, 19), update_modified=False)
		self.assertEqual(self.fire(at(6, 15)), 0)  # Sunday is off: 30 minutes so far
		self.assertEqual(self.fire(at(7, 10, 45)), 0)  # Monday: 30 + 15
		self.assertEqual(self.fire(at(7, 11, 20)), 1)  # 30 + 50

	def test_when_several_levels_are_passed_only_the_highest_notifies(self):
		self.assertEqual(self.fire(at(0, 15)), 1)  # 270 minutes: both levels
		self.assertEqual([(a.level, bool(a.sent_to)) for a in self.alerts()], [(60, False), (120, True)])
		self.assertEqual(self.fire(at(0, 16)), 0)

	def test_recipients_are_not_repeated(self):
		self.fire(at(0, 15))
		users = [n.to_user for n in self.notifications()]
		# owner (as owner and as user and through the role), the role's other user: each once; disabled user never
		self.assertCountEqual(users, [OWNER, OTHER])
		self.assertEqual(self.notifications(OWNER)[0].notification_text, "Stuck for 270 min")
		self.assertEqual(sorted(self.alerts()[-1].sent_to.split(", ")), sorted([OWNER, OTHER]))

		level = normalize_rule(frappe.get_doc("ABM Idle Lead Rule", self.rule)).levels[1]
		self.assertEqual(sorted(idle_alerts.recipients_for(level, {"lead_owner": OWNER})), sorted([OWNER, OTHER]))
		self.assertEqual(sorted(idle_alerts.recipients_for(level, {"lead_owner": None})), sorted([OWNER, OTHER]))

	def test_won_and_lost_statuses_are_only_watched_when_listed(self):
		empty = normalize_rule({"statuses": [], "levels": [{"idle_minutes": 5, "notify_owner": 1}]})
		watched = idle_alerts.watched_statuses(empty)
		self.assertIn(self.status, watched)
		self.assertNotIn(self.lost_status, watched)
		lost = self.make_lead(OWNER, self.lost_status, at(0, 10, 30))
		listed = normalize_rule(
			{"statuses": [self.lost_status], "levels": [{"idle_minutes": 5, "notify_owner": 1}], "mon": 1, "tue": 1}
		)
		self.assertEqual([r["name"] for r in idle_alerts.idle_leads(listed, at(0, 12))], [lost.name])

	def test_only_assigned_and_converted_leads(self):
		unowned = self.make_lead(None, self.status, at(0, 10, 30))
		rule = {"statuses": [self.status], "levels": [{"idle_minutes": 5, "notify_owner": 1}], "mon": 1}
		names = {r["name"] for r in idle_alerts.idle_leads(normalize_rule(rule), at(0, 12))}
		self.assertEqual(names, {self.lead.name, unowned.name})
		names = {r["name"] for r in idle_alerts.idle_leads(normalize_rule({**rule, "only_assigned": 1}), at(0, 12))}
		self.assertEqual(names, {self.lead.name})
		frappe.db.set_value("CRM Lead", self.lead.name, "converted", 1, update_modified=False)
		names = {r["name"] for r in idle_alerts.idle_leads(normalize_rule(rule), at(0, 12))}
		self.assertEqual(names, {unowned.name})

	# API

	def test_preview_sends_nothing(self):
		frappe.set_user(MANAGER)
		rule = {
			"rule_name": "unsaved",
			"statuses": [self.status],
			"levels": [{"idle_minutes": 60, "notify_owner": 1}],
			"mon": 1, "tue": 1, "wed": 1, "thu": 1, "fri": 1, "sat": 1,
		}
		self.make_lead(OWNER, self.status, add_days(now_datetime(), -4))
		self.lead_modified_days_ago(4)
		before = frappe.db.count("CRM Notification"), frappe.db.count("ABM Idle Lead Alert")
		preview = api.preview_rule(rule)
		self.assertGreaterEqual(preview["idle_now"], 2)
		self.assertEqual(
			set(preview["leads"][0]), {"name", "lead_name", "owner_name", "status", "idle_minutes"}
		)
		self.assertEqual(preview["leads"][0]["status"], self.status)
		self.assertEqual(preview["leads"][0]["owner_name"], frappe.db.get_value("User", OWNER, "full_name"))
		self.assertEqual((frappe.db.count("CRM Notification"), frappe.db.count("ABM Idle Lead Alert")), before)
		self.assertFalse(frappe.db.exists("ABM Idle Lead Rule", "unsaved"))

	def lead_modified_days_ago(self, days):
		frappe.db.set_value("CRM Lead", self.lead.name, "modified", add_days(now_datetime(), -days), update_modified=False)

	def test_setup_rules_and_lists(self):
		frappe.set_user(MANAGER)
		setup = api.get_setup()
		rule = next(r for r in setup["rules"] if r["name"] == self.rule)
		self.assertEqual((rule["statuses"], rule["work_start"], rule["work_end"], rule["sat"], rule["sun"]), ([self.status], "10:30:00", "19:30:00", 1, 0))
		self.assertEqual([lv["idle_minutes"] for lv in rule["levels"]], [60, 120])
		self.assertIn(self.status, [s["name"] for s in setup["statuses"]])
		self.assertIn(MANAGER, [u["name"] for u in setup["users"]])
		self.assertIn(self.role, setup["roles"])

		self.lead_modified_days_ago(4)
		idle = api.list_idle_leads(rule=self.rule)
		self.assertEqual([(r["name"], r["rule"], r["level"]) for r in idle["data"]], [(self.lead.name, self.rule, 120)])
		self.assertEqual(idle["data"][0]["owner_name"], frappe.db.get_value("User", OWNER, "full_name"))
		self.assertEqual(api.list_idle_leads(rule=self.rule, user=OTHER)["data"], [])

		self.assertEqual(api.run_now().keys(), {"alerts"})
		alerts = api.list_alerts(lead=self.lead.name)
		self.assertEqual([a["level"] for a in alerts["data"]], [120, 60][:len(alerts["data"])])
		self.assertEqual(alerts["data"][0]["lead_name"], self.lead.lead_name)
		self.assertEqual(alerts["data"][0]["rule"], self.rule)

		# renaming keeps the history; disabling and deleting work
		new_name = f"Idle renamed {self.token}"
		api.save_rule({"name": self.rule, "rule_name": new_name})
		self.assertEqual(frappe.db.count("ABM Idle Lead Alert", {"rule": new_name}), len(alerts["data"]))
		self.assertFalse(frappe.db.exists("ABM Idle Lead Rule", self.rule))
		self.rule = new_name
		api.set_rule_enabled(new_name, 0)
		self.assertEqual(frappe.db.get_value("ABM Idle Lead Rule", new_name, "enabled"), 0)
		api.delete_rule(new_name)
		self.assertFalse(frappe.db.exists("ABM Idle Lead Rule", new_name))
		self.assertEqual(frappe.db.count("ABM Idle Lead Alert", {"rule": new_name}), 0)

	def test_rule_validation(self):
		frappe.set_user(MANAGER)
		base = {"rule_name": f"Bad {self.token}", "levels": [{"idle_minutes": 30, "notify_owner": 1}]}
		for bad in (
			{**base, "work_start": "19:30:00", "work_end": "10:30:00"},
			{**base, "mon": 0, "tue": 0, "wed": 0, "thu": 0, "fri": 0, "sat": 0, "sun": 0},
			{**base, "levels": []},
			{**base, "levels": [{"idle_minutes": 0, "notify_owner": 1}]},
			{**base, "levels": [{"idle_minutes": 30}]},
			{**base, "levels": [{"idle_minutes": 30, "notify_owner": 1}, {"idle_minutes": 30, "notify_user": OWNER}]},
		):
			with self.assertRaises(frappe.ValidationError):
				api.save_rule(bad)
		self.assertEqual(api.save_rule(base), base["rule_name"])
		frappe.delete_doc("ABM Idle Lead Rule", base["rule_name"], force=True, ignore_permissions=True)

	def test_permissions(self):
		frappe.set_user(OWNER)
		self.assertRaises(frappe.PermissionError, api.get_setup)
		self.assertRaises(frappe.PermissionError, api.save_rule, {"rule_name": "x"})
		self.assertRaises(frappe.PermissionError, api.delete_rule, self.rule)
		self.assertRaises(frappe.PermissionError, api.set_rule_enabled, self.rule, 0)
		self.assertRaises(frappe.PermissionError, api.preview_rule, {})
		self.assertRaises(frappe.PermissionError, api.run_now)
		# a rep sees only the alerts on their own leads
		frappe.set_user("Administrator")
		self.fire(at(0, 15))
		frappe.set_user(OWNER)
		self.assertEqual(len(api.list_alerts(lead=self.lead.name)["data"]), 2)
		frappe.set_user(OTHER)
		self.assertEqual(api.list_alerts(lead=self.lead.name)["data"], [])
		# the log cannot be edited or created through the desk
		self.assertFalse(frappe.has_permission("ABM Idle Lead Alert", "write", user=MANAGER))
		self.assertFalse(frappe.has_permission("ABM Idle Lead Alert", "create", user=MANAGER))
		self.assertTrue(frappe.has_permission("ABM Idle Lead Alert", "read", user=MANAGER))

	def test_scheduler_runs_every_five_minutes(self):
		from abm_crm import hooks

		self.assertEqual(hooks.scheduler_events["cron"]["*/5 * * * *"], ["abm_crm.idle_alerts.run_check"])
