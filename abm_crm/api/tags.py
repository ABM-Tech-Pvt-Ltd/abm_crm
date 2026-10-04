"""Tags on leads and deals, shared by the web CRM and the mobile app. The contract is in docs/mobile-api.md.

Uses Frappe's own tag system (the `Tag` doctype, the `_user_tags` column and `Tag Link`), so tags
added here show up in the CRM's "Tags like ..." filters and in the desk. abm_crm adds a category and
a color to Tag (custom fields `abm_category` and `abm_color`).
"""

import re

import frappe
from frappe import _
from frappe.desk.doctype.tag.tag import DocTags

from abm_crm.setup.install import TAG_CATEGORIES, TAG_COLORS

CRM_DOCTYPES = ("CRM Lead", "CRM Deal")
CRM_ROLES = ("Sales User", "Sales Manager", "System Manager")


@frappe.whitelist()
def get_tags() -> list[dict]:
	"""Every tag with its category, color and how many leads and deals use it."""
	check_crm_user()
	counts = dict(
		frappe.db.sql(
			"select tag, count(*) from `tabTag Link` where document_type in %s group by tag",
			(CRM_DOCTYPES,),
		)
	)
	tags = frappe.get_all("Tag", fields=["name", "abm_category", "abm_color"])
	result = [{**tag_row(t), "count": counts.get(t.name, 0)} for t in tags]
	# tags without a category go last
	result.sort(key=lambda t: (not t["category"], (t["category"] or "").lower(), t["name"].lower()))
	return result


@frappe.whitelist()
def get_doc_tags(doctype: str, name: str) -> list[dict]:
	check_doctype(doctype)
	frappe.get_doc(doctype, name).check_permission("read")
	return doc_tags(doctype, name)


@frappe.whitelist(methods=["POST"])
def add_tag(
	doctype: str, name: str, tag: str, category: str | None = None, color: str | None = None
) -> list[dict]:
	"""Apply a tag to a lead or deal, creating the tag first if needed."""
	check_doctype(doctype)
	check_crm_user()
	frappe.get_doc(doctype, name).check_permission("write")
	tag_name = ensure_tag(tag, category, color)
	DocTags(doctype).add(name, tag_name)
	return doc_tags(doctype, name)


@frappe.whitelist(methods=["POST"])
def remove_tag(doctype: str, name: str, tag: str) -> list[dict]:
	check_doctype(doctype)
	frappe.get_doc(doctype, name).check_permission("write")
	tag_name = find_tag(normalize_tag(tag)) or normalize_tag(tag)
	DocTags(doctype).remove(name, tag_name)
	return doc_tags(doctype, name)


@frappe.whitelist(methods=["POST"])
def update_tag(tag: str, category: str | None = None, color: str | None = None) -> dict:
	"""Set a tag's category and color. Empty values clear them."""
	check_crm_user()
	tag_name = find_tag(normalize_tag(tag))
	if not tag_name:
		frappe.throw(_("Tag {0} not found").format(tag), frappe.DoesNotExistError)
	doc = frappe.get_doc("Tag", tag_name)
	doc.abm_category = clean_option(category, TAG_CATEGORIES, _("category"))
	doc.abm_color = clean_option(color, TAG_COLORS, _("color"))
	doc.save(ignore_permissions=True)
	return tag_row(doc)


# Helpers
# -------


def normalize_tag(tag: str | None) -> str:
	"""Strip and collapse spaces. Commas would split the tag in `_user_tags`, so they are refused."""
	tag = re.sub(r"\s+", " ", tag or "").strip()
	if not tag:
		frappe.throw(_("Tag is required"))
	if "," in tag:
		frappe.throw(_("A tag cannot contain a comma"))
	if len(tag) > 140:
		frappe.throw(_("A tag can be at most 140 characters long"))
	return tag


def find_tag(tag: str) -> str | None:
	"""The existing tag with this name in any letter case."""
	rows = frappe.db.sql("select name from `tabTag` where lower(name) = lower(%s) limit 1", tag)
	return rows[0][0] if rows else None


