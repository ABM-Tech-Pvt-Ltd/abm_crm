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
	for patch in (patch_facebook_blank_fields, patch_facebook_sync_window, patch_duplicate_call_rows):
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


# Facebook leads created this long before the last sync are asked for again, in case Facebook makes
# a lead available late. Leads already in the CRM are skipped quietly (patch_facebook_blank_fields).
SYNC_OVERLAP_HOURS = 6


def patch_facebook_sync_window() -> None:
	"""crm's Facebook sync misses leads created between midnight and 05:30 IST.

	fetch_leads asks Facebook for leads created after get_timestamp(last_synced_at), and
	get_timestamp keeps only the date and reads it in the server's clock (UTC on most servers): the
	threshold is 00:00 UTC of the last sync's day, which is 05:30 IST. Once a sync has run after
	midnight IST, a lead created before 05:30 IST that day is older than the threshold and is never
	fetched, with no error anywhere.

	Fixed by asking from the exact last sync time (converted from the site's time zone to UTC) minus
	an overlap, and by following Facebook's paging.
	"""
	try:
		from crm.lead_syncing.doctype.lead_sync_source import facebook
	except Exception:
		return

	cls = facebook.FacebookSyncSource
	if getattr(cls, "_abm_sync_window_patched", False):
		return

	def fetch_leads(self, since=None):
		since = since or self.last_synced_at
		params = {"access_token": self.access_token, "fields": "id,created_time,field_data", "limit": 500}
		if since:
			params["filtering"] = frappe.as_json(
				[{"field": "time_created", "operator": "GREATER_THAN", "value": sync_threshold(since)}]
			)
		url = self.get_api_url(f"/{self.form_id}/leads")
		leads = []
		for _page in range(100):  # 50,000 leads at most per sync
			response = facebook.make_get_request(url, params=params)
			leads.extend(response.get("data", []))
			url = (response.get("paging") or {}).get("next")
			if not url:
				break
			params = None  # the next-page URL carries every parameter
		return leads

	cls.fetch_leads = fetch_leads
	cls._abm_sync_window_patched = True


def sync_threshold(last_synced_at) -> int:
	"""Unix time to ask Facebook from: the last sync (site time zone) minus SYNC_OVERLAP_HOURS."""
	from zoneinfo import ZoneInfo

	from frappe.utils import add_to_date, get_datetime, get_system_timezone

	local = get_datetime(last_synced_at)
	if local.tzinfo is None:
		local = local.replace(tzinfo=ZoneInfo(get_system_timezone()))
	return int(add_to_date(local, hours=-SYNC_OVERLAP_HOURS).timestamp())


@frappe.whitelist()
def resync_facebook_leads(days: int = 3, source: str | None = None) -> dict:
	"""Fetch the last `days` days of leads again for every Facebook Lead Sync Source (or one), to
	recover leads an earlier sync missed. Leads already in the CRM are skipped. Managers only."""
	from frappe.utils import add_days, cint, now_datetime

	from crm.lead_syncing.doctype.lead_sync_source.facebook import FacebookSyncSource

	frappe.only_for(("System Manager", "Sales Manager"))
	apply()
	filters = {"type": "Facebook", "enabled": 1}
	if source:
		filters["name"] = source
	since = add_days(now_datetime(), -max(cint(days), 1))
	result = {}
	for s in frappe.get_all("Lead Sync Source", filters=filters, fields=["name", "facebook_lead_form"]):
		if not s.facebook_lead_form:
			continue
		doc = frappe.get_doc("Lead Sync Source", s.name)
		sync = FacebookSyncSource(doc.get_password("access_token"), s.facebook_lead_form, source_name=s.name)
		before = frappe.db.count("CRM Lead", {"facebook_form_id": s.facebook_lead_form})
		for lead in sync.fetch_leads(since=since):
			sync.sync_single_lead(lead)
		frappe.db.commit()
		result[s.name] = frappe.db.count("CRM Lead", {"facebook_form_id": s.facebook_lead_form}) - before
	return {"created": result}


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
