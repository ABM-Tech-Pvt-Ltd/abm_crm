import frappe
from crm.fcrm.doctype.crm_lead.crm_lead import convert_to_deal
from frappe.tests import IntegrationTestCase

from abm_crm.api import mobile, tags

REP = "tags.rep@example.com"
REP2 = "tags.rep2@example.com"
OUTSIDER = "tags.outsider@example.com"


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


def make_lead(**fields):
	return frappe.get_doc({"doctype": "CRM Lead", "first_name": "Tags Test", **fields}).insert(
		ignore_permissions=True
	)


class TestTags(IntegrationTestCase):
	def setUp(self):
		make_user(REP, ["Sales User"])
		make_user(REP2, ["Sales User"])
		make_user(OUTSIDER, [])
		self.suffix = frappe.generate_hash(length=6)
		self.tag = f"Lodha {self.suffix}"
		self.lead = make_lead(lead_owner=REP)

	def tearDown(self):
		frappe.set_user("Administrator")
		for name in frappe.get_all("Tag", filters={"name": ["like", f"%{self.suffix}%"]}, pluck="name"):
			frappe.db.delete("Tag Link", {"tag": name})
			frappe.delete_doc("Tag", name, force=True, ignore_permissions=True)

	def names(self, rows):
		return [t["name"] for t in rows]

	def test_add_creates_tag_and_link(self):
		frappe.set_user(REP)
		result = tags.add_tag("CRM Lead", self.lead.name, f"  Lodha   {self.suffix} ", "builder", "Blue")
		self.assertEqual(result, [{"name": self.tag, "category": "Builder", "color": "blue"}])
		self.assertEqual(frappe.db.get_value("CRM Lead", self.lead.name, "_user_tags"), self.tag)
		self.assertTrue(
			frappe.db.exists(
				"Tag Link", {"document_type": "CRM Lead", "document_name": self.lead.name, "tag": self.tag}
			)
		)
		listed = {t["name"]: t for t in tags.get_tags()}
		self.assertEqual(listed[self.tag]["count"], 1)
		self.assertEqual(listed[self.tag]["category"], "Builder")

	def test_reuses_existing_tag_case_insensitively(self):
		frappe.set_user(REP)
		tags.add_tag("CRM Lead", self.lead.name, self.tag)
		other = make_lead(lead_owner=REP)
		result = tags.add_tag("CRM Lead", other.name, self.tag.lower())
		self.assertEqual(self.names(result), [self.tag])
		self.assertEqual(frappe.db.count("Tag", {"name": ["like", f"%{self.suffix}%"]}), 1)
		# adding again does not duplicate
		tags.add_tag("CRM Lead", other.name, self.tag.upper())
		self.assertEqual(self.names(tags.get_doc_tags("CRM Lead", other.name)), [self.tag])

	def test_remove_tag(self):
		frappe.set_user(REP)
		tags.add_tag("CRM Lead", self.lead.name, self.tag)
		tags.add_tag("CRM Lead", self.lead.name, f"Pune {self.suffix}")
		result = tags.remove_tag("CRM Lead", self.lead.name, self.tag.lower())
		self.assertEqual(self.names(result), [f"Pune {self.suffix}"])
		self.assertFalse(
			frappe.db.exists(
				"Tag Link", {"document_type": "CRM Lead", "document_name": self.lead.name, "tag": self.tag}
			)
		)

	def test_update_tag(self):
		frappe.set_user(REP)
		tags.add_tag("CRM Lead", self.lead.name, self.tag)
		self.assertEqual(
			tags.update_tag(self.tag.lower(), "Location", "teal"),
			{"name": self.tag, "category": "Location", "color": "teal"},
		)
		self.assertRaises(frappe.ValidationError, tags.update_tag, self.tag, "Nope")

	def test_permissions(self):
		frappe.set_user(REP2)
		self.assertRaises(frappe.PermissionError, tags.add_tag, "CRM Lead", self.lead.name, self.tag)
		frappe.set_user(REP)
		tags.add_tag("CRM Lead", self.lead.name, self.tag)
		frappe.set_user(REP2)
		self.assertRaises(frappe.PermissionError, tags.remove_tag, "CRM Lead", self.lead.name, self.tag)
		frappe.set_user(OUTSIDER)
		self.assertRaises(frappe.PermissionError, tags.update_tag, self.tag, "Builder")
		self.assertRaises(frappe.PermissionError, tags.get_tags)
		frappe.set_user(REP)
		self.assertRaises(frappe.ValidationError, tags.add_tag, "Contact", "x", self.tag)
		self.assertRaises(frappe.ValidationError, tags.add_tag, "CRM Lead", self.lead.name, "a, b")

	def test_deal_copies_lead_tags(self):
		frappe.set_user(REP)
		tags.add_tag("CRM Lead", self.lead.name, self.tag, "Builder")
		tags.add_tag("CRM Lead", self.lead.name, f"Pune {self.suffix}")
		frappe.set_user("Administrator")
		deal = convert_to_deal(self.lead.name)
		self.assertEqual(
			self.names(tags.get_doc_tags("CRM Deal", deal)), [self.tag, f"Pune {self.suffix}"]
		)
		self.assertEqual(
			frappe.db.count("Tag Link", {"document_type": "CRM Deal", "document_name": deal}), 2
		)

	def test_mobile_rows_and_tag_filter(self):
		frappe.set_user(REP)
		org = f"Tags Org {self.suffix}"
		tagged = make_lead(lead_owner=REP, organization=org)
		near_miss = make_lead(lead_owner=REP, organization=org)
		make_lead(lead_owner=REP, organization=org)
		tags.add_tag("CRM Lead", tagged.name, self.tag, "Builder", "red")
		tags.add_tag("CRM Lead", tagged.name, f"Pune {self.suffix}")
		tags.add_tag("CRM Lead", near_miss.name, f"{self.tag} Park")

		result = mobile.list_leads(search=org, tag=self.tag.lower())
		self.assertEqual([r["name"] for r in result["data"]], [tagged.name])
		row = result["data"][0]
		self.assertNotIn("_user_tags", row)
		self.assertEqual(row["tags"][0], {"name": self.tag, "category": "Builder", "color": "red"})
		self.assertEqual(self.names(row["tags"]), [self.tag, f"Pune {self.suffix}"])

		self.assertEqual(len(mobile.list_leads(search=org)["data"]), 3)
		self.assertEqual(mobile.list_leads(search=org, tag=f"Nothing {self.suffix}")["data"], [])
		self.assertEqual(self.names(mobile.get_record("CRM Lead", tagged.name)["doc"]["tags"]), [
			self.tag,
			f"Pune {self.suffix}",
		])
