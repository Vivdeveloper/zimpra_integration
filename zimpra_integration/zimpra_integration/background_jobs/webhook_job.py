import frappe
import requests
import json
from frappe.utils import format_datetime


# ---------------------- HELPERS ----------------------
def clean_phone(phone):
	"""Return last 10 digits for Indian mobile, else empty string."""
	if not phone:
		return ""
	digits = "".join(filter(str.isdigit, str(phone)))
	if digits.startswith("91") and len(digits) > 10:
		digits = digits[-10:]
	return digits[-10:] if len(digits) >= 10 else ""


def _set_zimpra_status(doc_doctype, doc_name, status_flag):
	frappe.db.set_value(doc_doctype, doc_name, "custom_zimpra_status", status_flag)


def _create_zimpra_log(doc_doctype, doc_name, payload, response_text, status_flag):
	log = frappe.get_doc({
		"doctype": "Zimpra log",
		"reference_doctype": doc_doctype,
		"reference_name": doc_name,
		"payload": json.dumps(payload, indent=2) if not isinstance(payload, str) else payload,
		"response": response_text,
		"status": status_flag,
	})
	log.insert(ignore_permissions=True)


def _mark_failed(doc_doctype, doc_name, payload, error_message, title="Zimpra Webhook Failed"):
	"""Always set Failed status, create Zimpra log, and write Error Log."""
	response_text = f"ERROR: {error_message}"
	try:
		_create_zimpra_log(doc_doctype, doc_name, payload or {}, response_text, "Failed")
		_set_zimpra_status(doc_doctype, doc_name, "Failed")
		frappe.db.commit()
	except Exception as log_err:
		frappe.log_error(
			title="Zimpra Log Insert Failed",
			message=f"{str(log_err)}\n\nORIGINAL ERROR:\n{error_message}",
		)

	frappe.log_error(
		title=f"{title}: {doc_doctype} {doc_name}",
		message=error_message,
	)


def _mark_result(doc_doctype, doc_name, payload, response_text, status_flag):
	try:
		_create_zimpra_log(doc_doctype, doc_name, payload, response_text, status_flag)
		_set_zimpra_status(doc_doctype, doc_name, status_flag)
		frappe.db.commit()
	except Exception as e:
		frappe.log_error(
			title="Zimpra Log Insert Failed",
			message=f"{str(e)}\n\nORIGINAL RESPONSE:\n{response_text}",
		)
		try:
			_set_zimpra_status(doc_doctype, doc_name, status_flag)
			frappe.db.commit()
		except Exception:
			pass


# ---------------------- FAST EXECUTION ----------------------
def send_webhook(doc, event=None):
	if not doc.ewaybill:
		return  # No eWaybill → no webhook call

	frappe.enqueue(
		"zimpra_integration.zimpra_integration.background_jobs.webhook_job.process_webhook",
		doc_doctype=doc.doctype,
		doc_name=doc.name,
		queue="long",
		timeout=300,
	)


# ---------------------- MANUAL TRIGGER FROM BUTTON ----------------------
@frappe.whitelist()
def manual_send(doctype, doc_name):
	"""This is used by the manual button."""
	frappe.enqueue(
		"zimpra_integration.zimpra_integration.background_jobs.webhook_job.process_webhook",
		doc_doctype=doctype,
		doc_name=doc_name,
		queue="long",
		timeout=300,
	)
	return "Webhook queued"


@frappe.whitelist()
def manual_update(doctype, doc_name):
	frappe.enqueue(
		"zimpra_integration.zimpra_integration.background_jobs.webhook_job.process_update_webhook",
		doc_doctype=doctype,
		doc_name=doc_name,
		queue="long",
		timeout=300,
	)
	return "Update Webhook queued"


