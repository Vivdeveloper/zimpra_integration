"""Fill required Zimpra fields on a DN and run webhook expecting Success.

Run:
  bench --site alphalite.localhost execute \
    zimpra_integration.zimpra_integration.tests.zimpra_success_test.run
"""

import frappe

from zimpra_integration.zimpra_integration.address_hooks import update_coordinates
from zimpra_integration.zimpra_integration.background_jobs.webhook_job import process_webhook


def run():
	frappe.set_user("Administrator")
	dn_name = "DN-26-27-02960"
	company_address = "Adyam Energy Solutions Pvt. Ltd.-Billing"

	# 1) Ensure company address has GPS
	addr = frappe.get_doc("Address", company_address)
	lat = float(addr.custom_latitude or 0)
	lon = float(addr.custom_longitude or 0)
	if not lat or not lon:
		addr.custom_latitude = ""
		addr.custom_longitude = ""
		update_coordinates(addr)
		if not float(addr.custom_latitude or 0) or not float(addr.custom_longitude or 0):
			addr.custom_latitude = 19.0948
			addr.custom_longitude = 74.7480
		addr.save(ignore_permissions=True)
		frappe.db.commit()
	print("Company coords:", addr.custom_latitude, addr.custom_longitude)

	# Ensure shipping address GPS
	shipping = frappe.db.get_value(
		"Delivery Note", dn_name, "shipping_address_name"
	)
	if shipping:
		s_lat = float(frappe.db.get_value("Address", shipping, "custom_latitude") or 0)
		s_lon = float(frappe.db.get_value("Address", shipping, "custom_longitude") or 0)
		if not s_lat or not s_lon:
			frappe.db.set_value(
				"Address",
				shipping,
				{"custom_latitude": 18.5590239, "custom_longitude": 73.7867522},
				update_modified=False,
			)
			frappe.db.commit()

	# 2) Fill all required DN fields (including valid 10-digit phones)
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
		},
		update_modified=False,
	)
	frappe.db.commit()

	print("DN fields prepared on", dn_name)

	# 3) Call Zimpra create webhook
	process_webhook("Delivery Note", dn_name)

	status = frappe.db.get_value("Delivery Note", dn_name, "custom_zimpra_status")
	zlog = frappe.get_all(
		"Zimpra log",
		filters={"reference_name": dn_name},
		fields=["name", "status", "response"],
		order_by="creation desc",
		limit=1,
	)

	print("STATUS:", status)
	print("LOG NAME:", zlog[0]["name"] if zlog else None)
	print("LOG STATUS:", zlog[0]["status"] if zlog else None)
	print("LOG RESPONSE:", (zlog[0]["response"][:500] if zlog else None))

	ok = status == "Success"
	print("RESULT:", "SUCCESS" if ok else "NOT SUCCESS")
	return {"ok": ok, "status": status, "log": zlog, "dn": dn_name}
