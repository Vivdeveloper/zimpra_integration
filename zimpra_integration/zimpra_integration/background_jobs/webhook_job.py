import frappe
import requests
import json
from frappe.utils import format_datetime

# ---------------------- FAST EXECUTION ----------------------
def send_webhook(doc, event=None):
    if not doc.ewaybill:
        return  # No eWaybill → no webhook call
    frappe.enqueue(
        "zimpra_integration.zimpra_integration.background_jobs.webhook_job.process_webhook",
        doc_doctype=doc.doctype,
        doc_name=doc.name,
        queue="long",
        timeout=300
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
        timeout=300
    )
    return "Webhook queued"


@frappe.whitelist()
def manual_update(doctype, doc_name):
    frappe.enqueue(
        "zimpra_integration.zimpra_integration.background_jobs.webhook_job.process_update_webhook",
        doc_doctype=doctype,
        doc_name=doc_name,
        queue="long",
        timeout=300
    )
    return "Update Webhook queued"

# def clean_phone(phone):
#     if not phone:
#         return ""
#     digits = "".join(filter(str.isdigit, str(phone)))
#     return digits[-10:] if len(digits) >= 10 else ""



# ---------------------- BACKGROUND JOB ----------------------
# def process_webhook(doc_doctype, doc_name):

#     doc = frappe.get_doc(doc_doctype, doc_name)

#     url = "https://backend.graviti-test.in/api/v1/ewaybill/webhook-track"
#     token = "d1a4c0d2-6c2b-4c79-bf2a-8c1f42fda539"


#         # ---------------------- DYNAMIC ITEMS ----------------------
#     items_payload = {
#         item.item_name: {
#             "code": item.item_code,
#             "weight": item.weight_per_unit or 0,
#             "unit": item.uom,
#             "quantity": float(item.qty or 0),
#             "totalAmount": float(item.amount or 0),
#             "description": item.description or item.item_name or ""
#         }
#         for item in doc.items
#     }


#     ewaybill_date = frappe.db.get_value("e-Waybill Log", doc.ewaybill, "created_on")
#     valid_upto = frappe.db.get_value("e-Waybill Log", doc.ewaybill, "valid_upto")

#     # ---------------------- COORDINATES ----------------------
#     from_lat = float(frappe.db.get_value("Address", doc.company_address, "custom_latitude") or 0)
#     from_lon = float(frappe.db.get_value("Address", doc.company_address, "custom_longitude") or 0)

#     to_lat = float(frappe.db.get_value("Address", doc.shipping_address_name, "custom_latitude") or 0)
#     to_lon = float(frappe.db.get_value("Address", doc.shipping_address_name, "custom_longitude") or 0)


#     # ---------------------------------------------------------
#     shipping_addr = frappe.db.get_value(
#         "Address",
#         doc.shipping_address_name,
#         ["address_line1", "gst_state", "gst_state_number", "pincode","state","city"],
#         as_dict=True
#         ) or {}
    

#     payload = {
#         "lrNo": doc.lr_no or "",
#         "userGstin": doc.company_gstin or "",


#         "fromAddr": " ".join(frappe.db.get_value("Address", doc.company_address, ["address_line1","address_line2"]) or ["",""]).strip(),
#         "fromPlace": frappe.db.get_value("Address", doc.company_address, "gst_state") or "",
#         "fromPincode": frappe.db.get_value("Address", doc.company_address, "pincode") or "",
#         "fromStateCode": frappe.db.get_value("Address", doc.company_address, "gst_state_number") or "",
#         "fromCord": [from_lat, from_lon],

#         "toTrdName": doc.customer_name or "",
#         "toStateCode": shipping_addr.get("gst_state_number", ""),
#         "toAddr": shipping_addr.get("address_line1", ""),
#         "toPlace": shipping_addr.get("gst_state", ""),
#         "toPincode": shipping_addr.get("pincode", ""),



#         "amount": str(doc.grand_total or 0),

#         "items": items_payload,
        

#         "customerName": doc.customer_name or "",
#         "customerPhone": clean_phone(doc.contact_mobile),
#         "vehicleNumber": doc.vehicle_no or "",
  
