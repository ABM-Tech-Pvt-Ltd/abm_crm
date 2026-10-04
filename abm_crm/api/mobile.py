"""API for the ABM CRM Android app. The contract is in docs/mobile-api.md.

The app signs in once with `login`, then sends `Authorization: token <api_key>:<api_secret>` on every
call, so normal Frappe permissions apply to the rep.
"""

import datetime
import os
import re
from functools import wraps

import frappe
import phonenumbers
from crm.integrations.api import get_contact_lead_or_deal_from_number
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import (
	add_days,
	cint,
	convert_utc_to_system_timezone,
	escape_html,
	flt,
	get_datetime,
	getdate,
	now_datetime,
	nowdate,
	validate_phone_number,
)
from frappe.utils.password import set_encrypted_password

from abm_crm.api.tags import attach_tags, doc_tags, names_with_tag
from abm_crm.setup.install import CALL_OUTCOMES

CRM_DOCTYPES = ("CRM Lead", "CRM Deal")
CRM_ROLES = ("Sales User", "Sales Manager", "System Manager")
MANAGER_ROLES = ("System Manager", "Sales Manager")
CLOSED_TASK_STATUSES = ("Done", "Canceled")
CLOSED_STATUS_TYPES = ("Won", "Lost")

LEAD_FIELDS = [
	"name",
	"lead_name",
	"first_name",
	"organization",
	"status",
	"mobile_no",
	"phone",
	"email",
	"lead_owner",
	"source",
	"abm_campaign",
	"modified",
	"creation",
]
DEAL_FIELDS = [
	"name",
	"organization",
	"lead_name",
	"status",
	"deal_value",
	"currency",
	"mobile_no",
	"email",
	"deal_owner",
	"modified",
	"creation",
]
DETAIL_FIELDS = [
	"territory",
	"industry",
	"website",
	"job_title",
	"annual_revenue",
	"lost_reason",
	"abm_adset",
	"abm_ad",
	"abm_platform",
]
SEARCH_FIELDS = ("lead_name", "organization", "mobile_no", "email")
ORDER_FIELDS = ("modified", "creation", "lead_name", "organization", "status", "deal_value")
TASK_FIELDS = [
	"name",
	"title",
	"description",
	"status",
	"priority",
	"due_date",
	"assigned_to",
	"reference_doctype",
	"reference_docname",
]
CALL_FIELDS = [
	"name",
	"type",
	"status",
	"from",
	"to",
	"duration",
	"start_time",
	"end_time",
	"caller",
	"receiver",
	"recording_url",
	"abm_outcome",
	"note",
	"reference_doctype",
	"reference_docname",
	"telephony_medium",
]
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
]
AUDIO_EXTENSIONS = (
	"m4a",
	"mp3",
	"amr",
	"awb",
	"aac",
	"wav",
	"ogg",
	"oga",
	"opus",
	"3gp",
	"3gpp",
	"flac",
	"webm",
)
IMAGE_EXTENSIONS = ("jpg", "jpeg", "png", "webp", "heic", "heif")
MAX_SYNC_BATCH = 500


def plain(value):
	"""Datetimes as `YYYY-MM-DD HH:MM:SS` (no microseconds), recursively."""
	if isinstance(value, datetime.datetime):
		return value.strftime("%Y-%m-%d %H:%M:%S")
	if isinstance(value, datetime.date):
		return value.isoformat()
	if isinstance(value, dict):
		return {k: plain(v) for k, v in value.items()}
	if isinstance(value, list | tuple):
		return [plain(v) for v in value]
	return value


def formatted(fn):
	@wraps(fn)
	def wrapper(*args, **kwargs):
		return plain(fn(*args, **kwargs))

	return wrapper


# Auth and bootstrap
# ------------------


@frappe.whitelist(allow_guest=True, xss_safe=True, methods=["POST"])
@rate_limit(limit=10, seconds=600)
def login(usr: str, pwd: str) -> dict:
	"""Check the password and return the user's API key and secret. Opens no session."""
	from frappe.auth import LoginManager, validate_ip_address
	from frappe.twofactor import should_run_2fa

	# LoginManager() would start a session (and set a cookie); only its authenticate() is needed,
	# which handles disabled users and the failed-login lockout
	manager = LoginManager.__new__(LoginManager)
	manager.user = None
	manager.authenticate(usr, pwd)
	user = manager.user

	if should_run_2fa(user):
		frappe.throw(
			_("Two-factor authentication is on for this user. The mobile app does not support it yet."),
			frappe.AuthenticationError,
		)
	validate_ip_address(user)

	roles = [r for r in frappe.get_roles(user) if r in CRM_ROLES]
	if not roles:
		frappe.throw(_("You do not have access to the CRM"), frappe.PermissionError)

	doc = frappe.get_doc("User", user)
	api_key = doc.api_key
	api_secret = doc.get_password("api_secret", raise_exception=False) if api_key else None
	if not (api_key and api_secret):
		api_key = api_key or frappe.generate_hash(length=15)
		api_secret = frappe.generate_hash(length=15)
		frappe.db.set_value("User", user, "api_key", api_key, update_modified=False)
		set_encrypted_password("User", user, api_secret, "api_secret")

	return {
		"api_key": api_key,
		"api_secret": api_secret,
		"user": user,
		"full_name": doc.full_name,
		"user_image": doc.user_image,
		"roles": roles,
		"is_manager": is_manager(user),
	}


@frappe.whitelist(allow_guest=True)
@rate_limit(limit=60, seconds=600)
def get_brand() -> dict:
	"""CRM brand (FCRM Settings) for the app's sign-in screen and header. Public: name and logo only.

	The logo is returned inline as a data URI because it is often a private file.
	"""
	settings = frappe.get_single("FCRM Settings")
	return {"name": settings.brand_name or "CRM", "logo": file_as_data_uri(settings.brand_logo)}


def file_as_data_uri(file_url: str | None) -> str | None:
	if not file_url:
		return None
	if file_url.startswith("http"):
		return file_url
	try:
		import base64
		import mimetypes

		file = frappe.get_doc("File", {"file_url": file_url})
		content = file.get_content()
		if isinstance(content, str):
			content = content.encode()
		if len(content) > 300 * 1024:  # keep the response small; big logos are served by URL
			return file_url if not file.is_private else None
		mime = mimetypes.guess_type(file.file_name or file_url)[0] or "image/png"
		return f"data:{mime};base64,{base64.b64encode(content).decode()}"
	except Exception:
		return None


@frappe.whitelist(methods=["POST"])
def change_password(old_password: str, new_password: str) -> dict:
	"""Change the session user's password. API keys stay valid, so the app stays signed in."""
	from frappe.core.doctype.user.user import test_password_strength
	from frappe.utils.password import check_password, update_password

	user = frappe.session.user
	if user == "Guest":
		raise frappe.PermissionError
	try:
		check_password(user, old_password, delete_tracker_cache=False)
	except frappe.AuthenticationError:
		frappe.throw(_("Your current password is not correct"), frappe.AuthenticationError)
	if old_password == new_password:
		frappe.throw(_("The new password must be different from the current one"))
	strength = test_password_strength(new_password, user_data=(user,)) or {}
	feedback = strength.get("feedback") or {}
	if feedback and not feedback.get("password_policy_validation_passed", True):
		frappe.throw(feedback.get("warning") or _("Password is too weak. Use at least 8 characters with letters and numbers."))
	if len(new_password) < 8:
		frappe.throw(_("Use at least 8 characters"))
	update_password(user, new_password)
	return {"ok": True}


@frappe.whitelist(methods=["POST"])
def logout(token: str | None = None) -> None:
	"""New API secret: every device using the old one is signed out, so their pushes stop too.

	Every device of the user is disabled (they are all signed out); `token` is accepted so the app
	can name its own device. Signing in again and calling `register_device` re-enables a device.
	"""
	if frappe.session.user == "Guest":
		raise frappe.PermissionError
	set_encrypted_password("User", frappe.session.user, frappe.generate_hash(length=15), "api_secret")
	disable_devices(frappe.session.user, token)


@frappe.whitelist(methods=["POST"])
def register_device(
	token: str,
	platform: str = "android",
	device_name: str | None = None,
	app_version: str | None = None,
) -> dict:
	"""Save the phone's FCM token for the session user. A token another user had moves to this user."""
	user = frappe.session.user
	if user == "Guest":
		raise frappe.PermissionError
	token = (token or "").strip()
	if not token:
		frappe.throw(_("token is required"))
	platform = (platform or "android").strip().lower()
	if platform not in ("android", "ios"):
		frappe.throw(_("platform must be android or ios"))
	values = {
		"user": user,
		"platform": platform,
		"device_name": (device_name or "").strip()[:140] or None,
		"app_version": (app_version or "").strip()[:140] or None,
		"last_seen": now_datetime(),
		"enabled": 1,
	}
	name = frappe.db.get_value("ABM Mobile Device", {"token": token})
	if name:
		device = frappe.get_doc("ABM Mobile Device", name)
		device.update(values)
		device.save(ignore_permissions=True)
	else:
		device = frappe.get_doc({"doctype": "ABM Mobile Device", "token": token, **values}).insert(
			ignore_permissions=True
		)
	return {"name": device.name, "platform": device.platform, "enabled": device.enabled}


@frappe.whitelist(methods=["POST"])
def unregister_device(token: str) -> None:
	"""Forget the token, if it belongs to the session user."""
	if frappe.session.user == "Guest":
		raise frappe.PermissionError
	filters = {"token": (token or "").strip(), "user": frappe.session.user}
	for name in frappe.get_all("ABM Mobile Device", filters=filters, pluck="name"):
		frappe.delete_doc("ABM Mobile Device", name, ignore_permissions=True)


def disable_devices(user: str, token: str | None = None) -> None:
	filters = {"user": user, "enabled": 1}
	names = set(frappe.get_all("ABM Mobile Device", filters=filters, pluck="name"))
	if token:
		names.update(
			frappe.get_all("ABM Mobile Device", filters={"user": user, "token": token.strip()}, pluck="name")
		)
	for name in names:
		frappe.db.set_value("ABM Mobile Device", name, "enabled", 0, update_modified=False)


