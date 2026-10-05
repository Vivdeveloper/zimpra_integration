"""Manual smoke test for Zimpra failure logging.

Run:
  bench --site alphalite.localhost execute \
    zimpra_integration.zimpra_integration.tests.manual_zimpra_smoke.run
"""

import frappe
from frappe.utils import add_to_date, now_datetime

from zimpra_integration.zimpra_integration.address_hooks import update_coordinates
from zimpra_integration.zimpra_integration.background_jobs.webhook_job import process_webhook


def run():
	frappe.set_user("Administrator")
	tests = []

	def check(name, cond, detail=""):
		row = {"name": name, "ok": bool(cond), "detail": str(detail)[:500]}
		tests.append(row)
		print(("PASS" if row["ok"] else "FAIL"), "-", name, "-", row["detail"])

	created = {"address": None, "delivery_note": None}

	# ---------- TEST 1: Address geocode does not crash ----------
	try:
		addr = frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": f"Zimpra Smoke {frappe.generate_hash(length=6)}",
				"address_type": "Shipping",
				"address_line1": "FC Road",
				"city": "PUNE",
				"state": "Maharashtra",
				"pincode": "411030",
				"country": "India",
			}
		)
		update_coordinates(addr)
		addr.insert(ignore_permissions=True)
		frappe.db.commit()
		created["address"] = addr.name
		check(
			"Address geocode path did not crash",
			True,
			f"{addr.name} lat={addr.custom_latitude} lon={addr.custom_longitude}",
		)
	except Exception:
		frappe.db.rollback()
		check("Address geocode path did not crash", False, frappe.get_traceback())

	# ---------- TEST 2: Validation failure on existing DN ----------
	# Clear required Zimpra fields temporarily, run process_webhook, restore.
	dn_name = "DN-26-27-02960"
	company_address = "Adyam Energy Solutions Pvt. Ltd.-Billing"
	restore = {}

	try:
		if not frappe.db.exists("Delivery Note", dn_name):
			check("Existing DN available", False, dn_name)
		else:
			created["delivery_note"] = dn_name

			# Snapshot + force missing required fields / coords
			restore["dn"] = frappe.db.get_value(
				"Delivery Note",
				dn_name,
				[
					"vehicle_no",
					"driver_name",
					"custom_driver_number",
					"transporter_name",
					"custom_select_print_format",
					"custom_zimpra_status",
				],
				as_dict=True,
			)
			restore["addr"] = frappe.db.get_value(
				"Address",
				company_address,
				["custom_latitude", "custom_longitude"],
				as_dict=True,
			)

			frappe.db.set_value(
				"Delivery Note",
				dn_name,
				{
					"vehicle_no": "",
					"driver_name": "",
					"custom_driver_number": "",
					"transporter_name": "",
					"custom_select_print_format": "",
					"custom_zimpra_status": None,
				},
				update_modified=False,
			)
			frappe.db.set_value(
				"Address",
				company_address,
				{"custom_latitude": 0, "custom_longitude": 0},
				update_modified=False,
			)
			frappe.db.commit()

			before_logs = frappe.db.count("Zimpra log", {"reference_name": dn_name})
			before_errors = frappe.db.count("Error Log")
			cutoff = now_datetime()

			process_webhook("Delivery Note", dn_name)

			status = frappe.db.get_value("Delivery Note", dn_name, "custom_zimpra_status")
			after_logs = frappe.db.count("Zimpra log", {"reference_name": dn_name})
			after_errors = frappe.db.count("Error Log")
			zlog = frappe.get_all(
				"Zimpra log",
				filters={"reference_name": dn_name},
				fields=["name", "status", "response"],
				order_by="creation desc",
				limit=1,
			)
			elog = frappe.get_all(
				"Error Log",
				filters={"creation": [">=", add_to_date(cutoff, minutes=-1)]},
				fields=["name", "method"],
				order_by="creation desc",
				limit=5,
			)

			check("DN status is Failed after validation error", status == "Failed", status)
			check("Zimpra log created for DN", after_logs > before_logs, zlog)
			check(
				"Zimpra log status Failed",
				bool(zlog) and zlog[0]["status"] == "Failed",
				(zlog[0]["response"][:200] if zlog else "none"),
			)
			check(
				"Error Log written for failure",
				after_errors > before_errors or bool(elog),
				f"errors {before_errors}->{after_errors}; recent={elog}",
			)
	except Exception:
		check("Validation failure path", False, frappe.get_traceback())
	finally:
		# Restore DN + address
		try:
			if restore.get("dn"):
				frappe.db.set_value(
					"Delivery Note",
					dn_name,
					{
						"vehicle_no": restore["dn"].get("vehicle_no"),
						"driver_name": restore["dn"].get("driver_name"),
						"custom_driver_number": restore["dn"].get("custom_driver_number"),
						"transporter_name": restore["dn"].get("transporter_name"),
						"custom_select_print_format": restore["dn"].get("custom_select_print_format"),
						# keep Failed from test so it is visible; also restore old if needed
						"custom_zimpra_status": "Failed",
					},
					update_modified=False,
				)
			if restore.get("addr"):
				frappe.db.set_value(
					"Address",
					company_address,
					{
						"custom_latitude": restore["addr"].get("custom_latitude"),
						"custom_longitude": restore["addr"].get("custom_longitude"),
					},
					update_modified=False,
				)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()

	# ---------- TEST 3: item_group lookup used by client script ----------
	try:
		item_codes = ["Alphalite AAC Blocks (600X200X150)"]
		groups = frappe.get_all(
			"Item",
			filters={"name": ["in", item_codes]},
			fields=["name", "item_group"],
		)
		ok = bool(groups) and groups[0]["item_group"] == "Alphalite AAC"
		check("Item Group fetch for Alphalite AAC works", ok, groups)
	except Exception:
		check("Item Group fetch for Alphalite AAC works", False, frappe.get_traceback())

	passed = sum(1 for t in tests if t["ok"])
	failed = sum(1 for t in tests if not t["ok"])
	print("\n===== SUMMARY =====")
	print(f"Passed: {passed}, Failed: {failed}")
	print("CREATED:", created)
	return {"passed": passed, "failed": failed, "tests": tests, "created": created}
