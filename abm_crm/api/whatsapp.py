"""Wrappers for crm's WhatsApp send methods (see override_whitelisted_methods in hooks.py).

WhatsApp needs the full international number. Leads often store local numbers ("9876543210"), which
Meta reads as "+98 76543210" (an Iranian number), so sends fail or go to the wrong person. These
wrappers convert the recipient to international format using the default region in ABM CRM Settings,
then call crm's original method. Meta's error codes are also turned into messages that say what to do.
"""

import frappe
import phonenumbers
from frappe import _
from frappe.utils.messages import clear_messages

from crm.api import whatsapp as crm_whatsapp

META_ERROR_HELP = {
	"131030": (
		"This number is not on the allowed list of Meta's test number. In your Meta app go to "
		"WhatsApp > API Setup, add {0} under 'To', and verify it with the code WhatsApp sends."
	),
	"131047": (
		"More than 24 hours have passed since this person last messaged you, so WhatsApp only allows "
		"a template message. Send a template instead."
	),
	"132000": "The number of variables sent does not match the template.",
	"131026": "WhatsApp could not deliver to {0}. The number may not be on WhatsApp.",
	"190": "The WhatsApp access token has expired. Generate a new token and update the WhatsApp Account.",
}


def to_whatsapp_number(number: str | None) -> str | None:
	"""Return the number as international digits without "+" (e.g. 919876543210)."""
	if not number:
		return number
	region = (frappe.db.get_single_value("ABM CRM Settings", "default_phone_region") or "IN").upper()
	raw = number.strip()
	if raw.startswith("00"):
		raw = "+" + raw[2:]
	try:
		parsed = phonenumbers.parse(raw, region)
	except phonenumbers.NumberParseException:
		frappe.throw(_("{0} is not a valid phone number").format(number))
	if not phonenumbers.is_valid_number(parsed):
		frappe.throw(
			_("{0} is not a valid phone number for WhatsApp. Save it with the country code, e.g. +91 98765 43210.").format(
				number
			)
		)
	return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164).lstrip("+")


def explain_meta_error(fn, to: str):
	try:
		return fn()
	except frappe.ValidationError as e:
		message = frappe.utils.cstr(e)
		for code, help_text in META_ERROR_HELP.items():
			if f"(#{code})" in message or f"code {code}" in message:
				clear_messages()
				frappe.throw(_(help_text).format(f"+{to}"), title=_("WhatsApp message not sent"))
		raise


@frappe.whitelist()
def create_whatsapp_message(
	reference_doctype: str,
	reference_name: str,
	to: str,
	message: str = "",
	attach: str = "",
	reply_to: str = "",
	content_type: str = "text",
):
	to = to_whatsapp_number(to)
	return explain_meta_error(
		lambda: crm_whatsapp.create_whatsapp_message(
			reference_doctype=reference_doctype,
			reference_name=reference_name,
			message=message,
			to=to,
			attach=attach,
			reply_to=reply_to,
			content_type=content_type,
		),
		to,
	)


@frappe.whitelist()
def send_whatsapp_template(reference_doctype: str, reference_name: str, template: str, to: str):
	to = to_whatsapp_number(to)
	return explain_meta_error(
		lambda: crm_whatsapp.send_whatsapp_template(
			reference_doctype=reference_doctype, reference_name=reference_name, template=template, to=to
		),
		to,
	)