@frappe.whitelist(methods=["POST"])
def set_my_mobile(mobile_no: str) -> dict:
	"""Save the rep's own phone number. Call sync needs it as the other side of each call."""
	if frappe.session.user == "Guest":
		raise frappe.PermissionError
	from abm_crm.api.whatsapp import to_whatsapp_number

	number = "+" + to_whatsapp_number(mobile_no)  # throws a readable error for invalid numbers
	frappe.db.set_value("User", frappe.session.user, "mobile_no", number)
	return {"mobile_no": number}


@frappe.whitelist()
@formatted
def bootstrap() -> dict:
	"""Everything the app caches after sign-in."""
	user = frappe.session.user
	region = (frappe.db.get_single_value("ABM CRM Settings", "default_phone_region") or "IN").upper()
	brand = frappe.db.get_value("FCRM Settings", None, ["brand_name", "brand_logo"], as_dict=True) or {}
	return {
		"user": frappe.db.get_value(
			"User", user, ["name", "full_name", "user_image", "mobile_no"], as_dict=True
		),
		"is_manager": is_manager(),
		"lead_statuses": get_statuses("CRM Lead Status"),
		"deal_statuses": get_statuses("CRM Deal Status"),
		"lead_sources": frappe.get_all("CRM Lead Source", pluck="name", order_by="name asc"),
		"users": crm_users(),
		"settings": {
			"call_sync_scope": call_sync_scope(),
			"upload_recordings": recordings_enabled(),
			"calling_code": str(phonenumbers.country_code_for_region(region) or ""),
			"whatsapp_mode": frappe.db.get_single_value("ABM CRM Settings", "whatsapp_mode")
			or "Click to Chat",
		},
		"brand": {"name": brand.get("brand_name") or "CRM", "logo": file_as_data_uri(brand.get("brand_logo"))},
	}


# Home
# ----


@frappe.whitelist()
@formatted
def get_home() -> dict:
	user = frappe.session.user
	today_start, today_end = day_range()
	open_statuses = statuses_of_type("CRM Lead Status", ("Open",))
	return {
		"tasks_today": get_tasks("today", 0, 50)[0],
		"tasks_overdue": get_tasks("overdue", 0, 50)[0],
		"new_leads": attach_tags(
			frappe.get_list(
				"CRM Lead",
				fields=[*LEAD_FIELDS, "_user_tags"],
				filters=[["converted", "=", 0], ["status", "in", open_statuses or [""]]],
				or_filters=[["lead_owner", "=", user], ["_assign", "like", f'%"{user}"%']],
				order_by="creation desc",
				limit=10,
			)
		),
		"calls_today": call_stats(today_start, today_end, user),
		"counts": {
			"my_open_leads": frappe.db.count(
				"CRM Lead",
				{
					"lead_owner": user,
					"converted": 0,
					"status": ["not in", closed_statuses("CRM Lead Status")],
				},
			),
			"my_open_deals": frappe.db.count(
				"CRM Deal", {"deal_owner": user, "status": ["not in", closed_statuses("CRM Deal Status")]}
			),
		},
	}


# Leads and deals
# ---------------


@frappe.whitelist()
@formatted
def list_leads(
	search: str | None = None,
	status: str | None = None,
	owner: str | None = None,
	start: int = 0,
	page_length: int = 20,
	order_by: str = "modified desc",
	tag: str | None = None,
) -> dict:
	return list_records("CRM Lead", search, status, owner, start, page_length, order_by, tag)


@frappe.whitelist()
@formatted
def list_deals(
	search: str | None = None,
	status: str | None = None,
	owner: str | None = None,
	start: int = 0,
	page_length: int = 20,
	order_by: str = "modified desc",
	tag: str | None = None,
) -> dict:
	return list_records("CRM Deal", search, status, owner, start, page_length, order_by, tag)


def list_records(doctype, search, status, owner, start, page_length, order_by, tag=None) -> dict:
	is_lead = doctype == "CRM Lead"
	filters = []
	if is_lead:
		# converted leads live on as deals, like the CRM's own leads list
		filters.append(["converted", "=", 0])
	if status:
		filters.append(["status", "=", status])
	if owner:
		filters.append(
			["lead_owner" if is_lead else "deal_owner", "=", frappe.session.user if owner == "me" else owner]
		)
	if tag and tag.strip():
		# exact tag match (a plain LIKE on _user_tags would also match "Lodha Park" for "Lodha")
		filters.append(["name", "in", names_with_tag(doctype, tag) or [""]])
	search = (search or "").strip()
	or_filters = [[f, "like", f"%{search}%"] for f in SEARCH_FIELDS] if search else None
	result = paged(
		frappe.get_list,
		doctype,
		fields=[*(LEAD_FIELDS if is_lead else DEAL_FIELDS), "_user_tags"],
		filters=filters,
		or_filters=or_filters,
		order_by=safe_order_by(order_by),
		start=start,
		page_length=page_length,
	)
	attach_tags(result["data"])
	return result


@frappe.whitelist()
@formatted
def get_record(doctype: str, name: str) -> dict:
	"""A lead or deal with its notes, tasks, calls, comments, visits and WhatsApp history."""
	doc = get_crm_doc(doctype, name)
	ref = {"reference_doctype": doctype, "reference_docname": name}
	row = record_row(doc)
	row.update({f: doc.get(f) for f in DETAIL_FIELDS})

	linked_calls = frappe.get_all(
		"Dynamic Link",
		filters={"parenttype": "CRM Call Log", "link_doctype": doctype, "link_name": name},
		pluck="parent",
	)
	call_filters = {"reference_docname": name}
	if linked_calls:
		call_filters["name"] = ["in", linked_calls]

	# every field of the edit form (get_form), so the app can fill it
	for field in form_fields(doctype):
		row.setdefault(field["fieldname"], doc.get(field["fieldname"]))

	return {
		"doc": row,
		"assignees": assignees(doc),
		"notes": frappe.get_all(
			"FCRM Note",
			filters=ref,
			fields=["name", "title", "content", "owner", "creation"],
			order_by="creation desc",
			limit=50,
		),
		"tasks": frappe.get_all(
			"CRM Task", filters=ref, fields=TASK_FIELDS, order_by="creation desc", limit=50
		),
		"calls": [
			call_row(c)
			for c in frappe.get_all(
				"CRM Call Log",
				or_filters=call_filters,
				fields=CALL_FIELDS,
				order_by="creation desc",
				limit=50,
			)
		],
		"comments": frappe.get_all(
			"Comment",
			filters={"reference_doctype": doctype, "reference_name": name, "comment_type": "Comment"},
			fields=["name", "content", "owner", "creation"],
			order_by="creation desc",
			limit=50,
		),
		"visits": frappe.get_all(
			"ABM Field Visit", filters=ref, fields=VISIT_FIELDS, order_by="creation desc", limit=50
		),
		"whatsapp": frappe.get_all(
			"ABM WhatsApp Log",
			filters={"reference_doctype": doctype, "reference_name": name},
			fields=["name", "message", "sent_by", "creation"],
			order_by="creation desc",
			limit=50,
		),
	}


@frappe.whitelist(methods=["POST"])
@formatted
def update_status(doctype: str, name: str, status: str) -> dict:
	doc = get_crm_doc(doctype, name)
	doc.status = status
	doc.save()
	return record_row(doc)


@frappe.whitelist(methods=["POST"])
@formatted
def add_note(doctype: str, name: str, content: str, title: str | None = None) -> dict:
	get_crm_doc(doctype, name)
	note = make_note(content, title or _("Note"), doctype, name, ignore_permissions=False)
	return {f: note.get(f) for f in ("name", "title", "content", "owner", "creation")}


@frappe.whitelist(methods=["POST"])
@formatted
def create_lead(data: dict | str) -> dict:
	"""New lead owned by the session user unless `lead_owner` is given."""
	data = frappe.parse_json(data) or {}
	allowed = (
		"first_name",
		"last_name",
		"mobile_no",
		"email",
		"organization",
		"source",
		"status",
		"lead_owner",
	)
	values = {k: data.get(k) for k in allowed if data.get(k) not in (None, "")}
	values.setdefault("lead_owner", frappe.session.user)
	doc = frappe.get_doc({"doctype": "CRM Lead", **values}).insert()
	return record_row(doc)


# Tasks
# -----


@frappe.whitelist()
@formatted
def list_tasks(filter: str = "today", start: int = 0, page_length: int = 50) -> dict:
	data, has_more = get_tasks(filter, start, page_length)
	return {"data": data, "has_more": has_more}


def get_tasks(filter: str, start: int, page_length: int) -> tuple[list, bool]:
	"""Tasks assigned to the session user."""
	today_start, tomorrow = day_range()
	filters = [["assigned_to", "=", frappe.session.user]]
	not_closed = ["status", "not in", CLOSED_TASK_STATUSES]
	order_by = "due_date asc, creation asc"
	if filter == "today":
		filters += [not_closed, ["due_date", ">=", today_start], ["due_date", "<", tomorrow]]
	elif filter == "overdue":
		filters += [not_closed, ["due_date", "<", today_start]]
	elif filter == "upcoming":
		filters += [not_closed, ["due_date", ">=", tomorrow]]
	elif filter == "done":
		filters.append(["status", "=", "Done"])
		order_by = "modified desc"
	elif filter == "all":
		order_by = "modified desc"
	else:
		frappe.throw(_("Unknown task filter {0}").format(filter))
	result = paged(
		frappe.get_list,
		"CRM Task",
		fields=TASK_FIELDS,
		filters=filters,
		order_by=order_by,
		start=start,
		page_length=page_length,
	)
	return result["data"], result["has_more"]


@frappe.whitelist(methods=["POST"])
@formatted
def create_task(
	reference_doctype: str | None = None,
	reference_docname: str | None = None,
	title: str | None = None,
	due_date: str | None = None,
	priority: str = "Medium",
	assigned_to: str | None = None,
	description: str | None = None,
) -> dict:
	"""A task on a lead/deal, or a standalone task (from the app's create button)."""
	if not (title or "").strip():
		frappe.throw(_("Task title is required"))
	if reference_doctype or reference_docname:
		get_crm_doc(reference_doctype, reference_docname)
	task = frappe.get_doc(
		{
			"doctype": "CRM Task",
			"title": title,
			"description": description,
			"priority": priority or "Medium",
			"status": "Todo",
			"due_date": due_date or None,
			"assigned_to": assigned_to or frappe.session.user,
			"reference_doctype": reference_doctype or None,
			"reference_docname": reference_docname or None,
		}
	).insert()
	return task_row(task)


