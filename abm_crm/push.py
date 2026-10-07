"""Push notifications to the ABM CRM mobile app through Firebase Cloud Messaging (HTTP v1).

`send_push` only queues a background job, so saving a document never waits on FCM. The job looks
up the user's enabled ABM Mobile Devices and sends one message per token. Tokens FCM reports as
gone (404 / UNREGISTERED) are disabled.

The service-account JSON is stored in ABM CRM Settings (`fcm_service_account`, System Manager only).
"""

import hashlib
import json
import re
import time

import frappe
import requests
from frappe.utils import strip_html
from frappe.utils.html_utils import unescape_html

FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SEND_URL = "https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
TOKEN_CACHE_PREFIX = "abm_crm:fcm_access_token:"
TOKEN_TTL = 50 * 60  # Google access tokens last an hour
REQUEST_TIMEOUT = 20

_warned_not_configured = False


def logger():
	return frappe.logger("abm_crm.push")


def send_push(user: str, title: str, body: str, data: dict | None = None) -> bool:
	"""Queue a push to every enabled device of `user`. Returns False when push is not set up."""
	if not user or user in ("Guest", "Administrator"):
		return False
	if not get_service_account():
		return False
	frappe.enqueue(
		"abm_crm.push.deliver",
		queue="short",
		enqueue_after_commit=True,
		user=user,
		title=title,
		body=body,
		data=data or {},
	)
	return True


def get_service_account() -> dict | None:
	"""The parsed service account, or None (logged once per worker) when push is off or not set up."""
	global _warned_not_configured
	settings = frappe.db.get_value(
		"ABM CRM Settings", None, ["push_enabled", "fcm_service_account"], as_dict=True
	) or {}
	info = None
	if settings.get("push_enabled") and (settings.get("fcm_service_account") or "").strip():
		try:
			info = json.loads(settings.fcm_service_account)
		except ValueError:
			info = None
		if not (isinstance(info, dict) and info.get("project_id") and info.get("private_key")):
			info = None
	if not info and not _warned_not_configured:
		_warned_not_configured = True
		logger().info("Push notifications are off or ABM CRM Settings has no FCM service account")
	return info


