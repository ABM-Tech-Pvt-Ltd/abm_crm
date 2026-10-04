import json
from unittest.mock import MagicMock, patch

import frappe
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from frappe.desk.form.assign_to import add as assign
from frappe.tests import IntegrationTestCase

from abm_crm import push
from abm_crm.api import mobile

REP = "push.rep@example.com"
REP2 = "push.rep2@example.com"
TOKEN = "push-test-token-1"
TOKEN2 = "push-test-token-2"


def make_user(email):
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
				"roles": [{"role": "Sales User"}],
			}
		).insert(ignore_permissions=True)


def private_key_pem():
	key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
	pem = key.private_bytes(
		serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
	).decode()
	return key, pem


def response(status, body=None):
	r = MagicMock()
	r.status_code = status
	r.ok = 200 <= status < 300
	r.json.return_value = body or {}
	r.text = json.dumps(body or {})
	return r


class TestDevices(IntegrationTestCase):
	def setUp(self):
		make_user(REP)
		make_user(REP2)

	def tearDown(self):
		frappe.set_user("Administrator")
		for name in frappe.get_all(
			"ABM Mobile Device", filters={"token": ["like", "push-test-token-%"]}, pluck="name"
		):
			frappe.delete_doc("ABM Mobile Device", name, ignore_permissions=True)

	def device(self, token):
		return frappe.db.get_value(
			"ABM Mobile Device", {"token": token}, ["user", "enabled", "device_name"], as_dict=True
		)

	def test_register_move_unregister(self):
		frappe.set_user(REP)
		mobile.register_device(TOKEN, device_name="Pixel")
		mobile.register_device(TOKEN, device_name="Pixel 8")  # upsert, no duplicate
		self.assertEqual(frappe.db.count("ABM Mobile Device", {"token": TOKEN}), 1)
		self.assertEqual(self.device(TOKEN).device_name, "Pixel 8")

		# the phone is handed to another rep
		frappe.set_user(REP2)
		mobile.register_device(TOKEN)
		self.assertEqual(self.device(TOKEN).user, REP2)

		# REP can no longer remove it
		frappe.set_user(REP)
		mobile.unregister_device(TOKEN)
		self.assertTrue(self.device(TOKEN))

		frappe.set_user(REP2)
		mobile.unregister_device(TOKEN)
		self.assertIsNone(self.device(TOKEN))

	def test_logout_disables_devices(self):
		frappe.set_user(REP)
		mobile.register_device(TOKEN)
		mobile.register_device(TOKEN2)
		mobile.logout(token=TOKEN)
		self.assertEqual(self.device(TOKEN).enabled, 0)
		self.assertEqual(self.device(TOKEN2).enabled, 0)
		mobile.register_device(TOKEN)
		self.assertEqual(self.device(TOKEN).enabled, 1)

	def test_rejects_bad_input(self):
		frappe.set_user(REP)
		self.assertRaises(frappe.ValidationError, mobile.register_device, " ")
		self.assertRaises(frappe.ValidationError, mobile.register_device, TOKEN, "windows")


