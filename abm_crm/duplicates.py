"""Duplicate leads: same phone number (last 10 digits) as an existing lead.

A duplicate is kept, not skipped or merged, so nothing is lost and the team can decide. The new lead
is tagged "Duplicate" (red, category Other) and gets a comment naming the lead(s) it matches.

Numbers are compared on their last 10 digits only, so "+91 98765 43210", "098765 43210" and
"9876543210" all match. The key is stored in a hidden, indexed field (`abm_phone_key`) kept up to
date on every save, so a lookup is one indexed query.
"""

import re

import frappe
from frappe import _
from frappe.desk.doctype.tag.tag import DocTags

DUPLICATE_TAG = "Duplicate"
KEY_LENGTH = 10
MANAGER_ROLES = ("System Manager", "Sales Manager")


def phone_key(number: str | None) -> str | None:
	"""Last 10 digits of a phone number, or None when it has fewer than 10 digits."""
	digits = re.sub(r"\D", "", number or "")
	return digits[-KEY_LENGTH:] if len(digits) >= KEY_LENGTH else None


def lead_phone_key(doc) -> str | None:
	return phone_key(doc.get("mobile_no")) or phone_key(doc.get("phone"))


def set_phone_key(doc, method=None) -> None:
	"""CRM Lead.validate: keep the key in step with the number."""
	doc.abm_phone_key = lead_phone_key(doc)


def tag_duplicate(doc, method=None) -> None:
	"""CRM Lead.after_insert: tag the new lead when another lead has the same number."""
	key = doc.get("abm_phone_key") or lead_phone_key(doc)
	if not key:
		return
	matches = find_matches(key, exclude=doc.name)
	if not matches:
		return
	mark_duplicate(doc.name, matches)


def find_matches(key: str, exclude: str | None = None) -> list[str]:
	filters = {"abm_phone_key": key}
	if exclude:
		filters["name"] = ["!=", exclude]
	return frappe.get_all("CRM Lead", filters=filters, pluck="name", order_by="creation asc", limit=20)


def mark_duplicate(lead: str, matches: list[str]) -> None:
	DocTags("CRM Lead").add(lead, duplicate_tag())
	shown = ", ".join(matches[:3]) + (f" and {len(matches) - 3} more" if len(matches) > 3 else "")
	frappe.get_doc(
		{
			"doctype": "Comment",
			"comment_type": "Comment",
			"reference_doctype": "CRM Lead",
			"reference_name": lead,
			"content": "<p><b>{}</b></p><p>{}</p>".format(
				_("Possible duplicate"),
				_("Same phone number as {0}.").format(shown),
			),
		}
	).insert(ignore_permissions=True)


def duplicate_tag() -> str:
	"""The Duplicate tag, created on first use. An existing tag keeps whatever color the team gave it."""
	from abm_crm.api.tags import ensure_tag, find_tag

	return find_tag(DUPLICATE_TAG) or ensure_tag(DUPLICATE_TAG, "Other", "red")


@frappe.whitelist()
def tag_existing_duplicates() -> dict:
	"""Tag leads that already share a number with an older lead. Run once after installing.

	The oldest lead of each group stays untagged; every later one gets the Duplicate tag and a
	comment. Safe to run again: leads that already have the tag are skipped.
	"""
	frappe.only_for(MANAGER_ROLES)
	groups = frappe.db.sql(
		"""select abm_phone_key from `tabCRM Lead`
		where ifnull(abm_phone_key, '') != ''
		group by abm_phone_key having count(*) > 1""",
		pluck=True,
	)
	tagged = 0
	for key in groups:
		leads = frappe.get_all(
			"CRM Lead",
			filters={"abm_phone_key": key},
			fields=["name", "_user_tags"],
			order_by="creation asc",
		)
		first, rest = leads[0], leads[1:]
		for lead in rest:
			if DUPLICATE_TAG.lower() in (lead._user_tags or "").lower():
				continue
			mark_duplicate(lead.name, [first.name])
			tagged += 1
	return {"groups": len(groups), "tagged": tagged}