@frappe.whitelist(methods=["POST"])
@formatted
def update_task(
	name: str | int,
	status: str | None = None,
	due_date: str | None = None,
	title: str | None = None,
	description: str | None = None,
	priority: str | None = None,
	assigned_to: str | None = None,
) -> dict:
	"""Only the values sent are changed."""
	task = frappe.get_doc("CRM Task", name)
	task.check_permission("write")
	values = {
		"status": status,
		"due_date": due_date,
		"title": title,
		"description": description,
		"priority": priority,
		"assigned_to": assigned_to,
	}
	for field, value in values.items():
		if value is not None and (value != "" or field == "description"):
			task.set(field, value)
	task.save()
	return task_row(task)


@frappe.whitelist(methods=["POST"])
def delete_task(name: str | int) -> None:
	frappe.delete_doc("CRM Task", name)


# Calls
# -----


@frappe.whitelist(methods=["POST"])
@formatted
def sync_calls(calls: list | str, device_id: str) -> list[dict]:
	"""Save phone call-log entries as CRM Call Logs. Safe to retry: known calls are returned as is."""
	calls = frappe.parse_json(calls) or []
	if len(calls) > MAX_SYNC_BATCH:
		frappe.throw(_("Send at most {0} calls at a time").format(MAX_SYNC_BATCH))
	device = clean_id(device_id)
	if not device:
		frappe.throw(_("device_id is required"))

	user = frappe.session.user
	numbers = frappe.db.get_value("User", user, ["mobile_no", "phone"], as_dict=True) or {}
	user_number = next(
		(n for n in (numbers.get("mobile_no"), numbers.get("phone")) if n and validate_phone_number(n)), None
	)
	if not user_number:
		# from / to are mandatory on CRM Call Log, and the CRM saves call logs again later
		frappe.throw(_("Add your mobile number to your CRM profile before syncing calls"))
	context = frappe._dict(
		user=user,
		device=device,
		user_number=user_number,
		all_calls=call_sync_scope() == "All calls",
		upload=recordings_enabled(),
	)
	return [sync_call(frappe._dict(c), context) for c in calls]


def sync_call(call, ctx) -> dict:
	device_call_id = clean_id(call.device_call_id)
	result = {
		"device_call_id": call.device_call_id,
		"call_log": None,
		"reference_doctype": None,
		"reference_docname": None,
		"reference_title": None,
		"upload_recording": False,
	}
	if not device_call_id:
		return result

	call_id = f"abm-{ctx.device}-{device_call_id}"
	existing = get_synced_call(call_id)
	if existing:
		return sync_result(result, existing, ctx)

	number = str(call.number or "").strip()
	if not validate_phone_number(number):
		# hidden / private numbers
		return result
	docname, doctype = get_contact_lead_or_deal_from_number(number)
	if not docname and not ctx.all_calls:
		return result

	direction = str(call.type or "").lower()
	outgoing = direction == "outgoing"
	duration = max(cint(call.duration), 0)
	if duration > 0:
		status = "Completed"
	elif direction == "rejected":
		status = "Busy"
	else:
		status = "No Answer"
	start = from_epoch_ms(call.start)

	doc = frappe.get_doc(
		{
			"doctype": "CRM Call Log",
			"id": call_id,
			"telephony_medium": "Manual",
			"type": "Outgoing" if outgoing else "Incoming",
			"status": status,
			"from": ctx.user_number if outgoing else number,
			"to": number if outgoing else ctx.user_number,
			"duration": duration,
			"start_time": start,
			"end_time": start + datetime.timedelta(seconds=duration) if start else None,
			"caller": ctx.user if outgoing else None,
			"receiver": None if outgoing else ctx.user,
		}
	)
	if doctype in CRM_DOCTYPES:
		doc.reference_doctype = doctype
		doc.reference_docname = docname
	if docname:
		doc.link_with_reference_doc(doctype, docname)

	try:
		doc.insert()
	except frappe.DuplicateEntryError:
		# the same call sent twice at once
		frappe.clear_messages()
	return sync_result(result, get_synced_call(call_id), ctx)


def get_synced_call(call_id: str):
	return frappe.db.get_value(
		"CRM Call Log",
		call_id,
		["name", "reference_doctype", "reference_docname", "duration", "recording_url"],
		as_dict=True,
	)


def sync_result(result: dict, log, ctx) -> dict:
	if not log:
		return result
	result["call_log"] = log.name
	if log.reference_doctype in CRM_DOCTYPES and log.reference_docname:
		result["reference_doctype"] = log.reference_doctype
		result["reference_docname"] = log.reference_docname
		result["reference_title"] = record_title(log.reference_doctype, log.reference_docname)
	result["upload_recording"] = bool(ctx.upload and flt(log.duration) > 0 and not log.recording_url)
	return result


@frappe.whitelist(methods=["POST"])
def upload_recording(call_log: str) -> dict:
	"""Attach the call recording sent as the multipart field `file`."""
	log = frappe.get_doc("CRM Call Log", call_log)
	check_call_access(log)
	upload = uploaded_file()
	if not upload:
		frappe.throw(_("Send the recording as the file field"))
	filename, content = upload
	check_extension(filename, AUDIO_EXTENSIONS)
	file = attach_file(filename, content, "CRM Call Log", log.name, "recording_url")
	log.db_set("recording_url", file.file_url)
	return {"recording_url": file.file_url}


@frappe.whitelist(methods=["POST"])
@formatted
def set_call_outcome(
	call_log: str, outcome: str, note: str | None = None, next_follow_up: str | None = None
) -> dict:
	"""Outcome, optional note and follow-up task for a call."""
	if outcome not in CALL_OUTCOMES:
		frappe.throw(_("Unknown call outcome {0}").format(outcome))
	log = frappe.get_doc("CRM Call Log", call_log)
	check_call_access(log)

	ref_doctype, ref_name = None, None
	if log.reference_doctype in CRM_DOCTYPES and log.reference_docname:
		ref_doctype, ref_name = log.reference_doctype, log.reference_docname

	log.abm_outcome = outcome
	if note and note.strip():
		note_doc = make_note(note, _("Call Note"), ref_doctype, ref_name, ignore_permissions=True)
		log.note = note_doc.name
		log.link_with_reference_doc("FCRM Note", note_doc.name)
	if next_follow_up:
		task = frappe.get_doc(
			{
				"doctype": "CRM Task",
				"title": _("Follow up"),
				"description": f"<p>{escape_html(outcome)}</p>",
				"status": "Todo",
				"priority": "Medium",
				"due_date": get_datetime(next_follow_up),
				"assigned_to": frappe.session.user,
				"reference_doctype": ref_doctype,
				"reference_docname": ref_name,
			}
		).insert(ignore_permissions=True)
		log.link_with_reference_doc("CRM Task", task.name)
	log.save(ignore_permissions=True)
	return call_row({f: log.get(f) for f in CALL_FIELDS})


@frappe.whitelist()
@formatted
def list_calls(
	scope: str = "mine",
	date_from: str | None = None,
	date_to: str | None = None,
	start: int = 0,
	page_length: int = 50,
) -> dict:
	"""The session user's calls, or everyone's (`team`, managers only)."""
	user = frappe.session.user
	filters = []
	if date_from:
		filters.append(["start_time", ">=", day_start(date_from)])
	if date_to:
		filters.append(["start_time", "<", add_days(day_start(date_to), 1)])
	or_filters = None
	if scope == "team":
		frappe.only_for(MANAGER_ROLES)
	else:
		or_filters = [["caller", "=", user], ["receiver", "=", user]]
	result = paged(
		frappe.get_all,
		"CRM Call Log",
		fields=CALL_FIELDS,
		filters=filters,
		or_filters=or_filters,
		order_by="start_time desc, creation desc",
		start=start,
		page_length=page_length,
	)
	result["data"] = enrich_calls(result["data"])
	return result


# Field visits
# ------------


@frappe.whitelist(methods=["POST"])
@formatted
def check_in(
	reference_doctype: str,
	reference_docname: str,
	latitude: float,
	longitude: float,
	accuracy: float | None = None,
	address: str | None = None,
	notes: str | None = None,
) -> dict:
	"""Record a visit to a lead or deal. An optional multipart `file` is saved as the photo."""
	get_crm_doc(reference_doctype, reference_docname)
	latitude, longitude = flt(latitude), flt(longitude)
	if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
		frappe.throw(_("Invalid location"))

	upload = uploaded_file()
	if upload:
		check_extension(upload[0], IMAGE_EXTENSIONS)

	visit = frappe.get_doc(
		{
			"doctype": "ABM Field Visit",
			"reference_doctype": reference_doctype,
			"reference_docname": reference_docname,
			"latitude": latitude,
			"longitude": longitude,
			"accuracy": flt(accuracy) if accuracy not in (None, "") else None,
			"address": address,
			"notes": notes,
			"visited_by": frappe.session.user,
			"visited_at": now_datetime(),
		}
	).insert()
	if upload:
		file = attach_file(upload[0], upload[1], "ABM Field Visit", visit.name, "photo")
		visit.db_set("photo", file.file_url)
	return {f: visit.get(f) for f in VISIT_FIELDS}


# Manager dashboard
# -----------------