def process_webhook(doc_doctype, doc_name):
	payload = {}
	try:
		doc = frappe.get_doc(doc_doctype, doc_name)

		settings = frappe.get_single("Zimpra API Settings")
		url = settings.url
		token = settings.token

		if not url or not token:
			_mark_failed(
				doc_doctype,
				doc_name,
				payload,
				"Zimpra API Settings missing URL or Token",
			)
			return

		# ---------------------- DYNAMIC ITEMS ----------------------
		items_payload = {
			item.item_name: {
				"code": item.item_code,
				"weight": float(item.weight_per_unit or 0),
				"unit1": item.uom,
				"qty1": float(item.qty or 0),
				"qty2": float(item.stock_qty or 0),
				"unit2": item.stock_uom,
				"totalAmount": float(item.amount or 0),
				"description": item.description or item.item_name or "",
			}
			for item in doc.items
		}

		# ---------------------- EWAYBILL DATES ----------------------
		ewaybill_date = frappe.db.get_value("e-Waybill Log", doc.ewaybill, "created_on")
		valid_upto = frappe.db.get_value("e-Waybill Log", doc.ewaybill, "valid_upto")

		# ---------------------- COORDINATES (SAFE + FALLBACK) ----------------------
		from_lat_raw = frappe.db.get_value("Address", doc.company_address, "custom_latitude")
		from_lon_raw = frappe.db.get_value("Address", doc.company_address, "custom_longitude")

		from_lat = float(from_lat_raw or 0)
		from_lon = float(from_lon_raw or 0)

		to_lat_raw = None
		to_lon_raw = None

		if doc.shipping_address_name:
			to_lat_raw = frappe.db.get_value("Address", doc.shipping_address_name, "custom_latitude")
			to_lon_raw = frappe.db.get_value("Address", doc.shipping_address_name, "custom_longitude")

		to_lat = float(to_lat_raw or 0)
		to_lon = float(to_lon_raw or 0)

		used_fallback = False

		# Fallback to pickup location if shipping GPS missing
		if not to_lat or not to_lon:
			to_lat = from_lat
			to_lon = from_lon
			used_fallback = True

		# ---------------------- SHIPPING ADDRESS (SAFE) ----------------------
		shipping_addr = {}
		if doc.shipping_address_name:
			shipping_addr = frappe.db.get_value(
				"Address",
				doc.shipping_address_name,
				["address_line1", "gst_state", "gst_state_number", "pincode", "state", "city"],
				as_dict=True,
			) or {}

		# ---------------------- PAYLOAD ----------------------
		payload = {
			"lrNo": str(doc.lr_no or ""),
			"userGstin": str(doc.company_gstin or ""),
			"fromAddr": " ".join(
				frappe.db.get_value(
					"Address",
					doc.company_address,
					["address_line1", "address_line2"],
				)
				or ["", ""]
			).strip(),
			"fromPlace": str(
				frappe.db.get_value("Address", doc.company_address, "gst_state") or ""
			),
			"fromPincode": str(
				frappe.db.get_value("Address", doc.company_address, "pincode") or ""
			),
			"fromStateCode": str(
				frappe.db.get_value("Address", doc.company_address, "gst_state_number") or ""
			),
			"fromCord": [float(from_lat), float(from_lon)],
			"toTrdName": str(doc.customer_name or ""),
			"toStateCode": str(shipping_addr.get("gst_state_number", "")),
			"toAddr": str(shipping_addr.get("address_line1", "")),
			"toPlace": str(shipping_addr.get("gst_state", "")),
			"toPincode": str(shipping_addr.get("pincode", "")),
			"amount": str(doc.grand_total or 0),
			"items": items_payload,
			"customerName": str(doc.customer_name or ""),
			"customerPhone": clean_phone(doc.contact_mobile),
			"vehicleNumber": str(doc.vehicle_no or ""),
			"toCord": [float(to_lat), float(to_lon)],
			"driverName": str(doc.driver_name or ""),
			"driverPhone": clean_phone(doc.custom_driver_number),
			"net_weight": float(doc.custom_block_weight or 0),
			"invoiceNo": str(doc.name),
			"deliveryNoteTemplateName": str(doc.custom_select_print_format or ""),
			"deliveryState": str(shipping_addr.get("state", "")),
			"deliveryCity": str(shipping_addr.get("city", "")),
			"transporterName": str(doc.transporter_name or ""),
		}

		# ---------------------- CONDITIONAL FIELDS ----------------------
		if doc.ewaybill:
			payload["ewaybill_no"] = str(doc.ewaybill)

		if ewaybill_date:
			payload["ewayBillDate"] = format_datetime(ewaybill_date, "dd/MM/yyyy hh:mm:ss a")

		if valid_upto:
			payload["validUpto"] = format_datetime(valid_upto, "dd/MM/yyyy hh:mm:ss a")

		if doc.custom_ewaybill_allow:
			payload["is_ewb_present"] = doc.custom_ewaybill_allow

		# ---------------------- REQUIRED FIELD VALIDATION ----------------------
		required_fields = [
			"userGstin",
			"fromAddr",
			"fromPlace",
			"fromPincode",
			"fromStateCode",
			"toStateCode",
			"toTrdName",
			"toAddr",
			"toPlace",
			"toPincode",
			"customerPhone",
			"vehicleNumber",
			"driverName",
			"driverPhone",
			"transporterName",
			"deliveryNoteTemplateName",
		]

		missing = [f for f in required_fields if not payload.get(f)]

		if not payload.get("fromCord") or payload["fromCord"] == [0.0, 0.0]:
			missing.append("fromCord")

		if not payload.get("toCord") or payload["toCord"] == [0.0, 0.0]:
			missing.append("toCord")

		if not payload.get("items"):
			missing.append("items")

		if missing:
			error_message = (
				"Zimpra API Validation Failed. Missing / Invalid fields:\n"
				+ ", ".join(sorted(set(missing)))
			)
			_mark_failed(doc_doctype, doc_name, payload, error_message, title="Zimpra Validation Failed")
			return

		headers = {
			"Authorization": token,
			"Content-Type": "application/json",
		}

		response = None
		response_text = ""
		full_response = {}

		try:
			response = requests.post(url, json=payload, headers=headers, timeout=20)
			try:
				full_response = response.json()
			except Exception:
				full_response = {"raw": response.text}
			response_text = f"STATUS: {response.status_code}\n{full_response}"
		except Exception as e:
			response = None
			full_response = {}
			response_text = f"REQUEST ERROR: {str(e)}"

		zimpra_status_code = full_response.get("statusCode")
		success_flag = full_response.get("success", False)
		message = (full_response.get("message") or "").strip().lower()

		if "invoice number already exists" in message:
			status_flag = "Success"
		elif response and response.ok and success_flag and zimpra_status_code in (201, 205, 207):
			status_flag = "Success"
		else:
			status_flag = "Failed"

		if used_fallback:
			response_text = f"{response_text}\n\nNOTE: toCord fell back to fromCord (shipping GPS missing)"

		_mark_result(doc_doctype, doc_name, payload, response_text, status_flag)

		if status_flag == "Failed":
			frappe.log_error(
				title=f"Zimpra Webhook Failed: {doc_doctype} {doc_name}",
				message=response_text,
			)

	except Exception as e:
		_mark_failed(
			doc_doctype,
			doc_name,
			payload,
			frappe.get_traceback() or str(e),
			title="Zimpra Webhook Exception",
		)


