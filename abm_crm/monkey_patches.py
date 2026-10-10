"""Runtime fixes for upstream crm bugs, applied when abm_crm loads (imported from hooks.py).

Kept here, not edited in apps/crm, so the fixes survive `bench update` and ship with abm_crm.
"""

import frappe


def apply() -> None:
	patch_facebook_blank_fields()


def patch_facebook_blank_fields() -> None:
	"""Facebook lead sync crashes on a blank optional field.

	A field left empty on the lead form comes back with no "values" key, e.g.
	{"name": "email"}. crm's sync_single_lead does item["values"][0] for every field, so one
	blank field raises KeyError and the whole sync job fails. Drop blank fields before crm parses.
	"""
	try:
		from crm.lead_syncing.doctype.lead_sync_source import facebook
	except Exception:
		return

	cls = facebook.FacebookSyncSource
	if getattr(cls, "_abm_blank_fields_patched", False):
		return

	original = cls.sync_single_lead

	def sync_single_lead(self, lead, raise_exception=False):
		field_data = [item for item in (lead.get("field_data") or []) if item.get("values")]
		lead = {**lead, "field_data": field_data}
		return original(self, lead, raise_exception=raise_exception)

	cls.sync_single_lead = sync_single_lead
	cls._abm_blank_fields_patched = True
