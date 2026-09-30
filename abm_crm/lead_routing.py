"""Lead routing: assign new leads by campaign, ad, form, source or any other condition.

Runs on CRM Lead.before_insert (see hooks.py):
1. For Facebook leads, fetch campaign / ad set / ad from the Graph API and store them on the lead.
2. Find the first enabled ABM Lead Routing Rule (highest priority first) that matches the lead.
3. Pick a user from that rule (round robin or load balancing, respecting per-user limits) and set
   `lead_owner`. crm's own after_insert then assigns and shares the lead with that user.

Leads that already have a lead_owner are left alone. Leads no rule matches fall through to
Frappe's normal Assignment Rules, which also skip leads that are already assigned.
"""

import frappe
from frappe import _
from frappe.integrations.utils import make_get_request
from frappe.utils import cint

from crm.lead_syncing.doctype.lead_sync_source.facebook import get_fb_graph_api_url

ATTRIBUTION_FIELDS = (
	"abm_campaign",
	"abm_campaign_id",
	"abm_adset",
	"abm_adset_id",
	"abm_ad",
	"abm_ad_id",
	"abm_platform",
	"abm_lead_sync_source",
)
OPEN_STATUS_TYPES = ("Open", "Ongoing")
FB_PLATFORMS = {"fb": "Facebook", "ig": "Instagram", "msgr": "Messenger", "wa": "WhatsApp"}


# Hooks
# -----


def before_insert_lead(doc, method=None):
	if doc.facebook_form_id and not doc.get("abm_lead_sync_source"):
		doc.abm_lead_sync_source = frappe.db.get_value(
			"Lead Sync Source", {"facebook_lead_form": doc.facebook_form_id}, "name"
		)
	if doc.facebook_lead_id and not doc.get("abm_campaign_id"):
		set_facebook_attribution(doc)
	if doc.facebook_lead_id and not doc.get("abm_platform"):
		doc.abm_platform = "Facebook"

	if doc.lead_owner or doc.flags.skip_lead_routing:
		return

	result = route(doc)
	if result:
		doc.lead_owner = result["user"]
		doc.abm_routing_rule = result["rule"]


def before_insert_deal(doc, method=None):
	"""Carry campaign attribution from the lead to the deal it was converted into."""
	if not doc.get("lead"):
		return
	values = frappe.db.get_value("CRM Lead", doc.lead, [*ATTRIBUTION_FIELDS, "abm_routing_rule"], as_dict=True)
	for field, value in (values or {}).items():
		if value and not doc.get(field):
			doc.set(field, value)


# Facebook attribution
# --------------------


def set_facebook_attribution(doc):
	"""Fill campaign, ad set and ad on a Facebook lead. Never blocks the lead from being created."""
	token = get_sync_source_token(doc.abm_lead_sync_source)
	if not token:
		return

	data = fetch_facebook_lead(doc.facebook_lead_id, token)
	if not data:
		return

	doc.abm_campaign_id = data.get("campaign_id")
	doc.abm_campaign = data.get("campaign_name") or data.get("campaign_id")
	doc.abm_adset_id = data.get("adset_id")
	doc.abm_adset = data.get("adset_name") or data.get("adset_id")
	doc.abm_ad_id = data.get("ad_id")
	doc.abm_ad = data.get("ad_name") or data.get("ad_id")
	if data.get("platform"):
		doc.abm_platform = FB_PLATFORMS.get(data["platform"], data["platform"])


def get_sync_source_token(sync_source: str | None) -> str | None:
	if not sync_source:
		return None
	return frappe.get_doc("Lead Sync Source", sync_source).get_password("access_token", raise_exception=False)


def fetch_facebook_lead(lead_id: str, token: str) -> dict | None:
	# names need ads_read on the ad account; ids come with leads_retrieval alone, so fall back to ids
	field_sets = (
		"campaign_id,campaign_name,adset_id,adset_name,ad_id,ad_name,platform",
		"campaign_id,adset_id,ad_id,platform",
	)
	url = get_fb_graph_api_url(f"/{lead_id}")
	for fields in field_sets:
		try:
			return make_get_request(url, params={"access_token": token, "fields": fields})
		except Exception:
			continue
	frappe.log_error(f"Could not fetch campaign details for Facebook lead {lead_id}", "ABM Lead Routing")
	return None


# Routing
# -------


