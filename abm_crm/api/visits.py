"""Site visits (check-ins) made from the mobile app, for the CRM web app and the mobile app.

Visits are ABM Field Visit records linked to a lead or deal. Anyone who can read the lead or deal
can see its visits and their photos, whoever made the visit. The photo is a private file, so it is
served through `visit_photo`, which checks access to the lead or deal instead of the visit.
"""

import mimetypes

import frappe
from frappe import _

CRM_DOCTYPES = ("CRM Lead", "CRM Deal")
VISIT_FIELDS = [
	"name",
	"reference_doctype",
	"reference_docname",
	"latitude",
	"longitude",
	"accuracy",
	"address",
	"notes",
	"photo",
	"visited_by",
	"visited_at",
	"creation",
]


def check_reference(doctype: str, name: str):
	if doctype not in CRM_DOCTYPES:
		frappe.throw(_("Only leads and deals have site visits"))
	frappe.get_doc(doctype, name).check_permission("read")


def photo_url(visit_name: str) -> str:
	return f"/api/method/abm_crm.api.visits.visit_photo?visit={visit_name}"


@frappe.whitelist()
def get_visits(doctype: str, name: str) -> list[dict]:
	"""Visits to a lead or deal, newest first. A deal also shows the visits made while it was a lead."""
	check_reference(doctype, name)
	refs = [[doctype, name]]
	if doctype == "CRM Deal":
		lead = frappe.db.get_value("CRM Deal", name, "lead")
		if lead:
			refs.append(["CRM Lead", lead])

	visits = []
	for ref_doctype, ref_name in refs:
		visits += frappe.get_all(
			"ABM Field Visit",
			filters={"reference_doctype": ref_doctype, "reference_docname": ref_name},
			fields=VISIT_FIELDS,
			order_by="visited_at desc",
			limit=200,
		)

	users = {v.visited_by for v in visits if v.visited_by}
	names = (
		{
			u.name: u
			for u in frappe.get_all(
				"User", filters={"name": ["in", list(users)]}, fields=["name", "full_name", "user_image"]
			)
		}
		if users
		else {}
	)
	for v in visits:
		user = names.get(v.visited_by)
		v["visited_by_name"] = (user and user.full_name) or v.visited_by
		v["visited_by_image"] = user and user.user_image
		v["photo_url"] = photo_url(v.name) if v.photo else None
		v["map_url"] = f"https://maps.google.com/?q={v.latitude},{v.longitude}"
	visits.sort(key=lambda v: v.visited_at or v.creation, reverse=True)
	return visits


@frappe.whitelist()
def visit_photo(visit: str):
	"""The visit's photo, for anyone who can read the visited lead or deal."""
	row = frappe.db.get_value(
		"ABM Field Visit", visit, ["reference_doctype", "reference_docname", "photo"], as_dict=True
	)
	if not row or not row.photo:
		raise frappe.DoesNotExistError(_("No photo for this visit"))
	check_reference(row.reference_doctype, row.reference_docname)

	# only the file uploaded for this visit; never another file whose URL was typed into `photo`
	file_name = frappe.db.get_value(
		"File",
		{"file_url": row.photo, "attached_to_doctype": "ABM Field Visit", "attached_to_name": visit},
		"name",
	)
	if not file_name:
		raise frappe.DoesNotExistError(_("Photo file not found"))
	file = frappe.get_doc("File", file_name)

	frappe.local.response.filename = file.file_name
	frappe.local.response.filecontent = file.get_content()
	frappe.local.response.type = "download"
	frappe.local.response.display_content_as = "inline"
	frappe.local.response.content_type = mimetypes.guess_type(file.file_name)[0] or "image/jpeg"