#         "toCord": [to_lat, to_lon],
#         "driverName": doc.driver_name or "",
#         "driverPhone": clean_phone(doc.custom_driver_number),
#         "net_weight": doc.custom_block_weight or 0,
#         "invoiceNo": doc.name,

#         "deliveryState":shipping_addr.get("state", ""),
#         "deliveryCity":shipping_addr.get("city", ""),

#         "transporterName":doc.transporter_name

        


#     }
#     if doc.ewaybill:
#         payload["ewaybill_no"] = str(doc.ewaybill)

#     if ewaybill_date:
#         payload["ewayBillDate"] = format_datetime(ewaybill_date, "dd/MM/yyyy hh:mm:ss a")

#     if valid_upto:
#         payload["validUpto"] = format_datetime(valid_upto, "dd/MM/yyyy hh:mm:ss a")

#     if doc.custom_ewaybill_allow:
#        payload["is_ewb_present"] = doc.custom_ewaybill_allow

    

#     headers = {
#         "Authorization": token,
#         "Content-Type": "application/json"
#     }

#     # ------------------ RESPONSE HANDLING ------------------
#     response_text = ""
#     full_response = {}

#     try:
#         response = requests.post(url, json=payload, headers=headers)

#         try:
#             full_response = response.json()
#         except:
#             full_response = {}

#         response_text = f"STATUS: {response.status_code}\n{full_response}"

#     except Exception as e:
#         full_response = {}
#         response_text = f"REQUEST ERROR: {str(e)}"

#     # --------------- SUPER SHORT SUCCESS CHECK ---------------
#     # status_flag = "Success" if full_response.get("success") else "Failed"
#     zimpra_status_code = full_response.get("statusCode")
#     message = (full_response.get("message") or "").lower()

#     if response.status_code == 200 and zimpra_status_code == 200:
#         status_flag = "Success"
#     elif "already exists" in message:
#         status_flag = "Success"   # allow update flow
#     else:
#         status_flag = "Failed"



#     # ---------------------- LOG RESPONSE ----------------------
#     try:
#         log = frappe.get_doc({
#             "doctype": "Zimpra log",
#             "reference_doctype": doc_doctype,
#             "reference_name": doc_name,
#             "payload": json.dumps(payload, indent=2),
#             "response": response_text,
#             "full_response": json.dumps(full_response, indent=2) if isinstance(full_response, dict) else str(full_response),
#             "status": status_flag
#         })
#         log.insert(ignore_permissions=True)

#             # ---- UPDATE Delivery Note custom_status ----
#         frappe.db.set_value(doc_doctype, doc_name, "custom_zimpra_status", status_flag)
        
#         frappe.db.commit()


#     except Exception as e:
#         frappe.log_error(
#             f"Zimpra Log Insert Failed:\n{str(e)}\n\nORIGINAL RESPONSE:\n{response_text}",
#             "Zimpra Log Error"
#         )