def route(doc, dry_run: bool = False) -> dict | None:
	"""Return {"rule", "user"} for the first matching rule that has an available user."""
	lead = frappe._dict(doc.as_dict())
	for rule in get_enabled_rules():
		if not rule_matches(rule, lead):
			continue
		user = pick_user(rule, dry_run=dry_run)
		if user:
			return {"rule": rule.name, "user": user}
	return None


def get_enabled_rules() -> list:
	names = frappe.get_all(
		"ABM Lead Routing Rule",
		filters={"enabled": 1},
		order_by="priority desc, creation asc",
		pluck="name",
	)
	return [frappe.get_doc("ABM Lead Routing Rule", name) for name in names]


def rule_matches(rule, lead) -> bool:
	exact_checks = (
		(rule.lead_source, lead.source),
		(rule.lead_sync_source, lead.abm_lead_sync_source),
		(rule.facebook_lead_form, lead.facebook_form_id),
		(rule.territory, lead.territory),
	)
	for expected, actual in exact_checks:
		if expected and expected != actual:
			return False

	if rule.platform and (rule.platform or "").lower() != (lead.abm_platform or "").lower():
		return False

	text_checks = (
		(rule.campaign, (lead.abm_campaign, lead.abm_campaign_id)),
		(rule.adset, (lead.abm_adset, lead.abm_adset_id)),
		(rule.ad, (lead.abm_ad, lead.abm_ad_id)),
	)
	for patterns, values in text_checks:
		if patterns and not text_matches(patterns, values, rule.campaign_match):
			return False

	if rule.condition:
		try:
			if not frappe.safe_eval(rule.condition, None, {"doc": lead}):
				return False
		except Exception:
			frappe.log_error(f"Extra Condition failed in rule {rule.name}", "ABM Lead Routing")
			return False

	return True


def text_matches(patterns: str, values, mode: str | None) -> bool:
	"""True if any comma/newline separated pattern matches any of the values (case-insensitive)."""
	wanted = [p.strip().lower() for p in patterns.replace("\n", ",").split(",") if p.strip()]
	actual = [str(v).strip().lower() for v in values if v]
	for pattern in wanted:
		for value in actual:
			if mode == "Equals" and value == pattern:
				return True
			if mode == "Starts With" and value.startswith(pattern):
				return True
			if mode not in ("Equals", "Starts With") and pattern in value:
				return True
	return False


def pick_user(rule, dry_run: bool = False) -> str | None:
	rows = [row for row in rule.users if row.active and row.user]
	enabled = set(
		frappe.get_all("User", filters={"name": ["in", [r.user for r in rows]], "enabled": 1}, pluck="name")
	)
	rows = [row for row in rows if row.user in enabled]
	load = get_open_lead_counts([row.user for row in rows])
	available = [row for row in rows if not cint(row.max_open_leads) or load[row.user] < cint(row.max_open_leads)]

	user = None
	if available:
		if rule.strategy == "Load Balancing":
			user = min(available, key=lambda row: load[row.user]).user
		else:
			users = [row.user for row in available]
			last = rule.last_user if rule.last_user in [r.user for r in rows] else None
			order = list(dict.fromkeys(r.user for r in rows))  # unique, keeps list order
			start = order.index(last) + 1 if last else 0
			# next available user after the last assigned one, wrapping around
			for user in order[start:] + order[:start]:
				if user in users:
					break
	elif rule.fallback_user:
		user = rule.fallback_user

	if user and not dry_run:
		frappe.db.sql(
			"""update `tabABM Lead Routing Rule`
			set last_user=%s, assigned_count=assigned_count+1 where name=%s""",
			(user, rule.name),
		)
	return user


def get_open_lead_counts(users: list[str]) -> dict:
	counts = dict.fromkeys(users, 0)
	if not users:
		return counts
	open_statuses = frappe.get_all(
		"CRM Lead Status", filters={"type": ["in", OPEN_STATUS_TYPES]}, pluck="name"
	)
	if not open_statuses:
		return counts
	rows = frappe.db.sql(
		"""select lead_owner, count(*) as count from `tabCRM Lead`
		where lead_owner in %(users)s and converted = 0 and status in %(statuses)s
		group by lead_owner""",
		{"users": users, "statuses": open_statuses},
		as_dict=True,
	)
	for row in rows:
		counts[row.lead_owner] = row.count
	return counts
