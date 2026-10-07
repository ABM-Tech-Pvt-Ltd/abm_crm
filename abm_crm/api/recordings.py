"""Call recordings in formats browsers can't play (AMR: .amr/.awb/.3gp) converted to AAC .m4a.

The mobile app (1.5.1+) converts on the phone before uploading. This covers recordings sent by
older app versions and those already stored. Needs ffmpeg on the server; without it, files are
kept as they are (they still play in the mobile app).

Convert what is already stored:
    bench --site <site> execute abm_crm.api.recordings.convert_existing
"""

import os
import shutil
import subprocess
import tempfile

import frappe

BROWSER_UNPLAYABLE = ("amr", "awb", "3gp")


def needs_conversion(filename: str) -> bool:
	return filename.rsplit(".", 1)[-1].lower() in BROWSER_UNPLAYABLE if "." in filename else False


def to_m4a(filename: str, content: bytes) -> tuple[str, bytes]:
	"""(filename, content) as AAC .m4a, or unchanged when ffmpeg is missing or fails."""
	if not needs_conversion(filename) or not shutil.which("ffmpeg"):
		return filename, content
	with tempfile.TemporaryDirectory() as tmp:
		src = os.path.join(tmp, "in." + filename.rsplit(".", 1)[-1].lower())
		dst = os.path.join(tmp, "out.m4a")
		with open(src, "wb") as f:
			f.write(content)
		try:
			subprocess.run(
				["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-c:a", "aac", "-b:a", "48k", dst],
				check=True,
				timeout=120,
			)
		except Exception:
			frappe.log_error(title="ABM recording conversion failed", message=frappe.get_traceback())
			return filename, content
		with open(dst, "rb") as f:
			return filename.rsplit(".", 1)[0] + ".m4a", f.read()


def convert_existing(limit: int = 500) -> dict:
	"""Convert stored AMR recordings on CRM Call Logs to .m4a and point the call logs at them."""
	if not shutil.which("ffmpeg"):
		return {"converted": 0, "error": "ffmpeg is not installed on this server"}
	from abm_crm.api.mobile import attach_file

	converted = 0
	logs = frappe.get_all(
		"CRM Call Log",
		filters=[["recording_url", "is", "set"]],
		fields=["name", "recording_url"],
		limit=limit,
	)
	for log in logs:
		if not needs_conversion(log.recording_url):
			continue
		file_name = frappe.db.get_value("File", {"file_url": log.recording_url}, "name")
		if not file_name:
			continue
		old = frappe.get_doc("File", file_name)
		new_name, content = to_m4a(old.file_name, old.get_content())
		if new_name == old.file_name:
			continue
		new = attach_file(new_name, content, "CRM Call Log", log.name, "recording_url", is_private=old.is_private)
		frappe.db.set_value("CRM Call Log", log.name, "recording_url", new.file_url)
		old.delete(ignore_permissions=True)
		frappe.db.commit()
		converted += 1
	return {"converted": converted}