def process_webhook(doc_doctype, doc_name):

    doc = frappe.get_doc(doc_doctype, doc_name)

    settings = frappe.get_single("Zimpra API Settings")
    url = settings.url
    token = settings.token

    # ---------------------- DYNAMIC ITEMS ----------------------
    items_payload = {
        item.item_name: {
            "code": item.item_code,
            "weight": float(item.weight_per_unit or 0),
            "unit1": item.uom,
            "qty1": float(item.qty or 0),
            "qty2": float(item.stock_qty or 0),
            "unit2":item.stock_uom,
            "totalAmount": float(item.amount or 0),
            "description": item.description or item.item_name or ""
        }
        for item in doc.items
    }

    # ---------------------- EWAYBILL DATES ----------------------
    ewaybill_date = frappe.db.get_value("e-Waybill Log", doc.ewaybill, "created_on")
    valid_upto = frappe.db.get_value("e-Waybill Log", doc.ewaybill, "valid_upto")

    # ---------------------- COORDINATES (SAFE + FALLBACK) ----------------------

    # Pickup = Company Address
    from_lat_raw = frappe.db.get_value("Address", doc.company_address, "custom_latitude")
    from_lon_raw = frappe.db.get_value("Address", doc.company_address, "custom_longitude")

    from_lat = float(from_lat_raw or 0)
    from_lon = float(from_lon_raw or 0)

    # Delivery = Shipping Address
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
            as_dict=True
        ) or {}

    # ---------------------- PAYLOAD ----------------------
    payload = {
        "lrNo": str(doc.lr_no or ""),
        "userGstin": str(doc.company_gstin or ""),

        "fromAddr": " ".join(
            frappe.db.get_value(
                "Address",
                doc.company_address,
                ["address_line1", "address_line2"]
            ) or ["", ""]
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
        "customerPhone": str(doc.contact_mobile),
        "vehicleNumber": str(doc.vehicle_no or ""),

        "toCord": [float(to_lat), float(to_lon)],
        "driverName": str(doc.driver_name or ""),
        "driverPhone": str(doc.custom_driver_number),
        "net_weight": float(doc.custom_block_weight or 0),
        "invoiceNo": str(doc.name),

        # REQUIRED BY API
        "deliveryNoteTemplateName": str(doc.custom_select_print_format),

        "deliveryState": str(shipping_addr.get("state", "")),
        "deliveryCity": str(shipping_addr.get("city", "")),

        "transporterName": str(doc.transporter_name or "")
    }

    # ---------------------- CONDITIONAL FIELDS ----------------------
    if doc.ewaybill:
        payload["ewaybill_no"] = str(doc.ewaybill)

    if ewaybill_date:
        payload["ewayBillDate"] = format_datetime(
            ewaybill_date, "dd/MM/yyyy hh:mm:ss a"
        )

    if valid_upto:
        payload["validUpto"] = format_datetime(
            valid_upto, "dd/MM/yyyy hh:mm:ss a"
        )

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
        "vehicleNumber",
        "driverName",
        "driverPhone",
        "transporterName",
        "deliveryNoteTemplateName"
    ]

    missing = [f for f in required_fields if not payload.get(f)]

    # Validate coordinates (float-safe)
    if not payload.get("fromCord") or payload["fromCord"] == [0.0, 0.0]:
        missing.append("fromCord")

    if not payload.get("toCord") or payload["toCord"] == [0.0, 0.0]:
        missing.append("toCord")

    # Validate items JSON
    if not payload.get("items"):
        missing.append("items")

    if missing:
        frappe.throw(
            "Zimpra API Validation Failed. Missing / Invalid fields:\n" +
            ", ".join(sorted(set(missing)))
        )

    # ---------------------- HEADERS ----------------------
    headers = {
        "Authorization": token,
        "Content-Type": "application/json"
    }

    # ---------------------- RESPONSE HANDLING ----------------------
    response_text = ""
    full_response = {}

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=20)

        try:
            full_response = response.json()
        except Exception:
            full_response = {}

        response_text = f"STATUS: {response.status_code}\n{full_response}"

    except Exception as e:
        full_response = {}
        response_text = f"REQUEST ERROR: {str(e)}"

       # ---------------------- STATUS CHECK ----------------------
    zimpra_status_code = full_response.get("statusCode")
    success_flag = full_response.get("success", False)
    message = (full_response.get("message") or "").strip().lower()

    # ----------- NEW CONDITION : INVOICE ALREADY EXISTS -----------
    if "invoice number already exists" in message:
        status_flag = "Success"
        internal_status = "Invoice Already Exists"

        # popup in delivery note
        frappe.msgprint(
            title="Zimpra Info",
            msg="Invoice number already exists in Zimpra. Marked as Success.",
            indicator="orange"
        )

    # ----------- NORMAL SUCCESS CASE -----------
    elif response and response.ok and success_flag and zimpra_status_code in (201, 205, 207):
        status_flag = "Success"

        if zimpra_status_code == 201:
            internal_status = "All Orders Created"
        elif zimpra_status_code == 205:
            internal_status = "Trip Updated"
        elif zimpra_status_code == 207:
            internal_status = "Partial Success"

    # ----------- FAILED CASE -----------
    else:
        status_flag = "Failed"
        internal_status = f"API Error ({zimpra_status_code})"

        internal_status = f"API Error ({zimpra_status_code})"


    # ---------------------- LOG RESPONSE ----------------------
    try:
        log = frappe.get_doc({
            "doctype": "Zimpra log",
            "reference_doctype": doc_doctype,
            "reference_name": doc_name,
            "payload": json.dumps(payload, indent=2),
            "response": response_text,
            "full_response": json.dumps({
                "api_response": full_response,
                "used_fallback": used_fallback
            }, indent=2),
            "status": status_flag
        })
        log.insert(ignore_permissions=True)

        # ---- UPDATE Delivery Note custom_status ----
        frappe.db.set_value(
            doc_doctype,
            doc_name,
            "custom_zimpra_status",
            status_flag
        )

        frappe.db.commit()

    except Exception as e:
        frappe.log_error(
            f"Zimpra Log Insert Failed:\n{str(e)}\n\nORIGINAL RESPONSE:\n{response_text}",
            "Zimpra Log Error"
        )



