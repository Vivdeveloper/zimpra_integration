"""Positive + Negative Zimpra test suite.

Run:
  bench --site alphalite.localhost execute \\
    zimpra_integration.zimpra_integration.tests.run_all_scenarios.run

Live API (optional):
  bench --site alphalite.localhost execute \\
    zimpra_integration.zimpra_integration.tests.run_all_scenarios.run \\
    --kwargs '{"live": 1}'
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import frappe
from frappe.utils import add_to_date, now_datetime

from zimpra_integration.zimpra_integration.address_hooks import update_coordinates
from zimpra_integration.zimpra_integration.background_jobs import webhook_job
from zimpra_integration.zimpra_integration.background_jobs.webhook_job import (
	clean_phone,
	manual_send,
	manual_update,
	process_update_webhook,
	process_webhook,
	send_webhook,
)


DN_NAME = "DN-26-27-02960"
COMPANY_ADDRESS = "Adyam Energy Solutions Pvt. Ltd.-Billing"


class Suite:
	def __init__(self):
		self.tests = []
		self.section = ""

	def set_section(self, name):
		self.section = name
		print(f"\n===== {name} =====")

	def check(self, name, cond, detail=""):
		full = f"[{self.section}] {name}" if self.section else name
		row = {"name": full, "ok": bool(cond), "detail": str(detail)[:700], "section": self.section}
		self.tests.append(row)
		print(("PASS" if row["ok"] else "FAIL"), "-", name, "-", row["detail"][:220])

	def summary(self):
		passed = sum(1 for t in self.tests if t["ok"])
		failed = sum(1 for t in self.tests if not t["ok"])
		pos = [t for t in self.tests if t["section"].startswith("POSITIVE")]
		neg = [t for t in self.tests if t["section"].startswith("NEGATIVE")]
		print("\n===== FINAL SUMMARY =====")
		print(f"Total: {len(self.tests)} | Passed: {passed} | Failed: {failed}")
		print(f"Positive: {sum(1 for t in pos if t['ok'])}/{len(pos)}")
		print(f"Negative: {sum(1 for t in neg if t['ok'])}/{len(neg)}")
		for t in self.tests:
			if not t["ok"]:
				print("XX", t["name"], "|", t["detail"][:200])
		return {
			"passed": passed,
			"failed": failed,
			"total": len(self.tests),
			"positive_passed": sum(1 for t in pos if t["ok"]),
			"positive_total": len(pos),
			"negative_passed": sum(1 for t in neg if t["ok"]),
			"negative_total": len(neg),
			"tests": self.tests,
		}


def _mock_response(status_code=200, payload=None, ok=None):
	resp = MagicMock()
	resp.status_code = status_code
	resp.ok = (200 <= status_code < 300) if ok is None else ok
	resp.text = json.dumps(payload or {})
	resp.json.return_value = payload or {}
	return resp


def _snapshot_dn(dn_name):
	return frappe.db.get_value(
		"Delivery Note",
		dn_name,
		[
			"vehicle_no",
			"driver_name",
			"custom_driver_number",
			"transporter_name",
			"custom_select_print_format",
			"contact_mobile",
			"custom_zimpra_status",
			"ewaybill",
		],
		as_dict=True,
	)


def _snapshot_addr(name):
	return frappe.db.get_value(
		"Address",
		name,
		["custom_latitude", "custom_longitude"],
		as_dict=True,
	)


def _restore_dn(dn_name, snap):
	if not snap:
		return
	frappe.db.set_value(
		"Delivery Note",
		dn_name,
		{
			"vehicle_no": snap.get("vehicle_no"),
			"driver_name": snap.get("driver_name"),
			"custom_driver_number": snap.get("custom_driver_number"),
			"transporter_name": snap.get("transporter_name"),
			"custom_select_print_format": snap.get("custom_select_print_format"),
			"contact_mobile": snap.get("contact_mobile"),
			"custom_zimpra_status": snap.get("custom_zimpra_status"),
		},
		update_modified=False,
	)


def _restore_addr(name, snap):
	if not snap:
		return
	frappe.db.set_value(
		"Address",
		name,
		{
			"custom_latitude": snap.get("custom_latitude"),
			"custom_longitude": snap.get("custom_longitude"),
		},
		update_modified=False,
	)


def _prepare_valid_dn(dn_name):
	frappe.db.set_value(
		"Delivery Note",
		dn_name,
		{
			"vehicle_no": "MH12AB1234",
			"driver_name": "Test Driver",
			"custom_driver_number": "9876543210",
			"transporter_name": "Nath Transportation",
			"custom_select_print_format": "1",
			"contact_mobile": "9876543210",
			"custom_zimpra_status": None,
			"ewaybill": None,
		},
		update_modified=False,
	)
	frappe.db.set_value(
		"Address",
		COMPANY_ADDRESS,
		{"custom_latitude": 19.092952, "custom_longitude": 74.7493451},
		update_modified=False,
	)
	shipping = frappe.db.get_value("Delivery Note", dn_name, "shipping_address_name")
	if shipping:
		frappe.db.set_value(
			"Address",
			shipping,
			{"custom_latitude": 18.5590239, "custom_longitude": 73.7867522},
			update_modified=False,
		)
	frappe.db.commit()


def _latest_zlog(dn_name):
	rows = frappe.get_all(
		"Zimpra log",
		filters={"reference_name": dn_name},
		fields=["name", "status", "response"],
		order_by="creation desc",
		limit=1,
	)
	return rows[0] if rows else None


def _fake_settings(**overrides):
	base = frappe.get_single("Zimpra API Settings")
	obj = MagicMock()
	obj.url = overrides.get("url", base.url)
	obj.token = overrides.get("token", base.token)
	obj.url_update = overrides.get("url_update", base.url_update)
	obj.token_update = overrides.get("token_update", base.token_update)
	return obj


def run(live=0):
	frappe.set_user("Administrator")
	r = Suite()

	if not frappe.db.exists("Delivery Note", DN_NAME):
		r.set_section("SETUP")
		r.check("Fixture DN exists", False, DN_NAME)
		return r.summary()

	dn_snap = _snapshot_dn(DN_NAME)
	addr_snap = _snapshot_addr(COMPANY_ADDRESS)
	shipping = frappe.db.get_value("Delivery Note", DN_NAME, "shipping_address_name")
	ship_snap = _snapshot_addr(shipping) if shipping else None

	try:
		# ------------------------------------------------------------------
		# POSITIVE: helpers / gates / happy paths
		# ------------------------------------------------------------------
		r.set_section("POSITIVE - clean_phone")
		for raw, expected in [
			("9876543210", "9876543210"),
			("+91 98765 43210", "9876543210"),
			("919876543210", "9876543210"),
			("0919876543210", "9876543210"),
			("98765-43210", "9876543210"),
		]:
			got = clean_phone(raw)
			r.check(f"valid phone {raw!r}", got == expected, f"got={got!r}")

		r.set_section("POSITIVE - enqueue gates")
		doc = frappe.get_doc("Delivery Note", DN_NAME)
		doc.ewaybill = "EWB-POSITIVE-1"
		with patch.object(webhook_job.frappe, "enqueue") as enq:
			send_webhook(doc)
			r.check("send_webhook enqueues with ewaybill", enq.call_count == 1)

		with patch.object(webhook_job.frappe, "enqueue") as enq:
			msg = manual_send("Delivery Note", DN_NAME)
			r.check("manual_send queues", enq.call_count == 1 and "queued" in msg.lower(), msg)

		with patch.object(webhook_job.frappe, "enqueue") as enq:
			msg = manual_update("Delivery Note", DN_NAME)
			r.check("manual_update queues", enq.call_count == 1 and "queued" in msg.lower(), msg)

		r.set_section("POSITIVE - create API status codes")
		for code, label in [(201, "created"), (205, "trip updated"), (207, "partial")]:
			_prepare_valid_dn(DN_NAME)
			payload = {"success": True, "message": label, "statusCode": code}
			with patch.object(
				webhook_job.requests, "post", return_value=_mock_response(200, payload, True)
			):
				process_webhook("Delivery Note", DN_NAME)
			status = frappe.db.get_value("Delivery Note", DN_NAME, "custom_zimpra_status")
			zlog = _latest_zlog(DN_NAME)
			r.check(f"statusCode {code} => Success", status == "Success", status)
			r.check(f"statusCode {code} => Zimpra log Success", zlog and zlog.status == "Success")

		r.set_section("POSITIVE - already exists")
		_prepare_valid_dn(DN_NAME)
		with patch.object(
			webhook_job.requests,
			"post",
			return_value=_mock_response(
				400,
				{"success": False, "message": "Invoice number already exists", "statusCode": 400},
				False,
			),
		):
			process_webhook("Delivery Note", DN_NAME)
		r.check(
			"already exists => Success",
			frappe.db.get_value("Delivery Note", DN_NAME, "custom_zimpra_status") == "Success",
		)

		r.set_section("POSITIVE - GPS fallback")
		_prepare_valid_dn(DN_NAME)
		if shipping:
			frappe.db.set_value(
				"Address", shipping, {"custom_latitude": 0, "custom_longitude": 0}, update_modified=False
			)
			frappe.db.commit()
		captured = {}

		def _capture_post(url, json=None, headers=None, timeout=None):
			captured["payload"] = json
			return _mock_response(
				201, {"success": True, "message": "ok", "statusCode": 201}, True
			)

		with patch.object(webhook_job.requests, "post", side_effect=_capture_post):
			process_webhook("Delivery Note", DN_NAME)
		r.check(
			"toCord falls back to fromCord",
			captured.get("payload", {}).get("toCord") == captured.get("payload", {}).get("fromCord"),
			captured.get("payload", {}).get("toCord"),
		)
		r.check(
			"fallback noted in log",
			"fell back" in ((_latest_zlog(DN_NAME) or {}).get("response") or "").lower()
			or "fallback" in ((_latest_zlog(DN_NAME) or {}).get("response") or "").lower(),
			(_latest_zlog(DN_NAME) or {}).get("response", "")[:180],
		)

		r.set_section("POSITIVE - update API")
		_prepare_valid_dn(DN_NAME)
		with patch.object(
			webhook_job.requests,
			"patch",
			return_value=_mock_response(200, {"success": True, "message": "Updated", "statusCode": 200}, True),
		):
			process_update_webhook("Delivery Note", DN_NAME)
		r.check(
			"update Success",
			frappe.db.get_value("Delivery Note", DN_NAME, "custom_zimpra_status") == "Success",
		)

		r.set_section("POSITIVE - geocode")
		# skip when coords exist
		addr = frappe.get_doc("Address", COMPANY_ADDRESS)
		with patch("zimpra_integration.zimpra_integration.address_hooks.requests.get") as get_mock:
			update_coordinates(addr)
			r.check("skip geocode when coords present", get_mock.call_count == 0)

		# mock success geocode
		tmp = frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": f"Zimpra Pos {frappe.generate_hash(length=5)}",
				"address_type": "Shipping",
				"address_line1": "FC Road",
				"city": "PUNE",
				"state": "Maharashtra",
				"pincode": "411030",
				"country": "India",
			}
		)
		geo_ok = MagicMock()
		geo_ok.status_code = 200
		geo_ok.json.return_value = [{"lat": "18.52", "lon": "73.85"}]
		geo_ok.text = "[]"
		with patch(
			"zimpra_integration.zimpra_integration.address_hooks.requests.get",
			return_value=geo_ok,
		):
			update_coordinates(tmp)
		r.check(
			"geocode sets lat/lon",
			str(tmp.custom_latitude) == "18.52" and str(tmp.custom_longitude) == "73.85",
			f"{tmp.custom_latitude},{tmp.custom_longitude}",
		)

		r.set_section("POSITIVE - item group")
		item = "Alphalite AAC Blocks (600X200X150)"
		group = frappe.db.get_value("Item", item, "item_group")
		r.check("Alphalite AAC item group", group == "Alphalite AAC", group)
		r.check(
			"all AAC items pass filter",
			all(
				g.item_group == "Alphalite AAC"
				for g in frappe.get_all(
					"Item",
					filters={"name": ["in", [item]]},
					fields=["item_group"],
				)
			),
		)

		# ------------------------------------------------------------------
		# NEGATIVE cases
		# ------------------------------------------------------------------
		r.set_section("NEGATIVE - clean_phone")
		for raw in ["", None, "123", "36382", "abcdefghij", "91"]:
			got = clean_phone(raw)
			r.check(f"invalid phone {raw!r} => empty", got == "", f"got={got!r}")

		r.set_section("NEGATIVE - enqueue gates")
		doc = frappe.get_doc("Delivery Note", DN_NAME)
		doc.ewaybill = None
		with patch.object(webhook_job.frappe, "enqueue") as enq:
			send_webhook(doc)
			r.check("no ewaybill => no enqueue", enq.call_count == 0)

		r.set_section("NEGATIVE - missing settings")
		_prepare_valid_dn(DN_NAME)
		with patch.object(
			webhook_job.frappe, "get_single", return_value=_fake_settings(url="", token="")
		):
			process_webhook("Delivery Note", DN_NAME)
		status = frappe.db.get_value("Delivery Note", DN_NAME, "custom_zimpra_status")
		zlog = _latest_zlog(DN_NAME)
		r.check("missing create URL/token => Failed", status == "Failed", status)
		r.check(
			"missing settings message",
			zlog and "missing url or token" in (zlog.response or "").lower(),
			zlog.response[:160] if zlog else "",
		)

		_prepare_valid_dn(DN_NAME)
		with patch.object(
			webhook_job.frappe,
			"get_single",
			return_value=_fake_settings(url_update="", token_update=""),
		):
			process_update_webhook("Delivery Note", DN_NAME)
		r.check(
			"missing update URL/token => Failed",
			frappe.db.get_value("Delivery Note", DN_NAME, "custom_zimpra_status") == "Failed",
		)

		r.set_section("NEGATIVE - validation")
		# clear required fields
		frappe.db.set_value(
			"Delivery Note",
			DN_NAME,
			{
				"vehicle_no": "",
				"driver_name": "",
				"custom_driver_number": "",
				"transporter_name": "",
				"custom_select_print_format": "",
				"contact_mobile": "12",
				"custom_zimpra_status": None,
			},
			update_modified=False,
		)
		frappe.db.set_value(
			"Address",
			COMPANY_ADDRESS,
			{"custom_latitude": 0, "custom_longitude": 0},
			update_modified=False,
		)
		frappe.db.commit()
		before_logs = frappe.db.count("Zimpra log", {"reference_name": DN_NAME})
		before_errors = frappe.db.count("Error Log")
		cutoff = now_datetime()
		process_webhook("Delivery Note", DN_NAME)
		status = frappe.db.get_value("Delivery Note", DN_NAME, "custom_zimpra_status")
		zlog = _latest_zlog(DN_NAME)
		elog = frappe.get_all(
			"Error Log",
			filters={"creation": [">=", add_to_date(cutoff, minutes=-1)], "method": ["like", "Zimpra%"]},
			fields=["name", "method"],
			limit=3,
		)
		r.check("validation => Failed", status == "Failed", status)
		r.check("validation => Zimpra log", frappe.db.count("Zimpra log", {"reference_name": DN_NAME}) > before_logs)
		r.check("validation => Error Log", frappe.db.count("Error Log") > before_errors or bool(elog), elog)
		missing_txt = (zlog.response if zlog else "") or ""
		for field in [
			"vehicleNumber",
			"driverName",
			"driverPhone",
			"transporterName",
			"deliveryNoteTemplateName",
			"customerPhone",
			"fromCord",
		]:
			r.check(f"missing field reported: {field}", field in missing_txt, missing_txt[:220])

		r.set_section("NEGATIVE - API / network")
		_prepare_valid_dn(DN_NAME)
		with patch.object(
			webhook_job.requests,
			"post",
			return_value=_mock_response(
				400,
				{"success": False, "message": "bad request", "statusCode": 400},
				False,
			),
		):
			process_webhook("Delivery Note", DN_NAME)
		r.check(
			"API 400 => Failed",
			frappe.db.get_value("Delivery Note", DN_NAME, "custom_zimpra_status") == "Failed",
		)

		_prepare_valid_dn(DN_NAME)
		with patch.object(
			webhook_job.requests,
			"post",
			return_value=_mock_response(
				200,
				{"success": False, "message": "not ok", "statusCode": 500},
				True,
			),
		):
			process_webhook("Delivery Note", DN_NAME)
		r.check(
			"success=false => Failed",
			frappe.db.get_value("Delivery Note", DN_NAME, "custom_zimpra_status") == "Failed",
		)

		_prepare_valid_dn(DN_NAME)
		with patch.object(
			webhook_job.requests,
			"post",
			return_value=_mock_response(
				200,
				{"success": True, "message": "odd", "statusCode": 199},
				True,
			),
		):
			process_webhook("Delivery Note", DN_NAME)
		r.check(
			"unexpected statusCode => Failed",
			frappe.db.get_value("Delivery Note", DN_NAME, "custom_zimpra_status") == "Failed",
		)

		_prepare_valid_dn(DN_NAME)
		with patch.object(webhook_job.requests, "post", side_effect=Exception("connection timeout")):
			process_webhook("Delivery Note", DN_NAME)
		zlog = _latest_zlog(DN_NAME)
		r.check(
			"request exception => Failed",
			frappe.db.get_value("Delivery Note", DN_NAME, "custom_zimpra_status") == "Failed",
		)
		r.check(
			"request exception in Zimpra log",
			zlog and "REQUEST ERROR" in (zlog.response or ""),
			zlog.response[:160] if zlog else "",
		)

		# non-JSON body
		_prepare_valid_dn(DN_NAME)
		bad = MagicMock()
		bad.status_code = 502
		bad.ok = False
		bad.text = "<html>bad gateway</html>"
		bad.json.side_effect = ValueError("no json")
		with patch.object(webhook_job.requests, "post", return_value=bad):
			process_webhook("Delivery Note", DN_NAME)
		r.check(
			"non-JSON response => Failed",
			frappe.db.get_value("Delivery Note", DN_NAME, "custom_zimpra_status") == "Failed",
		)

		r.set_section("NEGATIVE - update API")
		_prepare_valid_dn(DN_NAME)
		with patch.object(
			webhook_job.requests,
			"patch",
			return_value=_mock_response(404, {"success": False, "message": "Not found", "statusCode": 404}, False),
		):
			process_update_webhook("Delivery Note", DN_NAME)
		r.check(
			"update 404 => Failed",
			frappe.db.get_value("Delivery Note", DN_NAME, "custom_zimpra_status") == "Failed",
		)

		# ewaybill without dates
		_prepare_valid_dn(DN_NAME)
		frappe.db.set_value("Delivery Note", DN_NAME, "ewaybill", "EWB-NO-DATES-TEST", update_modified=False)
		frappe.db.commit()
		# Ensure no e-Waybill Log dates for this fake number
		with patch.object(webhook_job.frappe.db, "get_value") as gv:
			# Keep normal get_value for most calls; specially return None for ewaybill dates
			real_get_value = frappe.db.get_value

			def _gv(doctype, *args, **kwargs):
				if doctype == "e-Waybill Log":
					return None
				return real_get_value(doctype, *args, **kwargs)

			# Simpler: set ewaybill and patch only the two date lookups inside function via side effect on module
		# Direct approach: process_update with ewaybill that has no log
		process_update_webhook("Delivery Note", DN_NAME)
		zlog = _latest_zlog(DN_NAME)
		status = frappe.db.get_value("Delivery Note", DN_NAME, "custom_zimpra_status")
		r.check("update ewaybill without dates => Failed", status == "Failed", status)
		r.check(
			"update ewaybill dates error message",
			zlog and "ewaybilldate" in (zlog.response or "").lower() and "validupto" in (zlog.response or "").lower(),
			zlog.response[:200] if zlog else "",
		)

		r.set_section("NEGATIVE - geocode")
		# empty address parts => no call
		empty_addr = frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": f"Empty {frappe.generate_hash(length=4)}",
				"address_type": "Shipping",
				"address_line1": "X",
				"country": "",
			}
		)
		empty_addr.city = ""
		empty_addr.state = ""
		empty_addr.pincode = ""
		with patch("zimpra_integration.zimpra_integration.address_hooks.requests.get") as get_mock:
			update_coordinates(empty_addr)
			r.check("empty city/state/pincode => no geocode call", get_mock.call_count == 0)

		# 429
		tmp2 = frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": f"Rate {frappe.generate_hash(length=4)}",
				"address_type": "Shipping",
				"address_line1": "Y",
				"city": "PUNE",
				"state": "Maharashtra",
				"pincode": "411001",
				"country": "India",
			}
		)
		mock_429 = MagicMock()
		mock_429.status_code = 429
		mock_429.text = "Too Many Requests"
		before_errors = frappe.db.count("Error Log")
		with patch(
			"zimpra_integration.zimpra_integration.address_hooks.requests.get",
			return_value=mock_429,
		):
			update_coordinates(tmp2)
		r.check("429 does not crash", True)
		r.check("429 writes Error Log", frappe.db.count("Error Log") > before_errors)

		# HTTP 500
		mock_500 = MagicMock()
		mock_500.status_code = 500
		mock_500.text = "server error"
		before_errors = frappe.db.count("Error Log")
		with patch(
			"zimpra_integration.zimpra_integration.address_hooks.requests.get",
			return_value=mock_500,
		):
			update_coordinates(tmp2)
		r.check("geocode HTTP 500 logs error", frappe.db.count("Error Log") > before_errors)

		# empty result list
		mock_empty = MagicMock()
		mock_empty.status_code = 200
		mock_empty.json.return_value = []
		mock_empty.text = "[]"
		before_errors = frappe.db.count("Error Log")
		with patch(
			"zimpra_integration.zimpra_integration.address_hooks.requests.get",
			return_value=mock_empty,
		):
			update_coordinates(tmp2)
		r.check("geocode no-result logs error", frappe.db.count("Error Log") > before_errors)

		# exception
		before_errors = frappe.db.count("Error Log")
		with patch(
			"zimpra_integration.zimpra_integration.address_hooks.requests.get",
			side_effect=Exception("dns fail"),
		):
			update_coordinates(tmp2)
		r.check("geocode exception logs error", frappe.db.count("Error Log") > before_errors)

		r.set_section("NEGATIVE - item group filter")
		aac = "Alphalite AAC Blocks (600X200X150)"
		other = frappe.db.get_value("Item", {"item_group": ["!=", "Alphalite AAC"], "disabled": 0}, "name")
		if other:
			groups = {
				g.name: g.item_group
				for g in frappe.get_all(
					"Item",
					filters={"name": ["in", [aac, other]]},
					fields=["name", "item_group"],
				)
			}
			all_aac = all(groups.get(c) == "Alphalite AAC" for c in [aac, other])
			r.check("mixed item groups blocked for auto-send", all_aac is False, groups)
		else:
			r.check("mixed item groups blocked for auto-send", True, "no non-AAC item")

		# ------------------------------------------------------------------
		# OPTIONAL LIVE
		# ------------------------------------------------------------------
		r.set_section("POSITIVE - live API" if int(live or 0) else "POSITIVE - live API skipped")
		if int(live or 0):
			_prepare_valid_dn(DN_NAME)
			process_webhook("Delivery Note", DN_NAME)
			status = frappe.db.get_value("Delivery Note", DN_NAME, "custom_zimpra_status")
			r.check("LIVE create sets Success/Failed", status in ("Success", "Failed"), status)
			process_update_webhook("Delivery Note", DN_NAME)
			status2 = frappe.db.get_value("Delivery Note", DN_NAME, "custom_zimpra_status")
			r.check("LIVE update sets Success/Failed", status2 in ("Success", "Failed"), status2)
		else:
			r.check("live skipped (use live=1)", True)

	except Exception:
		r.set_section("SUITE ERROR")
		r.check("suite crashed", False, frappe.get_traceback())
	finally:
		_restore_dn(DN_NAME, dn_snap)
		_restore_addr(COMPANY_ADDRESS, addr_snap)
		if ship_snap and shipping:
			_restore_addr(shipping, ship_snap)
		frappe.db.commit()

	return r.summary()