@frappe.whitelist()
@formatted
def manager_dashboard(date_from: str | None = None, date_to: str | None = None) -> dict:
	"""Team activity between two dates (default today)."""
	frappe.only_for(MANAGER_ROLES)
	start = day_start(date_from or nowdate())
	end = add_days(day_start(date_to or date_from or nowdate()), 1)
	now = now_datetime()

	stats = {s["user"]: s for s in call_stats(start, end, group=True)}
	assigned = dict(
		frappe.db.sql(
			"""select lead_owner, count(*) from `tabCRM Lead`
			where creation >= %s and creation < %s and ifnull(lead_owner, '') != '' group by lead_owner""",
			(start, end),
		)
	)
	touched = dict(
		frappe.db.sql(
			"""select user, count(distinct lead) from (
				select case when type = 'Outgoing' then caller else receiver end as user, reference_docname as lead
				from `tabCRM Call Log`
				where reference_doctype = 'CRM Lead' and start_time >= %(start)s and start_time < %(end)s
				union all
				select owner, reference_docname from `tabFCRM Note`
				where reference_doctype = 'CRM Lead' and creation >= %(start)s and creation < %(end)s
				union all
				select visited_by, reference_docname from `tabABM Field Visit`
				where reference_doctype = 'CRM Lead' and visited_at >= %(start)s and visited_at < %(end)s
			) t where user is not null group by user""",
			{"start": start, "end": end},
		)
	)
	visits = dict(
		frappe.db.sql(
			"""select visited_by, count(*) from `tabABM Field Visit`
			where visited_at >= %s and visited_at < %s group by visited_by""",
			(start, end),
		)
	)
	overdue = dict(
		frappe.db.sql(
			"""select assigned_to, count(*) from `tabCRM Task`
			where status not in %s and due_date < %s and ifnull(assigned_to, '') != '' group by assigned_to""",
			(CLOSED_TASK_STATUSES, now),
		)
	)
	last_calls = dict(
		frappe.db.sql(
			"""select case when type = 'Outgoing' then caller else receiver end as user, max(start_time)
			from `tabCRM Call Log` group by 1"""
		)
	)

	reps = []
	for u in crm_users():
		s = stats.get(u.name) or {}
		reps.append(
			{
				"user": u.name,
				"full_name": u.full_name,
				"user_image": u.user_image,
				"calls": s.get("count", 0),
				"connected": s.get("connected", 0),
				"talk_time": s.get("talk_time", 0),
				"outgoing": s.get("outgoing", 0),
				"incoming": s.get("incoming", 0),
				"missed": s.get("missed", 0),
				"leads_assigned": assigned.get(u.name, 0),
				"leads_touched": touched.get(u.name, 0),
				"visits": visits.get(u.name, 0),
				"overdue_tasks": overdue.get(u.name, 0),
				"last_call": last_calls.get(u.name),
			}
		)

	all_calls = call_stats(start, end)
	lead_counts = dict(
		frappe.db.sql(
			"select status, count(*) from `tabCRM Lead` where creation >= %s and creation < %s group by status",
			(start, end),
		)
	)
	return {
		"totals": {
			"calls": all_calls.get("count", 0),
			"connected": all_calls.get("connected", 0),
			"talk_time": all_calls.get("talk_time", 0),
			"new_leads": sum(lead_counts.values()),
			"converted": frappe.db.count(
				"CRM Deal", [["creation", ">=", start], ["creation", "<", end], ["lead", "is", "set"]]
			),
			"visits": sum(visits.values()),
			"overdue_tasks": sum(overdue.values()),
		},
		"reps": reps,
		"lead_funnel": [
			{"status": s.name, "color": s.color, "count": lead_counts.get(s.name, 0)}
			for s in get_statuses("CRM Lead Status")
		],
		"recent_calls": enrich_calls(
			frappe.get_all(
				"CRM Call Log",
				filters={"recording_url": ["is", "set"]},
				fields=CALL_FIELDS,
				order_by="start_time desc, creation desc",
				limit=20,
			)
		),
	}


# Helpers
# -------


def is_manager(user: str | None = None) -> bool:
	user = user or frappe.session.user
	return user == "Administrator" or bool(set(MANAGER_ROLES) & set(frappe.get_roles(user)))


def crm_users() -> list[dict]:
	"""Enabled users with a CRM role."""
	names = frappe.get_all(
		"Has Role",
		filters={"parenttype": "User", "role": ["in", CRM_ROLES]},
		pluck="parent",
		distinct=True,
	)
	names = [n for n in names if n not in ("Administrator", "Guest")]
	if not names:
		return []
	return frappe.get_all(
		"User",
		filters={"name": ["in", names], "enabled": 1, "user_type": "System User"},
		fields=["name", "full_name", "user_image"],
		order_by="full_name asc",
	)


def call_sync_scope() -> str:
	return frappe.db.get_single_value("ABM CRM Settings", "call_sync_scope") or "CRM numbers only"


def recordings_enabled() -> int:
	return cint(frappe.db.get_single_value("ABM CRM Settings", "upload_recordings"))


def get_statuses(doctype: str) -> list[dict]:
	return frappe.get_all(doctype, fields=["name", "color", "type", "position"], order_by="position asc")


def statuses_of_type(doctype: str, types) -> list[str]:
	return frappe.get_all(doctype, filters={"type": ["in", types]}, pluck="name")


def closed_statuses(doctype: str) -> list[str]:
	return statuses_of_type(doctype, CLOSED_STATUS_TYPES) or [""]


def get_crm_doc(doctype: str, name: str):
	if doctype not in CRM_DOCTYPES:
		frappe.throw(_("Only leads and deals are supported"))
	doc = frappe.get_doc(doctype, name)
	doc.check_permission("read")
	return doc


def record_row(doc) -> dict:
	fields = LEAD_FIELDS if doc.doctype == "CRM Lead" else DEAL_FIELDS
	row = {f: doc.get(f) for f in fields}
	row["tags"] = doc_tags(doc.doctype, doc.name)
	return row


def record_title(doctype: str, name: str) -> str | None:
	if not frappe.has_permission(doctype, "read", name):
		return None
	if doctype == "CRM Lead":
		return frappe.db.get_value("CRM Lead", name, "lead_name")
	org, lead_name = frappe.db.get_value("CRM Deal", name, ["organization", "lead_name"]) or (None, None)
	return org or lead_name


def task_row(task) -> dict:
	return {f: task.get(f) for f in TASK_FIELDS}


def call_row(call: dict) -> dict:
	call = dict(call)
	call["duration"] = cint(call.get("duration"))
	url = call.get("recording_url")
	if not url:
		call["recording_url_path"] = None
	elif url.startswith(("/files/", "/private/files/")):
		call["recording_url_path"] = url
	else:
		call["recording_url_path"] = (
			f"/api/method/crm.integrations.api.get_recording_url?call_log_name={call.get('name')}"
		)
	return call


def enrich_calls(calls: list[dict]) -> list[dict]:
	"""Call rows plus the rep's full name and the lead/deal title."""
	names = {}
	rows = []
	for c in calls:
		row = call_row(c)
		user = row.get("caller") if row.get("type") == "Outgoing" else row.get("receiver")
		if user and user not in names:
			names[user] = frappe.db.get_value("User", user, "full_name")
		row["user_full_name"] = names.get(user)
		row["reference_title"] = (
			record_title(row["reference_doctype"], row["reference_docname"])
			if row.get("reference_doctype") in CRM_DOCTYPES and row.get("reference_docname")
			else None
		)
		rows.append(row)
	return rows


def check_call_access(log) -> None:
	"""Only the call's caller or receiver, or a manager."""
	if frappe.session.user not in (log.caller, log.receiver) and not is_manager():
		frappe.throw(_("Not permitted"), frappe.PermissionError)


def call_stats(start, end, user: str | None = None, group: bool = False):
	"""Call counts between two datetimes, for one user, everyone, or per user (`group`)."""
	rep = "case when type = 'Outgoing' then caller else receiver end"
	conditions = "start_time >= %(start)s and start_time < %(end)s"
	if user:
		conditions += f" and {rep} = %(user)s"
	rows = frappe.db.sql(
		f"""select {rep} as user,
			count(*) as count,
			sum(case when status = 'Completed' then 1 else 0 end) as connected,
			sum(ifnull(duration, 0)) as talk_time,
			sum(case when type = 'Outgoing' then 1 else 0 end) as outgoing,
			sum(case when type = 'Incoming' then 1 else 0 end) as incoming,
			sum(case when type = 'Incoming' and status != 'Completed' then 1 else 0 end) as missed
		from `tabCRM Call Log`
		where {conditions}
		{"group by 1" if group else ""}""",
		{"start": start, "end": end, "user": user},
		as_dict=True,
	)
	for r in rows:
		for k in ("count", "connected", "talk_time", "outgoing", "incoming", "missed"):
			r[k] = cint(r[k])
	if group:
		return rows
	row = rows[0] if rows else {}
	return {k: cint(row.get(k)) for k in ("count", "connected", "talk_time")}


def paged(getter, doctype: str, start=0, page_length=20, **kwargs) -> dict:
	start = max(cint(start), 0)
	page_length = min(max(cint(page_length) or 20, 1), 100)
	rows = getter(doctype, start=start, page_length=page_length + 1, **kwargs)
	return {"data": rows[:page_length], "has_more": len(rows) > page_length}


def safe_order_by(order_by: str | None, default: str = "modified desc") -> str:
	parts = (order_by or "").split()
	if (
		len(parts) in (1, 2)
		and parts[0] in ORDER_FIELDS
		and (len(parts) == 1 or parts[1].lower() in ("asc", "desc"))
	):
		return " ".join(parts)
	return default


def day_start(value) -> datetime.datetime:
	return datetime.datetime.combine(getdate(value), datetime.time.min)


def day_range() -> tuple[datetime.datetime, datetime.datetime]:
	start = day_start(nowdate())
	return start, add_days(start, 1)


def from_epoch_ms(value) -> datetime.datetime | None:
	ms = flt(value)
	if not ms:
		return None
	utc = datetime.datetime.fromtimestamp(ms / 1000, tz=datetime.UTC)
	return convert_utc_to_system_timezone(utc).replace(tzinfo=None, microsecond=0)


def clean_id(value) -> str:
	return re.sub(r"[^A-Za-z0-9_.:-]", "", str(value or ""))[:60]


def make_note(content: str, title: str, doctype: str | None, name: str | None, ignore_permissions: bool):
	"""FCRM Note from plain text typed in the app."""
	html = "".join(f"<p>{escape_html(line)}</p>" for line in content.strip().splitlines() if line.strip())
	return frappe.get_doc(
		{
			"doctype": "FCRM Note",
			"title": title,
			"content": html,
			"reference_doctype": doctype,
			"reference_docname": name,
		}
	).insert(ignore_permissions=ignore_permissions)


def uploaded_file() -> tuple[str, bytes] | None:
	"""(filename, content) of the multipart field `file`, if sent."""
	files = getattr(frappe.request, "files", None) if frappe.request else None
	file = files.get("file") if files else None
	if not file or not file.filename:
		return None
	return os.path.basename(file.filename), file.stream.read()


def check_extension(filename: str, allowed) -> None:
	ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
	if ext not in allowed:
		frappe.throw(_("File type {0} is not allowed").format(ext or filename))