# ---------------------- UPDATE WEBHOOK JOB ----------------------
# def process_update_webhook(doc_doctype, doc_name):

#     doc = frappe.get_doc(doc_doctype, doc_name)

#     url = "https://backend.graviti-test.in/api/v1/ewaybill/webhook-update"
#     token = "d1a4c0d2-6c2b-4c79-bf2a-8c1f42fda539"

#     ewaybill_date = frappe.db.get_value("e-Waybill Log", doc.ewaybill, "created_on")
#     valid_upto = frappe.db.get_value("e-Waybill Log", doc.ewaybill, "valid_upto")

#     # ------------------ UPDATE PAYLOAD (ALL STRINGS) ------------------
#     payload = {
#         "ewaybill_no": str(doc.ewaybill or ""),
#         "lrNo": str(doc.lr_no or ""),
#         "ewayBillDate": format_datetime(ewaybill_date, "dd/MM/yyyy hh:mm:ss a") if ewaybill_date else "",
#         "customerName": str(doc.customer_name or ""),
#         "customerPhone": str(clean_phone(doc.contact_mobile)),
#         "vehicleNumber": str(doc.vehicle_no or ""),
#         "driverName": str(doc.driver_name or ""),
#         "driverPhone": str(clean_phone(doc.custom_driver_number)),
#         "invoiceNo": str(doc.name),  # MANDATORY
#         "updateInvoiceNo": str(doc.name),
#         "validUpto": format_datetime(valid_upto, "dd/MM/yyyy hh:mm:ss a") if valid_upto else ""
#     }

#     headers = {
#         "Authorization": token,
#         "Content-Type": "application/json"
#     }

#     execute_request(
#         method="PATCH",
#         url=url,
#         headers=headers,
#         payload=payload,
#         doc_doctype=doc_doctype,
#         doc_name=doc_name,
#         action="UPDATE"
#     )

# # ---------------------- SHARED EXECUTOR ----------------------
# def execute_request(method, url, headers, payload, doc_doctype, doc_name, action):

#     response_text = ""
#     full_response = {}

#     try:
#         if method == "PATCH":
#             response = requests.patch(url, json=payload, headers=headers)
#         else:
#             response = requests.post(url, json=payload, headers=headers)

#         try:
#             full_response = response.json()
#         except:
#             full_response = {}

#         response_text = f"{action} STATUS: {response.status_code}\n{full_response}"

#     except Exception as e:
#         full_response = {}
#         response_text = f"{action} REQUEST ERROR: {str(e)}"

#     # status_flag = "Success" if full_response.get("success") else "Failed"
#     zimpra_status_code = full_response.get("statusCode")
#     message = (full_response.get("message") or "").lower()

#     if response.status_code == 200 and zimpra_status_code == 200:
#         status_flag = "Success"
#     elif "already exists" in message:
#         status_flag = "Success"
#     else:
#         status_flag = "Failed"


#     # ---------------------- LOG RESPONSE ----------------------
#     try:
#         log = frappe.get_doc({
#             "doctype": "Zimpra log",
#             "reference_doctype": doc_doctype,
#             "reference_name": doc_name,
#             "payload": json.dumps(payload, indent=2),
#             "response": response_text,
#             "full_response": json.dumps(full_response, indent=2) if isinstance(full_response, dict) else str(full_response),
#             "status": status_flag
#         })
#         log.insert(ignore_permissions=True)

