app_name = "abm_crm"
app_title = "Abm Crm"
app_publisher = "Aman Boora "
app_description = "Custom CRM by ABM Tech"
app_email = "aman.chaudharyboora@gmail.com"
app_license = "agpl-3.0"

# Apps
# ------------------

# abm_crm layers on top of Frappe CRM. It must be installed after crm so that
# abm_crm/www/crm.html shadows crm's page (Frappe searches installed apps in reverse order).
# Do not install crm_override on the same site: both apps claim the /crm route.
required_apps = ["crm"]

# Installation
# ------------

after_install = "abm_crm.setup.install.after_install"
after_migrate = "abm_crm.setup.install.after_migrate"

# Document Events
# ---------------
# These run in addition to crm's own handlers.

doc_events = {
	"Communication": {
		"before_insert": "abm_crm.api.email.validate_outgoing_sender",
	},
	"Email Account": {
		# before_validate: Email Account.validate() tests the login, so clean the password first
		"before_validate": "abm_crm.api.email_account.clean_account_password",
		# "Create lead from incoming email" off must really stop lead creation (see the function)
		"validate": "abm_crm.api.email_account.sync_lead_creation",
	},
	"CRM Lead": {
		"before_insert": "abm_crm.lead_routing.before_insert_lead",
	},
	"CRM Deal": {
		"before_insert": "abm_crm.lead_routing.before_insert_deal",
		# a deal converted from a lead keeps the lead's tags
		"after_insert": "abm_crm.api.tags.copy_lead_tags",
	},
	"CRM Notification": {
		# push to the mobile app (crm also creates these for lead/deal/task assignments)
		"after_insert": "abm_crm.push.on_crm_notification",
	},
}

# Fixtures
# --------
# Only export records that belong to this app's module. Custom fields are created in code
# (abm_crm/setup/install.py), so they are not exported here.

fixtures = [
	{"dt": "Property Setter", "filters": [["module", "=", "Abm Crm"]]},
	{"dt": "Client Script", "filters": [["module", "=", "Abm Crm"]]},
	{"dt": "Server Script", "filters": [["module", "=", "Abm Crm"]]},
]

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"cron": {
# 		"0 9 * * *": ["abm_crm.tasks.daily_digest.send"],
# 	},
# }

# Overriding Methods
# ------------------------------
#
override_whitelisted_methods = {
	# tests only what is enabled and returns the real error (see abm_crm/api/email_account.py)
	"crm.api.settings.create_email_account": "abm_crm.api.email_account.create_email_account",
	# send to the full international number and explain Meta's errors (see abm_crm/api/whatsapp.py)
	"crm.api.whatsapp.create_whatsapp_message": "abm_crm.api.whatsapp.create_whatsapp_message",
	"crm.api.whatsapp.send_whatsapp_template": "abm_crm.api.whatsapp.send_whatsapp_template",
}

# Extend DocType Class
# ------------------------------
# Prefer extend_doctype_class over override_doctype_class: it adds a mixin instead of
# replacing crm's class.
#
# extend_doctype_class = {
# 	"CRM Lead": "abm_crm.overrides.crm_lead.CRMLeadMixin",
# }
