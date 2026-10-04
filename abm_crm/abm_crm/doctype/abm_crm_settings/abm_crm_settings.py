# Copyright (c) 2026, Aman Boora and contributors
# For license information, please see license.txt

import json

import frappe
from frappe import _
from frappe.model.document import Document


class ABMCRMSettings(Document):
	def validate(self):
		self.validate_fcm_service_account()

	def validate_fcm_service_account(self):
		if not (self.fcm_service_account or "").strip():
			return
		try:
			info = json.loads(self.fcm_service_account)
		except ValueError:
			frappe.throw(_("FCM Service Account must be the JSON key file downloaded from Firebase"))
		if not isinstance(info, dict):
			frappe.throw(_("FCM Service Account must be the JSON key file downloaded from Firebase"))
		missing = [k for k in ("project_id", "client_email", "private_key") if not info.get(k)]
		if missing:
			frappe.throw(_("FCM Service Account is missing {0}").format(", ".join(missing)))
		# a new key needs a new access token
		from abm_crm.push import clear_token_cache

		clear_token_cache()