def ensure_tag(tag: str, category: str | None = None, color: str | None = None) -> str:
	"""Name of the tag, reusing an existing one regardless of case ("lodha" -> "Lodha")."""
	tag = normalize_tag(tag)
	name = find_tag(tag)
	if name:
		if category or color:
			doc = frappe.get_doc("Tag", name)
			if category:
				doc.abm_category = clean_option(category, TAG_CATEGORIES, _("category"))
			if color:
				doc.abm_color = clean_option(color, TAG_COLORS, _("color"))
			doc.save(ignore_permissions=True)
		return name
	frappe.get_doc(
		{
			"doctype": "Tag",
			"name": tag,
			"abm_category": clean_option(category, TAG_CATEGORIES, _("category")),
			"abm_color": clean_option(color, TAG_COLORS, _("color")),
		}
	).insert(ignore_permissions=True)
	return tag


def clean_option(value: str | None, options, label: str) -> str | None:
	value = (value or "").strip()
	if not value:
		return None
	for option in options:
		if option.lower() == value.lower():
			return option
	frappe.throw(_("Unknown tag {0} {1}").format(label, value))


def parse_user_tags(value: str | None) -> list[str]:
	"""Tag names from a `_user_tags` value (comma separated, may start with a comma)."""
	return [t.strip() for t in (value or "").split(",") if t.strip()]


def doc_tags(doctype: str, name: str) -> list[dict]:
	names = parse_user_tags(frappe.db.get_value(doctype, name, "_user_tags"))
	info = tag_info(names)
	return [info.get(n.lower()) or {"name": n, "category": None, "color": None} for n in names]


def tag_info(names) -> dict:
	"""{lowercase name: Tag} for the given tag names, in one query."""
	names = list({n for n in names if n})
	if not names:
		return {}
	rows = frappe.get_all(
		"Tag", filters={"name": ["in", names]}, fields=["name", "abm_category", "abm_color"]
	)
	return {r.name.lower(): tag_row(r) for r in rows}


def tag_row(tag) -> dict:
	return {"name": tag.name, "category": tag.abm_category or None, "color": tag.abm_color or None}


def attach_tags(rows: list[dict]) -> list[dict]:
	"""Replace `_user_tags` on each row with `tags: [Tag]`, looking tags up once for all rows."""
	parsed = [parse_user_tags(row.pop("_user_tags", None)) for row in rows]
	info = tag_info(n for names in parsed for n in names)
	for row, names in zip(rows, parsed, strict=True):
		row["tags"] = [info.get(n.lower()) or {"name": n, "category": None, "color": None} for n in names]
	return rows


def names_with_tag(doctype: str, tag: str) -> list[str]:
	"""Records whose `_user_tags` contain exactly this tag (not just a tag that starts with it)."""
	check_doctype(doctype)
	tag = find_tag(normalize_tag(tag)) or normalize_tag(tag)
	pattern = "%," + tag.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + ",%"
	return frappe.db.sql_list(
		f"select name from `tab{doctype}` where concat(',', ifnull(_user_tags, ''), ',') like %s",
		pattern,
	)


def check_doctype(doctype: str) -> None:
	if doctype not in CRM_DOCTYPES:
		frappe.throw(_("Only leads and deals can be tagged"))


def check_crm_user() -> None:
	if not set(frappe.get_roles()) & set(CRM_ROLES):
		frappe.throw(_("You do not have access to the CRM"), frappe.PermissionError)


# Hooks
# -----


def copy_lead_tags(doc, method=None):
	"""CRM Deal after_insert: a deal created from a lead starts with the lead's tags."""
	if not doc.get("lead"):
		return
	tags = parse_user_tags(frappe.db.get_value("CRM Lead", doc.lead, "_user_tags"))
	if not tags:
		return
	existing = parse_user_tags(frappe.db.get_value("CRM Deal", doc.name, "_user_tags"))
	merged = existing + [t for t in tags if t.lower() not in {e.lower() for e in existing}]
	# DocTags would check write permission on the deal, which the converting user may not have yet
	# (e.g. conversions from automations), so set the column and Tag Links directly.
	frappe.db.set_value("CRM Deal", doc.name, "_user_tags", ",".join(merged), update_modified=False)
	linked = set(
		frappe.get_all(
			"Tag Link", filters={"document_type": "CRM Deal", "document_name": doc.name}, pluck="tag"
		)
	)
	title = doc.get_title() or ""
	for tag in merged:
		if tag in linked:
			continue
		if not frappe.db.exists("Tag", tag):
			frappe.get_doc({"doctype": "Tag", "name": tag}).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "Tag Link",
				"document_type": "CRM Deal",
				"document_name": doc.name,
				"title": title,
				"tag": tag,
			}
		).insert(ignore_permissions=True)