def attach_file(
	filename: str, content: bytes, doctype: str, name: str, field: str | None, is_private: int = 1
):
	return frappe.get_doc(
		{
			"doctype": "File",
			"file_name": filename,
			"content": content,
			"is_private": is_private,
			"attached_to_doctype": doctype,
			"attached_to_name": name,
			"attached_to_field": field,
		}
	).insert(ignore_permissions=True)


# Full CRM in the app (v2)
# ========================

OPEN_DEAL_STATUS_TYPES = ("Open", "Ongoing", "On Hold")
LAYOUT_SKIP_FIELDTYPES = (
	"Tab Break",
	"Section Break",
	"Column Break",
	"HTML",
	"Button",
	"Table",
	"Table MultiSelect",
	"Fold",
	"Heading",
	"Image",
)
CONTACT_FIELDS = ["name", "full_name", "email_id", "mobile_no", "company_name", "image"]
CONTACT_DETAIL_FIELDS = ["first_name", "last_name", "salutation", "gender", "designation", "phone"]
ORGANIZATION_FIELDS = [
	"name",
	"organization_name",
	"website",
	"industry",
	"territory",
	"organization_logo",
	"annual_revenue",
]
ORGANIZATION_DETAIL_FIELDS = ["no_of_employees", "currency", "address"]
EMAIL_FIELDS = [
	"name",
	"subject",
	"content",
	"sender",
	"sender_full_name",
	"recipients",
	"cc",
	"bcc",
	"sent_or_received",
	"creation",
	"communication_date",
	"read_by_recipient",
	"in_reply_to",
	"reference_doctype",
	"reference_name",
]
EMAIL_INTERNAL_FIELDS = ("communication_date", "reference_doctype", "reference_name")
ATTACHMENT_FIELDS = ["name", "file_name", "file_url", "file_size", "is_private", "owner", "creation"]
EVENT_FIELDS = ["name", "subject", "starts_on", "ends_on", "all_day", "status", "owner", "description"]
MAX_SEARCH_RESULTS = 50


# Dashboard and search
# --------------------


@frappe.whitelist()
@formatted
def get_dashboard() -> dict:
	"""Everything the app's home screen shows, in one call."""
	user = frappe.session.user
	today_start, tomorrow = day_range()
	month_start = today_start.replace(day=1)
	next_month = (month_start + datetime.timedelta(days=32)).replace(day=1)
	calls = call_stats(today_start, tomorrow, user)

	statuses = get_statuses("CRM Deal Status")
	open_statuses = [s.name for s in statuses if s.type in OPEN_DEAL_STATUS_TYPES]
	won_statuses = [s.name for s in statuses if s.type == "Won"]
	pipeline_rows = deal_totals([["status", "in", open_statuses or [""]]], group_by_status=True)
	currency = dashboard_currency(pipeline_rows)
	by_status = {}
	for r in pipeline_rows:
		entry = by_status.setdefault(r.status, {"count": 0, "value": 0.0})
		entry["count"] += cint(r.count)
		entry["value"] += row_value(r, currency)
	pipeline = [
		{
			"status": s.name,
			"color": s.color,
			"count": by_status.get(s.name, {}).get("count", 0),
			"value": flt(by_status.get(s.name, {}).get("value", 0), 2),
		}
		for s in statuses
		if s.type in OPEN_DEAL_STATUS_TYPES
	]

	won_rows = deal_totals(
		[
			["status", "in", won_statuses or [""]],
			["closed_date", ">=", month_start.date()],
			["closed_date", "<", next_month.date()],
		]
	) + deal_totals(
		[
			["status", "in", won_statuses or [""]],
			["closed_date", "is", "not set"],
			["modified", ">=", month_start],
			["modified", "<", next_month],
		]
	)

	return {
		"greeting_name": frappe.db.get_value("User", user, "first_name") or user,
		"stats": {
			"open_leads": frappe.db.count(
				"CRM Lead",
				{
					"lead_owner": user,
					"converted": 0,
					"status": ["not in", closed_statuses("CRM Lead Status")],
				},
			),
			"open_deals": frappe.db.count(
				"CRM Deal", {"deal_owner": user, "status": ["in", open_statuses or [""]]}
			),
			"pipeline_value": flt(sum(p["value"] for p in pipeline), 2),
			"currency": currency,
			"won_this_month": sum(cint(r.count) for r in won_rows),
			"won_value_this_month": flt(sum(row_value(r, currency) for r in won_rows), 2),
			"tasks_today": frappe.db.count(
				"CRM Task",
				[
					["assigned_to", "=", user],
					["status", "not in", CLOSED_TASK_STATUSES],
					["due_date", ">=", today_start],
					["due_date", "<", tomorrow],
				],
			),
			"tasks_overdue": frappe.db.count(
				"CRM Task",
				[
					["assigned_to", "=", user],
					["status", "not in", CLOSED_TASK_STATUSES],
					["due_date", "<", today_start],
				],
			),
			"calls_today": calls["count"],
			"talk_time_today": calls["talk_time"],
			"unread_notifications": unread_notifications(),
		},
		"agenda": agenda_items(today_start, add_days(tomorrow, 1)),
		"pipeline": pipeline,
		"recent": recent_records(8),
	}


def deal_totals(filters: list, group_by_status: bool = False) -> list:
	"""Deal count and value per currency (and status), for the deals the user can see."""
	group = ["currency", "exchange_rate"] + (["status"] if group_by_status else [])
	return frappe.get_list(
		"CRM Deal",
		fields=[*group, {"COUNT": "*", "as": "count"}, {"SUM": "deal_value", "as": "value"}],
		filters=filters,
		group_by=", ".join(group),
		order_by=None,
	)


def dashboard_currency(rows: list) -> str:
	"""The deals' own currency when they all share one, else the CRM base currency."""
	currencies = {r.currency for r in rows if r.currency}
	if len(currencies) == 1:
		return currencies.pop()
	return base_currency()


def base_currency() -> str:
	return (
		frappe.db.get_single_value("FCRM Settings", "currency")
		or frappe.db.get_default("currency")
		or "USD"
	)


def row_value(row, currency: str) -> float:
	"""Deal value in `currency`: as stored when it matches, else converted with the deal's exchange rate."""
	if not row.currency or row.currency == currency:
		return flt(row.value)
	return flt(row.value) * flt(row.exchange_rate or 1)


def recent_records(limit: int) -> list[dict]:
	"""Leads and deals the session user changed last."""
	user = frappe.session.user
	rows = []
	for doctype, fields in (
		("CRM Lead", ["name", "lead_name", "organization", "status", "modified"]),
		("CRM Deal", ["name", "lead_name", "organization", "status", "modified"]),
	):
		for r in frappe.get_list(
			doctype, fields=fields, filters={"modified_by": user}, order_by="modified desc", limit=limit
		):
			title = r.lead_name if doctype == "CRM Lead" else (r.organization or r.lead_name)
			rows.append(
				{
					"doctype": doctype,
					"name": r.name,
					"title": title or r.name,
					"status": r.status,
					"modified": r.modified,
				}
			)
	rows.sort(key=lambda r: r["modified"], reverse=True)
	return rows[:limit]


SEARCH_SOURCES = (
	# doctype, fields, searched fields, extra filters
	(
		"CRM Lead",
		["name", "lead_name", "organization", "email", "mobile_no", "status"],
		("lead_name", "organization", "email", "mobile_no", "name"),
		[["converted", "=", 0]],
	),
	(
		"CRM Deal",
		["name", "lead_name", "organization", "email", "mobile_no", "status"],
		("lead_name", "organization", "email", "mobile_no", "name"),
		[],
	),
	(
		"Contact",
		["name", "full_name", "company_name", "email_id", "mobile_no"],
		("full_name", "company_name", "email_id", "mobile_no", "name"),
		[],
	),
	(
		"CRM Organization",
		["name", "organization_name", "website", "industry"],
		("organization_name", "website", "name"),
		[],
	),
)


@frappe.whitelist()
def search(q: str, limit: int = 20) -> list[dict]:
	"""Leads, deals, contacts and organizations matching `q`, each list permission-checked."""
	q = (q or "").strip()
	if not q:
		return []
	limit = min(max(cint(limit) or 20, 1), MAX_SEARCH_RESULTS)
	results = []
	for doctype, fields, searched, filters in SEARCH_SOURCES:
		if not frappe.has_permission(doctype, "read"):
			continue
		for r in frappe.get_list(
			doctype,
			fields=fields,
			filters=filters,
			or_filters=[[f, "like", f"%{q}%"] for f in searched],
			order_by="modified desc",
			limit=limit,
		):
			results.append({"doctype": doctype, "name": r.name, **search_text(doctype, r)})
	return results[:limit] if len(results) <= limit else interleave(results, limit)


def search_text(doctype: str, r) -> dict:
	contact = " · ".join(x for x in (r.get("mobile_no"), r.get("email") or r.get("email_id")) if x)
	if doctype == "CRM Lead":
		return {
			"title": r.lead_name or r.name,
			"subtitle": " · ".join(x for x in (r.organization, contact) if x),
		}
	if doctype == "CRM Deal":
		return {
			"title": r.organization or r.lead_name or r.name,
			"subtitle": " · ".join(x for x in (r.lead_name if r.organization else None, r.status) if x),
		}
	if doctype == "Contact":
		return {
			"title": r.full_name or r.name,
			"subtitle": " · ".join(x for x in (r.company_name, contact) if x),
		}
	return {"title": r.organization_name or r.name, "subtitle": r.website or r.industry or ""}


def interleave(results: list[dict], limit: int) -> list[dict]:
	"""Take results round-robin per doctype, so one doctype does not crowd out the others."""
	groups = {}
	for r in results:
		groups.setdefault(r["doctype"], []).append(r)
	out = []
	while len(out) < limit and any(groups.values()):
		for rows in groups.values():
			if rows and len(out) < limit:
				out.append(rows.pop(0))
	return out


# Notifications
# -------------


