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

def clean_phone(phone):
    if not phone:
        return ""
    digits = "".join(filter(str.isdigit, str(phone)))
    return digits[-10:] if len(digits) >= 10 else ""



# ---------------------- BACKGROUND JOB ----------------------
def process_webhook(doc_doctype, doc_name):

    doc = frappe.get_doc(doc_doctype, doc_name)

    url = "https://backend.graviti-test.in/api/v1/ewaybill/webhook-track"
    token = "d1a4c0d2-6c2b-4c79-bf2a-8c1f42fda539"


        # ---------------------- DYNAMIC ITEMS ----------------------
    items_payload = {
        item.item_name: {
            "code": item.item_code,
            "weight": item.weight_per_unit or 0,
            "unit": item.uom,
            "quantity": float(item.qty or 0),
            "totalAmount": float(item.amount or 0),
            "description": item.description or item.item_name or ""
        }
        for item in doc.items
    }


    ewaybill_date = frappe.db.get_value("e-Waybill Log", doc.ewaybill, "created_on")
    valid_upto = frappe.db.get_value("e-Waybill Log", doc.ewaybill, "valid_upto")

    # ---------------------- COORDINATES ----------------------
    from_lat = float(frappe.db.get_value("Address", doc.company_address, "custom_latitude") or 0)
    from_lon = float(frappe.db.get_value("Address", doc.company_address, "custom_longitude") or 0)

    to_lat = float(frappe.db.get_value("Address", doc.shipping_address_name, "custom_latitude") or 0)
    to_lon = float(frappe.db.get_value("Address", doc.shipping_address_name, "custom_longitude") or 0)


    # ---------------------------------------------------------
    shipping_addr = frappe.db.get_value(
        "Address",
        doc.shipping_address_name,
        ["address_line1", "gst_state", "gst_state_number", "pincode"],
        as_dict=True
        ) or {}
    

    payload = {
        "ewaybill_no": doc.ewaybill or "",
        "lrNo": doc.lr_no or "",
        "ewayBillDate": format_datetime(ewaybill_date, "dd/MM/yyyy hh:mm:ss a") if ewaybill_date else "",
        "userGstin": doc.company_gstin or "",
        "fromAddr": " ".join(frappe.db.get_value("Address", doc.company_address, ["address_line1","address_line2"]) or ["",""]).strip(),
        "fromPlace": frappe.db.get_value("Address", doc.company_address, "gst_state") or "",
        "fromPincode": frappe.db.get_value("Address", doc.company_address, "pincode") or "",
        "fromStateCode": frappe.db.get_value("Address", doc.company_address, "gst_state_number") or "",
        "fromCord": [from_lat, from_lon],

        "toTrdName": doc.customer_name or "",
        # "toStateCode": frappe.db.get_value("Address", doc.shipping_address_name, "gst_state_number") or "",
        # "toAddr": frappe.db.get_value("Address", doc.shipping_address_name, "address_line1") or "",
        # "toPlace": frappe.db.get_value("Address", doc.shipping_address_name, "gst_state") or "",
        # "toPincode": frappe.db.get_value("Address", doc.shipping_address_name, "pincode") or "",
        "toStateCode": shipping_addr.get("gst_state_number", ""),
        "toAddr": shipping_addr.get("address_line1", ""),
        "toPlace": shipping_addr.get("gst_state", ""),
        "toPincode": shipping_addr.get("pincode", ""),


        "amount": str(doc.grand_total or 0),

        "items": items_payload,
        

        "customerName": doc.customer_name or "",
        # "customerPhone": doc.contact_mobile or "",
        "customerPhone": clean_phone(doc.contact_mobile),
        "vehicleNumber": doc.vehicle_no or "",
  
        "toCord": [to_lat, to_lon],
        "driverName": doc.driver_name or "",
        # "driverPhone": doc.custom_driver_number or "",
        "driverPhone": clean_phone(doc.custom_driver_number),
        "net_weight": doc.custom_block_weight or 0,
        "invoiceNo": doc.name,
        "validUpto": format_datetime(valid_upto, "dd/MM/yyyy hh:mm:ss a") if valid_upto else "",
        "deliveryNoteTemplateName": "aishwarya_tiles_dn",
        "transporterName":doc.transporter_name,

    }

    headers = {
        "Authorization": token,
        "Content-Type": "application/json"
    }

    # ------------------ RESPONSE HANDLING ------------------
    response_text = ""
    full_response = {}

    try:
        response = requests.post(url, json=payload, headers=headers)

        try:
            full_response = response.json()
        except:
            full_response = {}

        response_text = f"STATUS: {response.status_code}\n{full_response}"

    except Exception as e:
        full_response = {}
        response_text = f"REQUEST ERROR: {str(e)}"

    # --------------- SUPER SHORT SUCCESS CHECK ---------------
    status_flag = "Success" if full_response.get("success") else "Failed"


    # ---------------------- LOG RESPONSE ----------------------
    try:
        log = frappe.get_doc({
            "doctype": "Zimpra log",
            "reference_doctype": doc_doctype,
            "reference_name": doc_name,
            "payload": json.dumps(payload, indent=2),
            "response": response_text,
            "full_response": json.dumps(full_response, indent=2) if isinstance(full_response, dict) else str(full_response),
            "status": status_flag
        })
        log.insert(ignore_permissions=True)

            # ---- UPDATE Delivery Note custom_status ----
        frappe.db.set_value(doc_doctype, doc_name, "custom_zimpra_status", status_flag)
        
        frappe.db.commit()


    except Exception as e:
        frappe.log_error(
            f"Zimpra Log Insert Failed:\n{str(e)}\n\nORIGINAL RESPONSE:\n{response_text}",
            "Zimpra Log Error"
        )