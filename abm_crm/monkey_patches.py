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
	for patch in (patch_facebook_blank_fields, patch_duplicate_call_rows):
		try:
			patch()
		except Exception:
			frappe.log_error(title="abm_crm monkey patch failed")


def patch_facebook_blank_fields() -> None:
	"""Facebook lead sync fails on a blank optional field. Two crashes in crm, same cause.

	A field left empty on the lead form comes back with no "values" key, e.g. {"name": "email"}.

	1. sync_single_lead does item["values"][0] for every field -> KeyError: 'values', which fails
	   the whole sync job. Fixed by dropping blank fields before crm parses the lead.
	2. validate_duplicate_lead then reads lead_data[<every mapped crm field>] -> KeyError: 'email'.
	   crm catches that and writes a Failed Lead Sync Log, so the lead is silently never created.
	   Fixed by checking duplicates on Facebook's own lead id only. People who submit twice are
	   kept and tagged "Duplicate" (abm_crm.duplicates).
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
		# the same Facebook submission comes back on every sync inside the re-check window; it is
		# already in the CRM, so skip it quietly (crm would log a "Duplicate" entry each time)
		if lead.get("id") and frappe.db.exists("CRM Lead", {"facebook_lead_id": lead["id"]}):
			return None
		field_data = [item for item in (lead.get("field_data") or []) if item.get("values")]
		lead = {**lead, "field_data": field_data}
		return original_sync_single_lead(self, lead, raise_exception=raise_exception)

	def validate_duplicate_lead(self, lead_data: dict, field_mapping: dict):
		# Only the exact same Facebook lead id is skipped. The same person submitting again (same
		# phone number) is created and tagged "Duplicate" by abm_crm.duplicates, so it stays visible.
		lead_id = lead_data.get("facebook_lead_id")
		if lead_id and frappe.db.exists("CRM Lead", {"facebook_lead_id": lead_id}):
			raise facebook.DuplicateLeadError

	cls.sync_single_lead = sync_single_lead
	cls.validate_duplicate_lead = validate_duplicate_lead
	cls._abm_blank_fields_patched = True


def patch_duplicate_call_rows() -> None:
	"""crm shows a call twice on a lead or deal when the call is both referenced and linked to it.

	get_linked_calls joins calls whose reference_docname is the record with calls that have a link to
	the record, without removing repeats. Calls saved with both (older abm_crm call syncs did)
	appear twice in the Calls tab and the activity feed. Remove repeats from the result.
	"""
	from functools import wraps

	from crm.api import activities

	if getattr(activities, "_abm_calls_deduped", False):
		return

	original = activities.get_linked_calls

	@wraps(original)
	def get_linked_calls(name: str):
		result = original(name)
		seen = set()
		unique = []
		for call in result.get("calls", []):
			if call.get("name") in seen:
				continue
			seen.add(call.get("name"))
			unique.append(call)
		result["calls"] = unique
		return result

	activities.get_linked_calls = get_linked_calls
	activities._abm_calls_deduped = True