class TestPush(IntegrationTestCase):
	def setUp(self):
		make_user(REP)
		make_user(REP2)
		self.key, pem = private_key_pem()
		self.info = {
			"type": "service_account",
			"project_id": "abm-test",
			"private_key_id": "kid1",
			"private_key": pem,
			"client_email": "fcm@abm-test.iam.gserviceaccount.com",
		}
		frappe.db.set_single_value("ABM CRM Settings", "fcm_service_account", json.dumps(self.info))
		frappe.db.set_single_value("ABM CRM Settings", "push_enabled", 1)
		frappe.set_user(REP)
		mobile.register_device(TOKEN)
		mobile.register_device(TOKEN2)
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.set_single_value("ABM CRM Settings", "fcm_service_account", None)
		push.clear_token_cache()
		for name in frappe.get_all(
			"ABM Mobile Device", filters={"token": ["like", "push-test-token-%"]}, pluck="name"
		):
			frappe.delete_doc("ABM Mobile Device", name, ignore_permissions=True)

	def test_send_push_enqueues_on_short_queue(self):
		with patch("frappe.enqueue") as enqueue:
			self.assertTrue(push.send_push(REP, "Hi", "Body", {"doctype": "CRM Lead"}))
		args, kwargs = enqueue.call_args
		self.assertEqual(args[0], "abm_crm.push.deliver")
		self.assertEqual(kwargs["queue"], "short")
		self.assertTrue(kwargs["enqueue_after_commit"])
		self.assertEqual(kwargs["user"], REP)

	def test_not_configured_is_a_no_op(self):
		frappe.db.set_single_value("ABM CRM Settings", "fcm_service_account", None)
		with patch("frappe.enqueue") as enqueue:
			self.assertFalse(push.send_push(REP, "Hi", "Body"))
		enqueue.assert_not_called()
		frappe.db.set_single_value("ABM CRM Settings", "fcm_service_account", json.dumps(self.info))
		frappe.db.set_single_value("ABM CRM Settings", "push_enabled", 0)
		self.assertFalse(push.send_push(REP, "Hi", "Body"))

	def test_deliver_composes_message_and_disables_unregistered(self):
		unregistered = {"error": {"status": "NOT_FOUND", "details": [{"errorCode": "UNREGISTERED"}]}}

		def fake_post(url, json=None, headers=None, timeout=None):
			return response(200) if json["message"]["token"] == TOKEN else response(404, unregistered)

		with (
			patch.object(push, "get_access_token", return_value="access-1"),
			patch.object(push.requests, "post", side_effect=fake_post) as post,
		):
			results = push.deliver(REP, "New lead assigned", "Lead X", {"doctype": "CRM Lead", "n": 5})

		self.assertEqual(post.call_count, 2)
		url = post.call_args_list[0].args[0]
		self.assertEqual(url, "https://fcm.googleapis.com/v1/projects/abm-test/messages:send")
		sent = {c.kwargs["json"]["message"]["token"]: c.kwargs for c in post.call_args_list}
		message = sent[TOKEN]["json"]["message"]
		self.assertEqual(sent[TOKEN]["headers"]["Authorization"], "Bearer access-1")
		self.assertEqual(message["notification"], {"title": "New lead assigned", "body": "Lead X"})
		self.assertEqual(message["data"], {"doctype": "CRM Lead", "n": "5"})
		self.assertEqual(message["android"]["priority"], "high")
		self.assertEqual(message["android"]["notification"]["channel_id"], "default")

		self.assertEqual(len([r for r in results if r["ok"]]), 1)
		self.assertEqual(frappe.db.get_value("ABM Mobile Device", {"token": TOKEN}, "enabled"), 1)
		self.assertEqual(frappe.db.get_value("ABM Mobile Device", {"token": TOKEN2}, "enabled"), 0)

	def test_jwt_access_token_and_cache(self):
		def fake_post(url, data=None, timeout=None):
			claims = jwt.decode(
				data["assertion"],
				self.key.public_key(),
				algorithms=["RS256"],
				audience="https://oauth2.googleapis.com/token",
			)
			self.assertEqual(claims["iss"], self.info["client_email"])
			self.assertEqual(claims["scope"], push.FCM_SCOPE)
			self.assertEqual(jwt.get_unverified_header(data["assertion"])["kid"], "kid1")
			return response(200, {"access_token": "jwt-token", "expires_in": 3600})

		with patch.object(push.requests, "post", side_effect=fake_post) as post:
			self.assertEqual(push.fetch_access_token_with_jwt(self.info), "jwt-token")
		self.assertEqual(post.call_count, 1)

		with patch.object(push, "fetch_access_token", return_value="cached-token") as fetch:
			push.clear_token_cache()
			self.assertEqual(push.get_access_token(self.info), "cached-token")
			self.assertEqual(push.get_access_token(self.info), "cached-token")
		fetch.assert_called_once()

	def test_crm_notification_pushes_to_assignee(self):
		lead = frappe.get_doc(
			{"doctype": "CRM Lead", "first_name": "Push Test", "lead_owner": REP2}
		).insert(ignore_permissions=True)
		with patch.object(push, "send_push") as send:
			# crm creates an Assignment CRM Notification for the assignee
			assign({"assign_to": [REP], "doctype": "CRM Lead", "name": lead.name})
		pushes = [c for c in send.call_args_list if c.args[0] == REP]
		self.assertEqual(len(pushes), 1)
		user, title, body, data = pushes[0].args
		self.assertEqual(title, "New lead assigned")
		self.assertIn("Push Test", body)
		self.assertNotIn("<", body)
		self.assertEqual(data, {"doctype": "CRM Lead", "name": lead.name, "type": "Assignment"})

	def test_no_push_to_the_user_who_caused_it(self):
		doc = frappe._dict(
			to_user=REP, from_user=REP, type="Mention", reference_doctype="CRM Lead", reference_name="x"
		)
		with patch.object(push, "send_push") as send:
			push.on_crm_notification(doc)
		send.assert_not_called()