@frappe.whitelist()
@formatted
def list_notifications(start: int = 0, page_length: int = 30) -> dict:
	"""The session user's CRM Notifications, newest first."""
	from abm_crm.push import notification_body, notification_title

	result = paged(
		frappe.get_all,
		"CRM Notification",
		fields=[
			"name",
			"type",
			"from_user",
			"to_user",
			"read",
			"creation",
			"message",
			"notification_text",
			"notification_type_doctype",
			"notification_type_doc",
			"reference_doctype",
			"reference_name",
		],
		filters={"to_user": frappe.session.user},
		order_by="creation desc",
		start=start,
		page_length=page_length,
	)
	users = {r.from_user for r in result["data"] if r.from_user}
	names = (
		dict(
			frappe.get_all(
				"User", filters={"name": ["in", list(users)]}, fields=["name", "full_name"], as_list=True
			)
		)
		if users
		else {}
	)
	result["data"] = [
		{
			"name": r.name,
			"type": r.type,
			"title": notification_title(r),
			"body": notification_body(r),
			"from_user": r.from_user,
			"from_full_name": names.get(r.from_user),
			"read": cint(r.read),
			"creation": r.creation,
			"doctype": r.reference_doctype,
			"docname": r.reference_name,
		}
		for r in result["data"]
	]
	result["unread"] = unread_notifications()
	return result


@frappe.whitelist(methods=["POST"])
def mark_notifications_read(names: list | str | None = None) -> dict:
	"""Mark the given notifications (or all) of the session user as read."""
	names = frappe.parse_json(names) if isinstance(names, str) and names.startswith("[") else names
	if isinstance(names, str):
		names = [names] if names.strip() else []
	filters = {"to_user": frappe.session.user, "read": 0}
	if names:
		filters["name"] = ["in", list(names)]
	for name in frappe.get_all("CRM Notification", filters=filters, pluck="name"):
		frappe.db.set_value("CRM Notification", name, "read", 1)
	return {"unread": unread_notifications()}


def unread_notifications() -> int:
	return frappe.db.count("CRM Notification", {"to_user": frappe.session.user, "read": 0})


# Email
# -----


@frappe.whitelist()
@formatted
def get_emails(doctype: str, name: str) -> list[dict]:
	"""Emails of the record (and, for a deal, of the lead it came from), newest first."""
	doc = get_crm_doc(doctype, name)
	refs = [(doctype, name)]
	if doctype == "CRM Deal" and doc.get("lead") and frappe.has_permission("CRM Lead", "read", doc.lead):
		refs.append(("CRM Lead", doc.lead))
	emails = []
	for ref_doctype, ref_name in refs:
		emails += frappe.get_all(
			"Communication",
			filters={
				"reference_doctype": ref_doctype,
				"reference_name": ref_name,
				"communication_type": ["in", ["Communication", "Automated Message"]],
				"communication_medium": "Email",
			},
			fields=EMAIL_FIELDS,
			order_by="creation desc",
			limit=100,
		)
	emails.sort(key=lambda e: e.communication_date or e.creation, reverse=True)
	emails = emails[:100]

	files = {}
	if emails:
		for f in frappe.get_all(
			"File",
			filters={
				"attached_to_doctype": "Communication",
				"attached_to_name": ["in", [e.name for e in emails]],
			},
			fields=["attached_to_name", "file_name", "file_url"],
			order_by="creation asc",
		):
			files.setdefault(f.attached_to_name, []).append(
				{"file_name": f.file_name, "file_url": f.file_url}
			)
	return [
		{
			**{f: e.get(f) for f in EMAIL_FIELDS if f not in EMAIL_INTERNAL_FIELDS},
			"creation": e.communication_date or e.creation,
			"attachments": files.get(e.name, []),
		}
		for e in emails
	]


@frappe.whitelist()
def get_email_setup(doctype: str, name: str) -> dict:
	"""Senders, templates and the default recipient for the email composer."""
	from abm_crm.api.email import _get_sender_options

	doc = get_crm_doc(doctype, name)
	templates = frappe.get_list(
		"Email Template",
		fields=["name", "subject"],
		filters={"enabled": 1},
		or_filters=[["reference_doctype", "=", doctype], ["reference_doctype", "is", "not set"]],
		order_by="name asc",
	)
	return {
		"senders": _get_sender_options(frappe.session.user),
		"templates": templates,
		"to": [doc.email] if doc.get("email") else [],
	}


@frappe.whitelist()
def render_email_template(template: str, doctype: str, name: str) -> dict:
	"""Subject and HTML body of an Email Template rendered with the record, like the web composer."""
	doc = get_crm_doc(doctype, name)
	email_template = frappe.get_doc("Email Template", template)
	email_template.check_permission("read")
	values = doc.as_dict()
	# fields are the template context; nesting doc lets {{ doc.field }} work too (as on the web)
	rendered = email_template.get_formatted_email({**values, "doc": values})
	return {"subject": rendered.get("subject"), "content": rendered.get("message")}


@frappe.whitelist(methods=["POST"])
def send_email(
	doctype: str,
	name: str,
	to: str | list,
	subject: str,
	content: str,
	cc: str | list | None = None,
	bcc: str | list | None = None,
	sender: str | None = None,
	attachments: str | list | None = None,
	in_reply_to: str | None = None,
) -> str:
	"""Send an email from the record through the same path as the web composer. Returns the Communication."""
	from frappe.core.doctype.communication.email import make

	from abm_crm.api.email import _get_sender_options

	get_crm_doc(doctype, name)
	if not sender:
		options = _get_sender_options(frappe.session.user)
		default = next((o for o in options if o["is_default"]), None)
		sender = default["value"] if default else None
	attachments = frappe.parse_json(attachments) if isinstance(attachments, str) else attachments
	for file in attachments or []:
		# only files the user may read (e.g. uploaded with upload_attachment)
		frappe.get_doc("File", file).check_permission("read")

	frappe.flags.abm_crm_composer = True  # sender rules apply, as for the web composer
	try:
		result = make(
			doctype=doctype,
			name=name,
			recipients=join_addresses(to),
			cc=join_addresses(cc),
			bcc=join_addresses(bcc),
			subject=subject,
			content=content,
			sender=sender,
			sender_full_name=frappe.db.get_value("User", frappe.session.user, "full_name"),
			send_email=1,
			attachments=attachments or None,
			in_reply_to=in_reply_to or None,
		)
	finally:
		frappe.flags.abm_crm_composer = False
	return result["name"]


def join_addresses(value) -> str | None:
	if not value:
		return None
	if isinstance(value, str):
		value = frappe.parse_json(value) if value.strip().startswith("[") else value.split(",")
	return ", ".join(v.strip() for v in value if v and v.strip()) or None


# Attachments
# -----------


@frappe.whitelist()
@formatted
def list_attachments(doctype: str, name: str) -> list[dict]:
	get_crm_doc(doctype, name)
	return frappe.get_all(
		"File",
		filters={"attached_to_doctype": doctype, "attached_to_name": name, "is_folder": 0},
		fields=ATTACHMENT_FIELDS,
		order_by="creation desc",
	)


@frappe.whitelist(methods=["POST"])
@formatted
def upload_attachment(doctype: str, name: str, is_private: int = 1) -> dict:
	"""Attach the multipart field `file` to the record (private unless `is_private` is 0)."""
	doc = get_crm_doc(doctype, name)
	doc.check_permission("write")
	upload = uploaded_file()
	if not upload:
		frappe.throw(_("Send the file as the file field"))
	file = attach_file(upload[0], upload[1], doctype, name, None, is_private=1 if cint(is_private) else 0)
	return {f: file.get(f) for f in ATTACHMENT_FIELDS}


@frappe.whitelist(methods=["POST"])
def delete_attachment(file: str) -> None:
	"""Only the file's owner or a manager, and only files of a lead or deal."""
	doc = frappe.get_doc("File", file)
	if doc.attached_to_doctype not in CRM_DOCTYPES:
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	if doc.owner != frappe.session.user and not is_manager():
		frappe.throw(
			_("Only the person who uploaded this file or a manager can delete it"), frappe.PermissionError
		)
	frappe.delete_doc("File", doc.name)


# Editing records
# ---------------