#         # ---- UPDATE Delivery Note Status ----
#         frappe.db.set_value(doc_doctype, doc_name, "custom_zimpra_status", status_flag)
#         frappe.db.commit()

#     except Exception as e:
#         frappe.log_error(
#             f"Zimpra {action} Log Insert Failed:\n{str(e)}\n\nORIGINAL RESPONSE:\n{response_text}",
#             "Zimpra Log Error"
#         )        

def process_update_webhook(doc_doctype, doc_name):

    doc = frappe.get_doc(doc_doctype, doc_name)

    settings = frappe.get_single("Zimpra API Settings")
    url = settings.url.replace("webhook-track", "webhook-update")
    token = settings.token

    # ------------------ MANDATORY CHECK ------------------
    if not doc.name:
        frappe.throw("invoiceNo is mandatory for Zimpra Update API")

    ewaybill_date = frappe.db.get_value("e-Waybill Log", doc.ewaybill, "created_on")
    valid_upto = frappe.db.get_value("e-Waybill Log", doc.ewaybill, "valid_upto")

    # ------------------ BASE PAYLOAD (ALL STRINGS) ------------------
    payload = {
        "invoiceNo": str(doc.name),   # MANDATORY
        "updateInvoiceNo": str(doc.name),
        "lrNo": str(doc.lr_no or ""),
        "customerName": str(doc.customer_name or ""),
        "customerPhone": str((doc.contact_mobile)),
        "vehicleNumber": str(doc.vehicle_no or ""),
        "driverName": str(doc.driver_name or ""),
        "driverPhone": str((doc.custom_driver_number)),
    }

    # ------------------ CONDITIONAL EWAYBILL RULE ------------------
    if doc.ewaybill:
        if not ewaybill_date or not valid_upto:
            frappe.throw(
                "If ewaybill_no is sent, both ewayBillDate and validUpto must be provided"
            )

        payload["ewaybill_no"] = str(doc.ewaybill)
        payload["ewayBillDate"] = format_datetime(
            ewaybill_date, "dd/MM/yyyy hh:mm:ss a"
        )
        payload["validUpto"] = format_datetime(
            valid_upto, "dd/MM/yyyy hh:mm:ss a"
        )

    headers = {
        "Authorization": token,
        "Content-Type": "application/json"
    }

    execute_request(
        method="PATCH",
        url=url,
        headers=headers,
        payload=payload,
        doc_doctype=doc_doctype,
        doc_name=doc_name,
        action="UPDATE"
    )

def execute_request(method, url, headers, payload, doc_doctype, doc_name, action):
    response_text = ""
    full_response = {}

    try:
        if method == "PATCH":
            response = requests.patch(url, json=payload, headers=headers, timeout=20)
        else:
            response = requests.post(url, json=payload, headers=headers, timeout=20)

        try:
            full_response = response.json()
        except:
            full_response = {}

        response_text = f"{action} STATUS: {response.status_code}\n{full_response}"

    except Exception as e:
        full_response = {}
        response_text = f"{action} REQUEST ERROR: {str(e)}"
        response = None

    # ---------------------- STATUS CHECK ----------------------
    zimpra_status_code = full_response.get("statusCode")
    success_flag = full_response.get("success", False)

    if response and response.status_code == 200 and success_flag and zimpra_status_code == 200:
        status_flag = "Success"
    else:
        status_flag = "Failed"

    # ---------------------- LOG RESPONSE ----------------------
    try:
        log = frappe.get_doc({
            "doctype": "Zimpra log",
            "reference_doctype": doc_doctype,
            "reference_name": doc_name,
            "payload": json.dumps(payload, indent=2),
            "response": response_text,
            "full_response": json.dumps(full_response, indent=2),
            "status": status_flag
        })
        log.insert(ignore_permissions=True)

        frappe.db.set_value(
            doc_doctype,
            doc_name,
            "custom_zimpra_status",
            status_flag
        )
        frappe.db.commit()

    except Exception as e:
        frappe.log_error(
            f"Zimpra {action} Log Insert Failed:\n{str(e)}\n\nORIGINAL RESPONSE:\n{response_text}",
            "Zimpra Log Error"
        )