def deliver(user: str, title: str, body: str, data: dict | None = None) -> list[dict]:
	"""Background job: send the message to each of the user's enabled devices."""
	info = get_service_account()
	if not info:
		return []
	devices = frappe.get_all(
		"ABM Mobile Device", filters={"user": user, "enabled": 1}, fields=["name", "token"]
	)
	if not devices:
		return []
	access_token = get_access_token(info)
	url = SEND_URL.format(project_id=info["project_id"])
	headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
	results = []
	for device in devices:
		payload = {"message": build_message(device.token, title, body, data)}
		try:
			response = requests.post(url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
		except requests.RequestException as e:
			logger().warning(f"FCM request failed for {device.name}: {e}")
			results.append({"device": device.name, "ok": False})
			continue
		if response.ok:
			results.append({"device": device.name, "ok": True})
			continue
		if is_unregistered(response):
			frappe.db.set_value("ABM Mobile Device", device.name, "enabled", 0, update_modified=False)
			results.append({"device": device.name, "ok": False, "disabled": True})
		else:
			if response.status_code == 401:
				clear_token_cache()
			logger().warning(f"FCM error {response.status_code} for {device.name}: {response.text[:500]}")
			results.append({"device": device.name, "ok": False})
	return results


def build_message(token: str, title: str, body: str, data: dict | None = None) -> dict:
	return {
		"token": token,
		"notification": {"title": title or "", "body": body or ""},
		# FCM only accepts string values in data
		"data": {str(k): "" if v is None else str(v) for k, v in (data or {}).items()},
		"android": {
			"priority": "high",
			# the app's white status-bar icon (res/drawable/notification_icon) in the brand colour
			"notification": {
				"channel_id": "default",
				"sound": "default",
				"icon": "notification_icon",
				"color": "#ff6a00",
			},
		},
	}


def is_unregistered(response) -> bool:
	if response.status_code == 404:
		return True
	try:
		error = response.json().get("error") or {}
	except ValueError:
		return False
	if error.get("status") == "UNREGISTERED":
		return True
	return any(d.get("errorCode") == "UNREGISTERED" for d in error.get("details") or [])


# OAuth access token
# ------------------


def token_cache_key(info: dict) -> str:
	key = f"{info.get('client_email')}:{info.get('private_key_id') or info.get('private_key')}"
	return TOKEN_CACHE_PREFIX + hashlib.sha256(key.encode()).hexdigest()[:32]


def get_access_token(info: dict) -> str:
	key = token_cache_key(info)
	token = frappe.cache.get_value(key)
	if not token:
		token = fetch_access_token(info)
		frappe.cache.set_value(key, token, expires_in_sec=TOKEN_TTL)
	return token


def clear_token_cache() -> None:
	frappe.cache.delete_keys(TOKEN_CACHE_PREFIX)


def fetch_access_token(info: dict) -> str:
	try:
		from google.auth.transport.requests import Request
		from google.oauth2 import service_account
	except ImportError:
		return fetch_access_token_with_jwt(info)
	credentials = service_account.Credentials.from_service_account_info(info, scopes=[FCM_SCOPE])
	credentials.refresh(Request())
	return credentials.token


def fetch_access_token_with_jwt(info: dict) -> str:
	"""Service-account OAuth flow without google-auth: sign a JWT (RS256) and exchange it."""
	import jwt

	now = int(time.time())
	claims = {
		"iss": info["client_email"],
		"scope": FCM_SCOPE,
		"aud": info.get("token_uri") or TOKEN_URL,
		"iat": now,
		"exp": now + 3600,
	}
	headers = {"kid": info["private_key_id"]} if info.get("private_key_id") else None
	assertion = jwt.encode(claims, info["private_key"], algorithm="RS256", headers=headers)
	response = requests.post(
		info.get("token_uri") or TOKEN_URL,
		data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion},
		timeout=REQUEST_TIMEOUT,
	)
	response.raise_for_status()
	return response.json()["access_token"]


# Hooks
# -----

NOTIFICATION_TITLES = {
	"Mention": "You were mentioned",
	"Task": "Task update",
	"WhatsApp": "New WhatsApp message",
	"Automation": "CRM update",
}
ASSIGNMENT_TITLES = {
	"CRM Lead": "New lead assigned",
	"CRM Deal": "New deal assigned",
	"CRM Task": "New task assigned",
}


def on_crm_notification(doc, method=None):
	"""CRM Notification after_insert: push it to `to_user`, unless they caused it."""
	if not doc.to_user or doc.to_user in (doc.from_user, frappe.session.user):
		return
	title, body = notification_title(doc), notification_body(doc)
	data = {"doctype": doc.reference_doctype, "name": doc.reference_name, "type": doc.type}
	send_push(doc.to_user, title, body, data)


def notification_title(doc) -> str:
	if doc.type == "Assignment":
		# crm uses the same type when an assignment is removed; the ToDo is cancelled by then
		still_assigned = frappe.db.exists(
			"ToDo",
			{
				"reference_type": doc.notification_type_doctype,
				"reference_name": doc.notification_type_doc,
				"allocated_to": doc.to_user,
				"status": "Open",
			},
		)
		if doc.notification_type_doctype and doc.notification_type_doc and not still_assigned:
			return "Assignment removed"
		return ASSIGNMENT_TITLES.get(doc.notification_type_doctype, "New assignment")
	return NOTIFICATION_TITLES.get(doc.type, "ABM CRM")


def notification_body(doc) -> str:
	text = strip_html(doc.notification_text or "") or strip_html(doc.message or "")
	text = re.sub(r"\s+", " ", unescape_html(text)).strip()
	return text[:500]
