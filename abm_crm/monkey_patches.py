"""Runtime fixes for upstream crm bugs.

Applied from the `before_request` and `before_job` hooks in hooks.py, so every web process and
every background worker has them. Kept here, not edited in apps/crm, so the fixes survive
`bench update` and ship with abm_crm.
"""

import frappe


def apply(**_hook_kwargs) -> None:
	"""Apply all patches. Idempotent and never raises: a failure here must not break requests or jobs.

	`before_job` passes method, kwargs and transaction_type, which are ignored.
	"""
	try:
		patch_facebook_blank_fields()
	except Exception:
		frappe.log_error(title="abm_crm monkey patch failed")


def patch_facebook_blank_fields() -> None:
	"""Facebook lead sync fails on a blank optional field. Two crashes in crm, same cause.

	A field left empty on the lead form comes back with no "values" key, e.g. {"name": "email"}.

	1. sync_single_lead does item["values"][0] for every field -> KeyError: 'values', which fails
	   the whole sync job. Fixed by dropping blank fields before crm parses the lead.
	2. validate_duplicate_lead then reads lead_data[<every mapped crm field>] -> KeyError: 'email'.
	   crm catches that and writes a Failed Lead Sync Log, so the lead is silently never created.
	   Fixed by checking duplicates on Facebook's own lead id, plus the contact fields that are
	   present.
	"""
	try:
		from crm.lead_syncing.doctype.lead_sync_source import facebook
	except Exception:
		return

	cls = facebook.FacebookSyncSource
	if getattr(cls, "_abm_blank_fields_patched", False):
		return

	original_sync_single_lead = cls.sync_single_lead

	def sync_single_lead(self, lead, raise_exception=False):
		field_data = [item for item in (lead.get("field_data") or []) if item.get("values")]
		lead = {**lead, "field_data": field_data}
		return original_sync_single_lead(self, lead, raise_exception=raise_exception)

	def validate_duplicate_lead(self, lead_data: dict, field_mapping: dict):
		# the Facebook lead id is unique per submission, so it is an exact duplicate check
		lead_id = lead_data.get("facebook_lead_id")
		if lead_id and frappe.db.exists("CRM Lead", {"facebook_lead_id": lead_id}):
			raise facebook.DuplicateLeadError

		# same person re-submitting this form: match on the mapped fields that were filled in
		filters = {f: lead_data[f] for f in field_mapping.values() if lead_data.get(f)}
		if not set(filters) - {"first_name"}:
			return  # only a name: too weak to call it a duplicate
		filters["facebook_form_id"] = lead_data["facebook_form_id"]  # only for this campaign
		if frappe.db.exists("CRM Lead", filters):
			raise facebook.DuplicateLeadError

	cls.sync_single_lead = sync_single_lead
	cls.validate_duplicate_lead = validate_duplicate_lead
	cls._abm_blank_fields_patched = True
