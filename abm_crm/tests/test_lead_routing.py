import frappe
from frappe.tests import IntegrationTestCase

from abm_crm.lead_routing import route, text_matches

USERS = ("routing.a@example.com", "routing.b@example.com", "routing.c@example.com")


def make_user(email):
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
				"roles": [{"role": "Sales User"}],
			}
		).insert(ignore_permissions=True)


def make_rule(name, users, **conditions):
	return frappe.get_doc(
		{
			"doctype": "ABM Lead Routing Rule",
			"rule_name": name,
			"users": [{"user": u, **extra} for u, extra in users],
			**conditions,
		}
	).insert(ignore_permissions=True)


def make_lead(**fields):
	return frappe.get_doc({"doctype": "CRM Lead", "first_name": "Routing Test", **fields}).insert(
		ignore_permissions=True
	)


class TestTextMatches(IntegrationTestCase):
	def test_contains_is_case_insensitive_and_accepts_lists(self):
		self.assertTrue(text_matches("diwali, festive", ["DIWALI Sale 2026"], "Contains"))
		self.assertTrue(text_matches("diwali\nfestive", ["Festive offer"], "Contains"))
		self.assertFalse(text_matches("diwali", ["Brand awareness"], "Contains"))

	def test_equals_and_starts_with(self):
		self.assertTrue(text_matches("12021", ["Some name", "12021"], "Equals"))
		self.assertFalse(text_matches("1202", ["12021"], "Equals"))
		self.assertTrue(text_matches("ig_", ["IG_Retarget"], "Starts With"))


class TestLeadRouting(IntegrationTestCase):
	def setUp(self):
		for email in USERS:
			make_user(email)
		for name in frappe.get_all("ABM Lead Routing Rule", pluck="name"):
			frappe.delete_doc("ABM Lead Routing Rule", name, force=True)

	def test_round_robin_by_campaign(self):
		make_rule("Diwali", [(USERS[0], {}), (USERS[1], {})], campaign="diwali", priority=10)
		owners = [make_lead(abm_campaign="Diwali Sale").lead_owner for _ in range(3)]
		self.assertEqual(owners, [USERS[0], USERS[1], USERS[0]])

	def test_highest_priority_rule_wins(self):
		make_rule("Low", [(USERS[0], {})], campaign="diwali", priority=1)
		make_rule("High", [(USERS[1], {})], campaign="diwali", priority=50)
		lead = make_lead(abm_campaign="Diwali Sale")
		self.assertEqual(lead.lead_owner, USERS[1])
		self.assertEqual(lead.abm_routing_rule, "High")

	def test_cap_uses_fallback_user(self):
		make_rule(
			"Instagram",
			[(USERS[2], {"max_open_leads": 1})],
			platform="Instagram",
			fallback_user=USERS[0],
		)
		first = make_lead(abm_platform="Instagram")
		second = make_lead(abm_platform="Instagram")
		self.assertEqual(first.lead_owner, USERS[2])
		self.assertEqual(second.lead_owner, USERS[0])

	def test_unmatched_and_owned_leads_are_left_alone(self):
		make_rule("Diwali", [(USERS[0], {})], campaign="diwali")
		self.assertFalse(make_lead(abm_campaign="Brand").lead_owner)
		owned = make_lead(abm_campaign="Diwali", lead_owner=USERS[1])
		self.assertEqual(owned.lead_owner, USERS[1])

	def test_dry_run_does_not_advance_round_robin(self):
		make_rule("Diwali", [(USERS[0], {}), (USERS[1], {})], campaign="diwali")
		lead = frappe.get_doc({"doctype": "CRM Lead", "first_name": "Dry", "abm_campaign": "Diwali"})
		self.assertEqual(route(lead, dry_run=True)["user"], USERS[0])
		self.assertEqual(route(lead, dry_run=True)["user"], USERS[0])