@frappe.whitelist()
def get_form(doctype: str) -> list[dict]:
	"""The edit form: sections and fields from the CRM Fields Layout (Data Fields, else Side Panel)."""
	if doctype not in CRM_DOCTYPES:
		frappe.throw(_("Only leads and deals are supported"))
	if not frappe.has_permission(doctype, "read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	return form_sections(doctype)


def form_sections(doctype: str) -> list[dict]:
	from crm.fcrm.doctype.crm_fields_layout.crm_fields_layout import get_fields_layout

	layout_type = (
		"Data Fields"
		if frappe.db.exists("CRM Fields Layout", {"dt": doctype, "type": "Data Fields"})
		else "Side Panel"
	)
	sections = []
	seen = set()
	for tab in get_fields_layout(doctype, layout_type) or []:
		for section in tab.get("sections") or []:
			fields = []
			for column in section.get("columns") or []:
				for field in column.get("fields") or []:
					# get_fields_layout replaces known fieldnames with the field's meta (as a dict)
					if not isinstance(field, dict) or field.get("fieldname") in seen:
						continue
					if field.get("hidden") or field.get("fieldtype") in LAYOUT_SKIP_FIELDTYPES:
						continue
					seen.add(field["fieldname"])
					fields.append(form_field(field))
			if fields:
				sections.append({"section": section.get("label") or None, "fields": fields})
	return sections


def form_field(field: dict) -> dict:
	options = field.get("options")
	if field.get("fieldtype") == "Select":
		options = [o for o in (options or "").split("\n") if o.strip()]
	return {
		"fieldname": field["fieldname"],
		"label": _(field.get("label") or field["fieldname"]),
		"fieldtype": field.get("fieldtype"),
		"options": options,
		"reqd": cint(field.get("reqd")),
		"read_only": cint(field.get("read_only") or field.get("fieldtype") in ("Read Only",)),
	}


def form_fields(doctype: str) -> list[dict]:
	return [f for s in form_sections(doctype) for f in s["fields"]]


@frappe.whitelist()
def link_options(doctype: str, txt: str = "") -> list[dict]:
	"""Values for a Link field pointing to `doctype`, max 20, permission-checked."""
	txt = (txt or "").strip()
	if doctype == "User":
		# owners and assignees are CRM users, as in the web CRM's user pickers
		users = crm_users()
		needle = txt.lower()
		return [
			{"value": u.name, "label": u.full_name or u.name}
			for u in users
			if not needle or needle in (u.full_name or "").lower() or needle in u.name.lower()
		][:20]
	from frappe.desk.search import build_for_autosuggest, search_widget

	if not (frappe.has_permission(doctype, "select") or frappe.has_permission(doctype, "read")):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	rows = build_for_autosuggest(search_widget(doctype, txt, page_length=20), doctype=doctype)
	return [{"value": r["value"], "label": r.get("label") or r["value"]} for r in rows[:20]]


@frappe.whitelist(methods=["POST"])
@formatted
def update_record(doctype: str, name: str, values: dict | str) -> dict:
	"""Set fields of the edit form. Fields not in get_form, or read only there, are refused."""
	values = frappe.parse_json(values) or {}
	if not isinstance(values, dict) or not values:
		frappe.throw(_("Nothing to update"))
	doc = get_crm_doc(doctype, name)
	doc.check_permission("write")
	fields = {f["fieldname"]: f for f in form_fields(doctype)}
	for fieldname in values:
		field = fields.get(fieldname)
		if not field:
			frappe.throw(_("Field {0} cannot be edited here").format(fieldname))
		if field["read_only"]:
			frappe.throw(_("Field {0} is read only").format(field["label"]))
	doc.update({k: (None if v == "" else v) for k, v in values.items()})
	doc.save()
	return get_record(doctype, name)["doc"]


@frappe.whitelist(methods=["POST"])
def assign(doctype: str, name: str, users: list | str) -> list[dict]:
	"""Assign the record to users (frappe.desk.form.assign_to). Returns the assignees."""
	from frappe.desk.form.assign_to import add

	doc = get_crm_doc(doctype, name)
	doc.check_permission("write")
	users = frappe.parse_json(users) if isinstance(users, str) and users.startswith("[") else users
	if isinstance(users, str):
		users = [users]
	users = [u for u in users or [] if u]
	if not users:
		frappe.throw(_("Select a user to assign"))
	add({"assign_to": users, "doctype": doctype, "name": name})
	frappe.clear_messages()  # "already assigned" / "shared with" notes are not errors for the app
	return assignees(frappe.get_doc(doctype, name))


@frappe.whitelist(methods=["POST"])
def unassign(doctype: str, name: str, user: str) -> list[dict]:
	from frappe.desk.form.assign_to import remove

	doc = get_crm_doc(doctype, name)
	doc.check_permission("write")
	remove(doctype, name, user)
	return assignees(frappe.get_doc(doctype, name))


def assignees(doc) -> list[dict]:
	users = frappe.parse_json(doc.get("_assign") or "[]") or []
	if not users:
		return []
	rows = {
		u.name: u
		for u in frappe.get_all(
			"User", filters={"name": ["in", users]}, fields=["name", "full_name", "user_image"]
		)
	}
	return [rows[u] for u in users if u in rows]


@frappe.whitelist(methods=["POST"])
def convert_to_deal(
	lead: str,
	deal: dict | str | None = None,
	existing_contact: str | None = None,
	existing_organization: str | None = None,
) -> dict:
	"""Convert a lead with crm's own conversion. A lead already converted returns its deal."""
	from crm.fcrm.doctype.crm_lead.crm_lead import convert_to_deal as crm_convert

	get_crm_doc("CRM Lead", lead)
	deal = frappe.parse_json(deal) if isinstance(deal, str) else deal
	name = crm_convert(
		lead=lead,
		deal=deal or None,
		existing_contact=existing_contact or None,
		existing_organization=existing_organization or None,
		if_converted="Return Existing",  # retries from a flaky connection must not make two deals
	)
	return {"deal": name}


@frappe.whitelist(methods=["POST"])
@formatted
def create_deal(data: dict | str) -> dict:
	"""New deal (with its contact and organization, like the web form), owned by the session user."""
	from crm.fcrm.doctype.crm_deal.crm_deal import create_deal as crm_create_deal

	if not frappe.has_permission("CRM Deal", "create"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	data = frappe.parse_json(data) or {}
	allowed = ("organization", "lead_name", "mobile_no", "email", "deal_value", "status", "deal_owner")
	values = {k: data.get(k) for k in allowed if data.get(k) not in (None, "")}
	values.setdefault("deal_owner", frappe.session.user)
	organization = values.pop("organization", None)
	if organization:
		if frappe.db.exists("CRM Organization", organization):
			values["organization"] = organization
		else:
			values["organization_name"] = organization
	if values.get("lead_name"):
		first, _sep, last = values["lead_name"].strip().partition(" ")
		values.update(first_name=first, last_name=last.strip() or None)
	name = crm_create_deal(values)
	return record_row(frappe.get_doc("CRM Deal", name))


@frappe.whitelist(methods=["POST"])
@formatted
def add_comment(doctype: str, name: str, content: str) -> dict:
	"""Comment typed in the app (plain text), through crm's add_comment (mentions, notifications)."""
	from crm.api.comment import add_comment as crm_add_comment

	get_crm_doc(doctype, name)
	if not (content or "").strip():
		frappe.throw(_("Comment is empty"))
	html = "".join(f"<p>{escape_html(line)}</p>" for line in content.strip().splitlines() if line.strip())
	comment = crm_add_comment(doctype, name, html)
	return {f: comment.get(f) for f in ("name", "content", "owner", "creation")}


@frappe.whitelist(methods=["POST"])
@formatted
def update_note(name: str, title: str | None = None, content: str | None = None) -> dict:
	note = frappe.get_doc("FCRM Note", name)
	note.check_permission("write")
	if title is not None:
		note.title = title
	if content is not None:
		note.content = "".join(
			f"<p>{escape_html(line)}</p>" for line in content.strip().splitlines() if line.strip()
		)
	note.save()
	return {f: note.get(f) for f in ("name", "title", "content", "owner", "creation")}


@frappe.whitelist(methods=["POST"])
def delete_note(name: str) -> None:
	frappe.delete_doc("FCRM Note", name)


# Contacts and organizations
# --------------------------


@frappe.whitelist()
@formatted
def list_contacts(search: str | None = None, start: int = 0, page_length: int = 20) -> dict:
	search = (search or "").strip()
	return paged(
		frappe.get_list,
		"Contact",
		fields=CONTACT_FIELDS,
		or_filters=search_filters(search, ("full_name", "email_id", "mobile_no", "company_name")),
		order_by="modified desc",
		start=start,
		page_length=page_length,
	)


@frappe.whitelist()
@formatted
def get_contact(name: str) -> dict:
	"""A contact with its deals (CRM Contacts rows) and open leads with the same email or mobile."""
	contact = frappe.get_doc("Contact", name)
	contact.check_permission("read")
	deal_names = frappe.get_all(
		"CRM Contacts", filters={"contact": name, "parenttype": "CRM Deal"}, pluck="parent", distinct=True
	)
	deals = (
		frappe.get_list(
			"CRM Deal",
			fields=DEAL_FIELDS,
			filters={"name": ["in", deal_names]},
			order_by="modified desc",
			limit=50,
		)
		if deal_names
		else []
	)
	or_filters = []
	if contact.email_id:
		or_filters.append(["email", "=", contact.email_id])
	if contact.mobile_no:
		or_filters.append(["mobile_no", "=", contact.mobile_no])
	leads = (
		frappe.get_list(
			"CRM Lead",
			fields=LEAD_FIELDS,
			filters={"converted": 0},
			or_filters=or_filters,
			order_by="modified desc",
			limit=50,
		)
		if or_filters
		else []
	)
	return {"doc": contact_row(contact, detail=True), "deals": deals, "leads": leads}


@frappe.whitelist(methods=["POST"])
@formatted
def create_contact(data: dict | str) -> dict:
	"""Keys: first_name, last_name, email_id, mobile_no, company_name."""
	data = frappe.parse_json(data) or {}
	if not (data.get("first_name") or "").strip():
		frappe.throw(_("First name is required"))
	contact = frappe.new_doc("Contact")
	contact.update(contact_values(data))
	if data.get("email_id"):
		contact.append("email_ids", {"email_id": data["email_id"].strip(), "is_primary": 1})
	if data.get("mobile_no"):
		contact.append("phone_nos", {"phone": data["mobile_no"].strip(), "is_primary_mobile_no": 1})
	contact.insert()
	return contact_row(contact)


@frappe.whitelist(methods=["POST"])
@formatted
def update_contact(name: str, data: dict | str) -> dict:
	"""Same keys as create_contact. A new email / mobile becomes the primary one."""
	data = frappe.parse_json(data) or {}
	contact = frappe.get_doc("Contact", name)
	contact.check_permission("write")
	contact.update(contact_values(data))
	if data.get("email_id"):
		set_primary_row(contact, "email_ids", "email_id", data["email_id"].strip(), "is_primary")
	if data.get("mobile_no"):
		set_primary_row(contact, "phone_nos", "phone", data["mobile_no"].strip(), "is_primary_mobile_no")
	contact.save()
	return contact_row(contact, detail=True)


def search_filters(search: str, fields) -> list | None:
	return [[f, "like", f"%{search}%"] for f in fields] if search else None


def contact_values(data: dict) -> dict:
	keys = ("first_name", "last_name", "company_name", "designation", "salutation", "gender")
	return {k: (data[k] or None) for k in keys if k in data}


def set_primary_row(doc, table: str, field: str, value: str, flag: str) -> None:
	rows = doc.get(table)
	if not any(r.get(field) == value for r in rows):
		doc.append(table, {field: value})
	for r in doc.get(table):
		r.set(flag, 1 if r.get(field) == value else 0)


def contact_row(contact, detail: bool = False) -> dict:
	row = {f: contact.get(f) for f in CONTACT_FIELDS}
	if detail:
		row.update({f: contact.get(f) for f in CONTACT_DETAIL_FIELDS})
		row["email_ids"] = [{"email_id": e.email_id, "is_primary": e.is_primary} for e in contact.email_ids]
		row["phone_nos"] = [
			{
				"phone": p.phone,
				"is_primary_mobile_no": p.is_primary_mobile_no,
				"is_primary_phone": p.is_primary_phone,
			}
			for p in contact.phone_nos
		]
	return row


@frappe.whitelist()
@formatted
def list_organizations(search: str | None = None, start: int = 0, page_length: int = 20) -> dict:
	search = (search or "").strip()
	return paged(
		frappe.get_list,
		"CRM Organization",
		fields=ORGANIZATION_FIELDS,
		or_filters=search_filters(search, ("organization_name", "website", "industry", "territory")),
		order_by="modified desc",
		start=start,
		page_length=page_length,
	)


@frappe.whitelist()
@formatted
def get_organization(name: str) -> dict:
	org = frappe.get_doc("CRM Organization", name)
	org.check_permission("read")
	return {
		"doc": {f: org.get(f) for f in ORGANIZATION_FIELDS + ORGANIZATION_DETAIL_FIELDS},
		"deals": frappe.get_list(
			"CRM Deal", fields=DEAL_FIELDS, filters={"organization": name}, order_by="modified desc", limit=50
		),
		"contacts": frappe.get_list(
			"Contact",
			fields=CONTACT_FIELDS,
			filters={"company_name": name},
			order_by="modified desc",
			limit=50,
		)
		if frappe.has_permission("Contact", "read")
		else [],
	}


ORGANIZATION_KEYS = (
	"organization_name",
	"website",
	"industry",
	"territory",
	"annual_revenue",
	"no_of_employees",
)


@frappe.whitelist(methods=["POST"])
@formatted
def create_organization(data: dict | str) -> dict:
	"""Keys: organization_name, website, industry, territory, annual_revenue, no_of_employees."""
	data = frappe.parse_json(data) or {}
	if not (data.get("organization_name") or "").strip():
		frappe.throw(_("Organization name is required"))
	org = frappe.get_doc(
		{
			"doctype": "CRM Organization",
			**{k: data[k] for k in ORGANIZATION_KEYS if data.get(k) not in (None, "")},
		}
	).insert()
	return {f: org.get(f) for f in ORGANIZATION_FIELDS}


@frappe.whitelist(methods=["POST"])
@formatted
def update_organization(name: str, data: dict | str) -> dict:
	"""Same keys as create_organization, except organization_name (the name of the record)."""
	data = frappe.parse_json(data) or {}
	org = frappe.get_doc("CRM Organization", name)
	org.check_permission("write")
	org.update({k: (data[k] or None) for k in ORGANIZATION_KEYS if k in data and k != "organization_name"})
	org.save()
	return {f: org.get(f) for f in ORGANIZATION_FIELDS + ORGANIZATION_DETAIL_FIELDS}


# Calendar
# --------


@frappe.whitelist()
@formatted
def list_agenda(date_from: str, date_to: str) -> list[dict]:
	"""My events and my tasks between two dates (inclusive), merged and sorted by time."""
	start = day_start(date_from)
	end = add_days(day_start(date_to or date_from), 1)
	if end <= start:
		frappe.throw(_("date_to must not be before date_from"))
	if (end - start).days > 366:
		frappe.throw(_("Ask for at most a year at a time"))
	return agenda_items(start, end)


def agenda_items(start, end) -> list[dict]:
	"""AgendaItems for the session user in [start, end)."""
	user = frappe.session.user
	# "mine" (owner, participant, assigned) is a subset of what Event's permission query allows
	events = frappe.db.sql(
		f"""select {", ".join(f"e.`{f}`" for f in EVENT_FIELDS)}
		from `tabEvent` e
		where e.starts_on < %(end)s and coalesce(e.ends_on, e.starts_on) >= %(start)s
			and (e.owner = %(user)s
				or e._assign like %(assign)s
				or exists (select 1 from `tabEvent Participants` p
					where p.parent = e.name and p.parenttype = 'Event' and p.email = %(user)s))
		order by e.starts_on asc
		limit 500""",
		{"start": start, "end": end, "user": user, "assign": f'%"{user}"%'},
		as_dict=True,
	)
	refs = event_references([e.name for e in events])
	items = [event_item(e, refs.get(e.name)) for e in events]

	tasks = frappe.get_list(
		"CRM Task",
		fields=TASK_FIELDS,
		filters=[
			["assigned_to", "=", user],
			["status", "!=", "Canceled"],
			["due_date", ">=", start],
			["due_date", "<", end],
		],
		order_by="due_date asc",
		limit=500,
	)
	titles = {}
	for t in tasks:
		key = (t.reference_doctype, t.reference_docname)
		if key not in titles:
			titles[key] = (
				record_title(*key) if t.reference_doctype in CRM_DOCTYPES and t.reference_docname else None
			)
		items.append(
			{
				"kind": "task",
				"name": t.name,
				"title": t.title,
				"start": t.due_date,
				"end": None,
				"all_day": 0,
				"status": t.status,
				"reference_doctype": t.reference_doctype,
				"reference_docname": t.reference_docname,
				"reference_title": titles[key],
			}
		)
	items.sort(key=lambda i: (get_datetime(i["start"]), i["kind"] != "event" or not i["all_day"]))
	return items


def event_references(names: list[str]) -> dict:
	"""The first lead / deal participant of each event, with its title."""
	if not names:
		return {}
	refs = {}
	for p in frappe.get_all(
		"Event Participants",
		filters={"parenttype": "Event", "parent": ["in", names], "reference_doctype": ["in", CRM_DOCTYPES]},
		fields=["parent", "reference_doctype", "reference_docname"],
		order_by="idx asc",
	):
		if p.parent not in refs and p.reference_docname:
			refs[p.parent] = (
				p.reference_doctype,
				p.reference_docname,
				record_title(p.reference_doctype, p.reference_docname),
			)
	return refs


def event_item(event, ref=None) -> dict:
	ref = ref or (None, None, None)
	return {
		"kind": "event",
		"name": event.name,
		"title": event.subject,
		"start": event.starts_on,
		"end": event.ends_on,
		"all_day": cint(event.all_day),
		"status": event.status,
		"reference_doctype": ref[0],
		"reference_docname": ref[1],
		"reference_title": ref[2],
	}


@frappe.whitelist(methods=["POST"])
@formatted
def create_event(
	subject: str,
	starts_on: str,
	ends_on: str | None = None,
	all_day: int = 0,
	description: str | None = None,
	reference_doctype: str | None = None,
	reference_docname: str | None = None,
) -> dict:
	"""A private Event owned by the session user, linked to a lead or deal as a participant."""
	if not (subject or "").strip():
		frappe.throw(_("Subject is required"))
	event = frappe.get_doc(
		{
			"doctype": "Event",
			"subject": subject.strip(),
			"event_type": "Private",
			"event_category": "Event",
			"starts_on": get_datetime(starts_on),
			"ends_on": get_datetime(ends_on) if ends_on else None,
			"all_day": cint(all_day),
			"description": description,
			"status": "Open",
		}
	)
	if reference_doctype or reference_docname:
		get_crm_doc(reference_doctype, reference_docname)
		event.add_participant(reference_doctype, reference_docname)
	event.insert()
	return event_agenda_item(event)


@frappe.whitelist(methods=["POST"])
@formatted
def update_event(
	name: str,
	subject: str | None = None,
	starts_on: str | None = None,
	ends_on: str | None = None,
	all_day: int | None = None,
	description: str | None = None,
	status: str | None = None,
	reference_doctype: str | None = None,
	reference_docname: str | None = None,
) -> dict:
	"""Owner only. Values not sent are kept; `ends_on=""` clears the end, a new reference replaces the old."""
	event = get_own_event(name)
	if subject is not None:
		if not subject.strip():
			frappe.throw(_("Subject is required"))
		event.subject = subject.strip()
	if starts_on:
		event.starts_on = get_datetime(starts_on)
	if ends_on is not None:
		event.ends_on = get_datetime(ends_on) if ends_on else None
	if all_day is not None:
		event.all_day = cint(all_day)
	if description is not None:
		event.description = description
	if status:
		event.status = status
	if reference_doctype and reference_docname:
		get_crm_doc(reference_doctype, reference_docname)
		event.event_participants = [
			p for p in event.event_participants if p.reference_doctype not in CRM_DOCTYPES
		]
		event.add_participant(reference_doctype, reference_docname)
	event.save()
	return event_agenda_item(event)


@frappe.whitelist(methods=["POST"])
def delete_event(name: str) -> None:
	get_own_event(name)
	# Event gives Desk Users no delete permission; the owner check above stands in for it
	frappe.delete_doc("Event", name, ignore_permissions=True)


def get_own_event(name: str):
	event = frappe.get_doc("Event", name)
	if event.owner != frappe.session.user:
		frappe.throw(_("Only the person who created this event can change it"), frappe.PermissionError)
	return event


def event_agenda_item(event) -> dict:
	return event_item(event, event_references([event.name]).get(event.name))


# Profile
# -------

PROFILE_FIELDS = ["name", "full_name", "first_name", "last_name", "email", "mobile_no", "user_image"]


@frappe.whitelist()
def get_profile() -> dict:
	user = frappe.session.user
	if user == "Guest":
		raise frappe.PermissionError
	row = frappe.db.get_value("User", user, PROFILE_FIELDS, as_dict=True)
	row["roles"] = [r for r in frappe.get_roles(user) if r in CRM_ROLES]
	row["is_manager"] = is_manager(user)
	return row


@frappe.whitelist(methods=["POST"])
def update_profile(
	first_name: str | None = None, last_name: str | None = None, mobile_no: str | None = None
) -> dict:
	"""Update the session user's own name and mobile; an optional multipart `file` becomes the photo."""
	user = frappe.session.user
	if user == "Guest":
		raise frappe.PermissionError
	upload = uploaded_file()
	if upload:
		check_extension(upload[0], IMAGE_EXTENSIONS)
	values = {}
	if first_name is not None:
		if not first_name.strip():
			frappe.throw(_("First name is required"))
		values["first_name"] = first_name.strip()
	if last_name is not None:
		values["last_name"] = last_name.strip() or None
	if mobile_no is not None:
		if mobile_no.strip():
			from abm_crm.api.whatsapp import to_whatsapp_number

			values["mobile_no"] = "+" + to_whatsapp_number(mobile_no)
		else:
			values["mobile_no"] = None
	if values or upload:
		doc = frappe.get_doc("User", user)
		doc.update(values)
		if upload:
			# public, like profile photos uploaded on the web, so other users can see it
			file = attach_file(upload[0], upload[1], "User", user, "user_image", is_private=0)
			doc.user_image = file.file_url
		# the user's own record and only these fields; Sales Users have no User write permission
		doc.save(ignore_permissions=True)
	return get_profile()