def process_update_webhook(doc_doctype, doc_name):
	payload = {}
	try:
		doc = frappe.get_doc(doc_doctype, doc_name)

		settings = frappe.get_single("Zimpra API Settings")
		url = settings.url_update
		token = settings.token_update

		if not url or not token:
			_mark_failed(
				doc_doctype,
				doc_name,
				payload,
				"Zimpra API Settings missing Update URL or Token",
				title="Zimpra Update Failed",
			)
			return

		if not doc.name:
			_mark_failed(
				doc_doctype,
				doc_name,
				payload,
				"invoiceNo is mandatory for Zimpra Update API",
				title="Zimpra Update Failed",
			)
			return

		ewaybill_date = frappe.db.get_value("e-Waybill Log", doc.ewaybill, "created_on")
		valid_upto = frappe.db.get_value("e-Waybill Log", doc.ewaybill, "valid_upto")

		payload = {
			"invoiceNo": str(doc.name),
			"updateInvoiceNo": str(doc.name),
			"lrNo": str(doc.lr_no or ""),
			"customerName": str(doc.customer_name or ""),
			"customerPhone": clean_phone(doc.contact_mobile),
			"vehicleNumber": str(doc.vehicle_no or ""),
			"driverName": str(doc.driver_name or ""),
			"driverPhone": clean_phone(doc.custom_driver_number),
		}

		if doc.ewaybill:
			if not ewaybill_date or not valid_upto:
				_mark_failed(
					doc_doctype,
					doc_name,
					payload,
					"If ewaybill_no is sent, both ewayBillDate and validUpto must be provided",
					title="Zimpra Update Failed",
				)
				return

			payload["ewaybill_no"] = str(doc.ewaybill)
			payload["ewayBillDate"] = format_datetime(ewaybill_date, "dd/MM/yyyy hh:mm:ss a")
			payload["validUpto"] = format_datetime(valid_upto, "dd/MM/yyyy hh:mm:ss a")

		headers = {
			"Authorization": token,
			"Content-Type": "application/json",
		}

		execute_request(
			method="PATCH",
			url=url,
			headers=headers,
			payload=payload,
			doc_doctype=doc_doctype,
			doc_name=doc_name,
			action="UPDATE",
		)

	except Exception as e:
		_mark_failed(
			doc_doctype,
			doc_name,
			payload,
			frappe.get_traceback() or str(e),
			title="Zimpra Update Exception",
		)


def execute_request(method, url, headers, payload, doc_doctype, doc_name, action):
	response = None
	response_text = ""
	full_response = {}

	try:
		if method == "PATCH":
			response = requests.patch(url, json=payload, headers=headers, timeout=20)
		else:
			response = requests.post(url, json=payload, headers=headers, timeout=20)

		try:
			full_response = response.json()
		except Exception:
			full_response = {"raw": getattr(response, "text", "")}

		response_text = f"{action} STATUS: {response.status_code}\n{full_response}"

	except Exception as e:
		response = None
		full_response = {}
		response_text = f"{action} REQUEST ERROR: {str(e)}"

	zimpra_status_code = full_response.get("statusCode")
	success_flag = full_response.get("success", False)

	if response and response.status_code == 200 and success_flag and zimpra_status_code == 200:
		status_flag = "Success"
	else:
		status_flag = "Failed"

	_mark_result(doc_doctype, doc_name, payload, response_text, status_flag)

	if status_flag == "Failed":
		frappe.log_error(
			title=f"Zimpra {action} Failed: {doc_doctype} {doc_name}",
			message=response_text,
		)
