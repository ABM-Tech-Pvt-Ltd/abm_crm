import frappe
from frappe import _
from frappe.utils import parse_addr

CRM_DOCTYPES = ("CRM Lead", "CRM Deal")
EMAIL_MAKE_PATH = "frappe.core.doctype.communication.email.make"


@frappe.whitelist()
def get_sender_options() -> list[dict]:
	"""Return the Email Accounts the session user may send CRM emails from.

	Sources, in priority order: ABM Email Sender rules (user, role, everyone), the user's own
	User Emails rows, then the default outgoing account. Only accounts with outgoing enabled
	are returned. The first option flagged `is_default` should be pre-selected.
	"""
	return _get_sender_options(frappe.session.user)


def _get_sender_options(user: str) -> list[dict]:
	settings = frappe.get_single("ABM CRM Settings")
	accounts = {
		a.name: a
		for a in frappe.get_all(
			"Email Account",
			filters={"enable_outgoing": 1, "awaiting_password": 0},
			fields=["name", "email_id", "default_outgoing"],
		)
	}

	options = {}

	def add(account_name, is_default=False):
		account = accounts.get(account_name)
		if not account or not account.email_id:
			return
		if account_name in options:
			options[account_name]["is_default"] |= is_default
			return
		options[account_name] = {
			"label": f"{account.name} <{account.email_id}>",
			"value": account.email_id,
			"email_account": account.name,
			"is_default": is_default,
		}

	roles = frappe.get_roles(user)
	rules = frappe.get_all(
		"ABM Email Sender",
		filters={"enabled": 1},
		fields=["email_account", "applies_to", "user", "role", "is_default"],
		order_by="is_default desc, creation asc",
	)
	for rule in rules:
		if (
			rule.applies_to == "Everyone"
			or (rule.applies_to == "User" and rule.user == user)
			or (rule.applies_to == "Role" and rule.role in roles)
		):
			add(rule.email_account, bool(rule.is_default))

	if settings.include_user_email_accounts:
		for row in frappe.get_all(
			"User Email",
			filters={"parent": user, "parenttype": "User"},
			fields=["email_account"],
			order_by="idx asc",
		):
			add(row.email_account)

	if settings.include_default_outgoing:
		for account in accounts.values():
			if account.default_outgoing:
				add(account.name)

	result = list(options.values())
	if result and not any(o["is_default"] for o in result):
		own = next((o for o in result if o["value"] == user), None)
		(own or result[0])["is_default"] = True
	return result


def validate_outgoing_sender(doc, method=None):
	"""Communication.before_insert: pin the Email Account for CRM emails sent from the composer.

	Frappe picks the SMTP account by matching the sender address, and falls back to other
	accounts when nothing matches. Setting `email_account` explicitly makes the choice
	deterministic. When "Enforce Sender Rules" is on, senders the user may not use are rejected.
	"""
	if not _is_crm_composer_email(doc):
		return

	sender = parse_addr(doc.sender or "")[1]
	options = _get_sender_options(frappe.session.user)
	match = next((o for o in options if o["value"] == sender), None)

	if match:
		doc.email_account = match["email_account"]
		return

	if frappe.session.user == "Administrator" or "System Manager" in frappe.get_roles():
		return

	if frappe.db.get_single_value("ABM CRM Settings", "enforce_sender_rules"):
		frappe.throw(
			_("You are not allowed to send emails from {0}").format(sender or _("this address")),
			frappe.PermissionError,
		)


def _is_crm_composer_email(doc) -> bool:
	if doc.communication_medium != "Email" or doc.sent_or_received != "Sent":
		return False
	if doc.reference_doctype not in CRM_DOCTYPES:
		return False
	# only emails sent by a user from the composer; skip automations, notifications and imports
	if frappe.flags.abm_crm_composer:
		# the mobile app's composer (abm_crm.api.mobile.send_email)
		return True
	request = getattr(frappe.local, "request", None)
	return bool(request and request.path.rstrip("/").endswith(EMAIL_MAKE_PATH))


# Settings page (CRM Settings > Email > Senders)
# ----------------------------------------------

MANAGER_ROLES = ("System Manager", "Sales Manager")
SENDER_SETTINGS = ("enforce_sender_rules", "include_user_email_accounts", "include_default_outgoing")
CRM_ROLES = ("Sales User", "Sales Manager", "System Manager")


@frappe.whitelist()
def get_sender_setup() -> dict:
	"""Everything the Senders settings page needs, in one call."""
	frappe.only_for(MANAGER_ROLES)
	settings = frappe.get_single("ABM CRM Settings")
	return {
		"accounts": frappe.get_all(
			"Email Account",
			filters={"enable_outgoing": 1},
			fields=["name", "email_id", "default_outgoing", "awaiting_password"],
			order_by="name asc",
		),
		"users": frappe.get_all(
			"User",
			filters={"enabled": 1, "user_type": "System User", "name": ["not in", ["Administrator", "Guest"]]},
			fields=["name", "full_name"],
			order_by="full_name asc",
		),
		"roles": list(CRM_ROLES),
		"rules": frappe.get_all(
			"ABM Email Sender",
			fields=["name", "enabled", "email_account", "email_id", "applies_to", "user", "role", "is_default"],
			order_by="creation asc",
		),
		"settings": {key: settings.get(key) for key in SENDER_SETTINGS},
	}


@frappe.whitelist()
def save_sender_rule(rule: dict) -> str:
	frappe.only_for(MANAGER_ROLES)
	rule = frappe.parse_json(rule)
	fields = {k: rule.get(k) for k in ("enabled", "email_account", "applies_to", "user", "role", "is_default")}
	if rule.get("name"):
		doc = frappe.get_doc("ABM Email Sender", rule["name"])
		doc.update(fields)
		doc.save()
	else:
		doc = frappe.get_doc({"doctype": "ABM Email Sender", **fields}).insert()
	return doc.name


@frappe.whitelist()
def delete_sender_rule(name: str) -> None:
	frappe.only_for(MANAGER_ROLES)
	frappe.delete_doc("ABM Email Sender", name)


@frappe.whitelist()
def update_sender_setting(field: str, value: int) -> None:
	frappe.only_for(MANAGER_ROLES)
	if field not in SENDER_SETTINGS:
		frappe.throw(_("Unknown setting {0}").format(field))
	frappe.db.set_single_value("ABM CRM Settings", field, 1 if frappe.utils.cint(value) else 0)
