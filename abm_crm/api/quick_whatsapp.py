"""Click to Chat WhatsApp: free, no Meta account needed.

The CRM opens the rep's own WhatsApp (phone app or WhatsApp Web) at wa.me/<number>?text=<message>,
with the message typed in from a predefined template. The rep presses send in WhatsApp. Each message
opened this way is logged on the lead or deal (ABM WhatsApp Log + a comment in the activity feed).
Replies stay in the rep's WhatsApp; this mode has no inbox.
"""

import frappe
import phonenumbers
from frappe import _
from frappe.utils import escape_html

from abm_crm.api.whatsapp import to_whatsapp_number

CRM_DOCTYPES = ("CRM Lead", "CRM Deal")
MANAGER_ROLES = ("System Manager", "Sales Manager")


@frappe.whitelist()
def get_whatsapp_mode() -> dict:
	mode = frappe.db.get_single_value("ABM CRM Settings", "whatsapp_mode") or "Click to Chat"
	cloud_ready = False
	if mode == "Cloud API":
		from crm.api.whatsapp import is_whatsapp_enabled

		cloud_ready = bool(is_whatsapp_enabled())
	region = (frappe.db.get_single_value("ABM CRM Settings", "default_phone_region") or "IN").upper()
	return {
		"mode": mode,
		"cloud_enabled": cloud_ready,
		# used by list cards to build wa.me links without a request per row
		"calling_code": str(phonenumbers.country_code_for_region(region) or ""),
	}


@frappe.whitelist()
def get_quick_whatsapp(doctype: str, name: str) -> dict:
	"""Number, rendered templates and recent history for the WhatsApp tab of a lead or deal."""
	doc = get_crm_doc(doctype, name)
	phone = doc.get("mobile_no") or doc.get("phone")

	wa_number, error = None, None
	if phone:
		try:
			wa_number = to_whatsapp_number(phone)
		except frappe.ValidationError as e:
			frappe.clear_messages()
			error = frappe.utils.cstr(e)
	else:
		error = _("Add a mobile number to send WhatsApp messages.")

	return {
		"phone": phone,
		"wa_number": wa_number,
		"error": error,
		"templates": render_templates(doc),
		"history": frappe.get_all(
			"ABM WhatsApp Log",
			filters={"reference_doctype": doctype, "reference_name": name},
			fields=["name", "message", "template", "sent_by", "creation"],
			order_by="creation desc",
			limit=20,
		),
	}


@frappe.whitelist()
def get_contact_links(doctype: str, name: str) -> dict:
	"""tel: and WhatsApp numbers for the call / WhatsApp buttons on a lead or deal."""
	doc = get_crm_doc(doctype, name)
	phone = doc.get("mobile_no") or doc.get("phone")
	wa_number = None
	if phone:
		try:
			wa_number = to_whatsapp_number(phone)
		except frappe.ValidationError:
			frappe.clear_messages()
	return {
		"phone": phone,
		"tel": f"+{wa_number}" if wa_number else phone,
		"wa_number": wa_number,
		"email": doc.get("email"),
	}


@frappe.whitelist()
def log_quick_whatsapp(doctype: str, name: str, message: str, template: str | None = None) -> str:
	"""Record a message the rep opened in WhatsApp. Called right after the wa.me link opens."""
	doc = get_crm_doc(doctype, name)
	phone = doc.get("mobile_no") or doc.get("phone")
	log = frappe.get_doc(
		{
			"doctype": "ABM WhatsApp Log",
			"reference_doctype": doctype,
			"reference_name": name,
			"phone": phone,
			"template": template if template and frappe.db.exists("ABM WhatsApp Template", template) else None,
			"message": message,
			"sent_by": frappe.session.user,
		}
	).insert(ignore_permissions=True)

	# show up in the lead/deal activity feed
	frappe.get_doc(
		{
			"doctype": "Comment",
			"comment_type": "Comment",
			"reference_doctype": doctype,
			"reference_name": name,
			"content": "<p><b>{}</b></p><p>{}</p>".format(
				_("WhatsApp message opened"), escape_html(message).replace("\n", "<br>")
			),
		}
	).insert(ignore_permissions=True)
	return log.name


def get_crm_doc(doctype: str, name: str):
	if doctype not in CRM_DOCTYPES:
		frappe.throw(_("WhatsApp is only available on leads and deals"))
	doc = frappe.get_doc(doctype, name)
	doc.check_permission("read")
	return doc


def render_templates(doc) -> list[dict]:
	templates = frappe.get_all(
		"ABM WhatsApp Template",
		filters={"enabled": 1, "applies_to": ["in", ["Both", doc.doctype]]},
		fields=["name", "message"],
		order_by="sort_order asc, creation asc",
	)
	context = get_template_context(doc)
	result = []
	for t in templates:
		try:
			text = frappe.render_template(t.message, context)
		except Exception:
			text = t.message
		result.append({"name": t.name, "message": text.strip()})
	return result


def get_template_context(doc) -> dict:
	user = frappe.db.get_value(
		"User", frappe.session.user, ["full_name", "first_name", "email", "mobile_no"], as_dict=True
	)
	brand = frappe.db.get_single_value("FCRM Settings", "brand_name") or ""
	return {"doc": doc.as_dict(), "user": user or {}, "brand": brand}


# Settings page (CRM Settings > Messaging > WhatsApp)
# --------------------------------------------------


@frappe.whitelist()
def get_template_setup() -> dict:
	frappe.only_for(MANAGER_ROLES)
	return {
		"mode": frappe.db.get_single_value("ABM CRM Settings", "whatsapp_mode") or "Click to Chat",
		"cloud_installed": "frappe_whatsapp" in frappe.get_installed_apps(),
		"templates": frappe.get_all(
			"ABM WhatsApp Template",
			fields=["name", "template_name", "enabled", "applies_to", "message", "sort_order"],
			order_by="sort_order asc, creation asc",
		),
	}


@frappe.whitelist()
def set_whatsapp_mode(mode: str) -> None:
	frappe.only_for(MANAGER_ROLES)
	if mode not in ("Click to Chat", "Cloud API"):
		frappe.throw(_("Unknown WhatsApp mode {0}").format(mode))
	frappe.db.set_single_value("ABM CRM Settings", "whatsapp_mode", mode)


@frappe.whitelist()
def save_template(template: dict) -> str:
	frappe.only_for(MANAGER_ROLES)
	template = frappe._dict(frappe.parse_json(template))
	fields = {
		k: template.get(k)
		for k in ("template_name", "enabled", "applies_to", "message", "sort_order")
		if k in template
	}
	if template.get("name"):
		name = template.name
		new_name = (template.get("template_name") or "").strip()
		if new_name and new_name != name:
			name = frappe.rename_doc("ABM WhatsApp Template", name, new_name)
		doc = frappe.get_doc("ABM WhatsApp Template", name)
		doc.update(fields)
		doc.save()
	else:
		doc = frappe.get_doc({"doctype": "ABM WhatsApp Template", **fields}).insert()
	return doc.name


@frappe.whitelist()
def delete_template(name: str) -> None:
	frappe.only_for(MANAGER_ROLES)
	frappe.delete_doc("ABM WhatsApp Template", name)
