"""Replacement for crm.api.settings.create_email_account (see override_whitelisted_methods in hooks.py).

crm's version has two problems:
- It always logs in over IMAP, even when incoming is turned off, so outgoing-only accounts and
  accounts with IMAP disabled at the provider fail with "invalid credentials".
- The UI replaces every server error with "invalid credentials", hiding the real reason.

This version lets Email Account.validate() test only what is enabled (IMAP for incoming, SMTP for
outgoing) and returns an error message that says what went wrong and how to fix it.
"""

import frappe
from frappe import _
from frappe.utils.messages import clear_last_message

from crm.api.settings import email_service_config

APP_PASSWORD_HELP = {
	"GMail": (
		"Gmail needs an App Password, not your normal password. Turn on 2-Step Verification, then "
		"create one at https://myaccount.google.com/apppasswords. For incoming email, also enable "
		"IMAP in Gmail settings. Google Workspace admins can block app passwords."
	),
	"Outlook": (
		"Microsoft has turned off password sign-in (basic auth) for most Outlook and Office 365 "
		"mailboxes. Use an App Password if your account still allows it, otherwise connect the "
		"account with OAuth from desk (Email Account > Authentication: OAuth)."
	),
	"Yahoo": "Yahoo needs an App Password: Account Security > Generate app password.",
	"Yandex": "Yandex needs an App Password: https://id.yandex.com/security/app-passwords",
	"Sendgrid": "Use a SendGrid API key with Mail Send permission as the password.",
}

AUTH_ERROR_HINTS = (
	"authenticat",
	"credential",
	"password",
	"username",
	"login",
	"535",
	"534",
	"invalid",
)


@frappe.whitelist()
def create_email_account(data: dict) -> None:
	# Email Accounts hold mailbox passwords; Frappe only lets System Managers create them
	if "System Manager" not in frappe.get_roles():
		frappe.throw(
			_("Only a System Manager can add email accounts. Ask your administrator to add it."),
			frappe.PermissionError,
		)
	data = frappe._dict(frappe.parse_json(data))

	service = data.get("service")
	service_config = email_service_config.get(service)
	if not service_config:
		frappe.throw(_("Email service {0} is not supported").format(service))

	if not data.get("enable_incoming") and not data.get("enable_outgoing"):
		frappe.throw(_("Turn on incoming, outgoing or both"))

	email_id = (data.get("email_id") or "").strip().lower()
	email_doc = frappe.get_doc(
		{
			"doctype": "Email Account",
			"email_id": email_id,
			"email_account_name": (data.get("email_account_name") or email_id).strip(),
			"service": service,
			"enable_incoming": data.get("enable_incoming"),
			"enable_outgoing": data.get("enable_outgoing"),
			"default_incoming": data.get("default_incoming"),
			"default_outgoing": data.get("default_outgoing"),
			"email_sync_option": "ALL",
			"initial_sync_count": 100,
			"create_contact": 1,
			"track_email_status": 1,
			"use_tls": 1,
			"use_imap": 1,
			"smtp_port": 587,
			**service_config,
		}
	)
	if data.get("create_lead_from_incoming_email") is not None:
		email_doc.set("create_lead_from_incoming_email", data.get("create_lead_from_incoming_email"))

	if service == "Frappe Mail":
		email_doc.api_key = data.get("api_key")
		email_doc.api_secret = data.get("api_secret")
		email_doc.frappe_mail_site = data.get("frappe_mail_site")
		email_doc.append_to = "CRM Lead"
	else:
		email_doc.password = clean_password(service, data.get("password"))
		if email_doc.enable_incoming:
			email_doc.append("imap_folder", {"append_to": "CRM Lead", "folder_name": "INBOX"})

	try:
		# validate() logs in to IMAP (if incoming) and SMTP (if outgoing) with these credentials
		email_doc.insert()
	except Exception as e:
		clear_last_message()
		frappe.throw(explain_error(service, e), title=_("Could not connect email account"))


def clean_password(service: str, password: str | None) -> str | None:
	if not password:
		return password
	password = password.strip()
	if service in ("GMail", "Yahoo"):
		# app passwords are shown in groups ("abcd efgh ijkl mnop"); the spaces are not part of it
		password = password.replace(" ", "")
	return password


def explain_error(service: str, error: Exception) -> str:
	message = frappe.utils.cstr(error).strip() or error.__class__.__name__
	message = frappe.utils.strip_html(message)
	if any(hint in message.lower() for hint in AUTH_ERROR_HINTS) and service in APP_PASSWORD_HELP:
		return _("{0}. {1}").format(message.rstrip("."), _(APP_PASSWORD_HELP[service]))
	return message


def clean_account_password(doc, method=None):
	"""Email Account.before_validate: drop the spaces Gmail/Yahoo show inside app passwords.

	Runs before the connection test in validate(), for accounts saved from CRM or desk.
	"""
	if doc.password and not doc.is_dummy_password(doc.password):
		doc.password = clean_password(doc.service, doc.password)


def sync_lead_creation(doc, method=None):
	"""Make "Create lead from incoming email" the only switch for leads from email.

	Frappe CRM sets the account's "Append To" (and the INBOX folder's) to CRM Lead when it creates
	an email account. Frappe's email receiver then creates a CRM Lead for every incoming email that
	isn't a reply to a known record, whatever the CRM checkbox says. The checkbox only controls
	CRM's own hook (crm.utils.create_lead_from_incoming_email), which creates the lead by itself
	when it is on. So with the checkbox off, CRM Lead is removed from "Append To"; emails still
	arrive and replies still link to their lead or deal.
	"""
	if not doc.meta.has_field("create_lead_from_incoming_email") or doc.create_lead_from_incoming_email:
		return
	if doc.append_to == "CRM Lead":
		doc.append_to = None
	for row in doc.get("imap_folder") or []:
		if row.append_to == "CRM Lead":
			row.append_to = None
