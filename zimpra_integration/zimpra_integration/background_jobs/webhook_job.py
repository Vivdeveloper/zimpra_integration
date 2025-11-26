import frappe
import requests
import json
from frappe.utils import format_datetime

# ---------------------- FAST EXECUTION ----------------------
def send_webhook(doc, event=None):
    frappe.enqueue(
        "zimpra_integration.zimpra_integration.background_jobs.webhook_job.process_webhook",
        doc_doctype=doc.doctype,
        doc_name=doc.name,
        queue="long",
        timeout=300
    )

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
            "unit": item.uom
        }
        for item in doc.items
    }


    ewaybill_date = frappe.db.get_value("e-Waybill Log", doc.ewaybill, "created_on")
    valid_upto = frappe.db.get_value("e-Waybill Log", doc.ewaybill, "valid_upto")


    # ---------------------------------------------------------
    #   GET LIVE COORDINATES (OpenStreetMap) BASED ON 3 FIELDS
    # ---------------------------------------------------------

    from_addr = frappe.db.get_value("Address", doc.company_address, "address_line1") or ""
    from_place = frappe.db.get_value("Address", doc.company_address, "gst_state") or ""
    from_pincode = frappe.db.get_value("Address", doc.company_address, "pincode") or ""

    search_query = f"{from_addr}, {from_place}, {from_pincode}"

    from_coords = [0, 0]

    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": search_query, "format": "json", "limit": 1},
            headers={"User-Agent": "ERPNext"}
        )
        if r.ok and r.json():
            from_coords = [
                float(r.json()[0]["lat"]),
                float(r.json()[0]["lon"])
            ]
    except:
        pass


    # ---------------------------------------------------------
    #   GET LIVE TO COORDINATES (OpenStreetMap)
    # ---------------------------------------------------------
    to_addr = frappe.db.get_value("Address", doc.shipping_address_name, "address_line1") or ""
    to_place = frappe.db.get_value("Address", doc.shipping_address_name, "gst_state") or ""
    to_pincode = frappe.db.get_value("Address", doc.shipping_address_name, "pincode") or ""

    to_query = f"{to_addr}, {to_place}, {to_pincode}"
    to_coords = [0, 0]

    try:
        r2 = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": to_query, "format": "json", "limit": 1},
            headers={"User-Agent": "ERPNext"}
        )
        if r2.ok and r2.json():
            to_coords = [
                float(r2.json()[0]["lat"]),
                float(r2.json()[0]["lon"])
            ]
    except:
        pass

    # ---------------------------------------------------------

    payload = {
        "ewaybill_no": "444446789551",
        "lrNo": doc.lr_no or "",
        "ewayBillDate": format_datetime(ewaybill_date, "dd/MM/yyyy hh:mm:ss a") if ewaybill_date else "",
        "userGstin": doc.company_gstin or "",
        "fromAddr": frappe.db.get_value("Address", doc.company_address, "address_line1") or "",
        "fromPlace": frappe.db.get_value("Address", doc.company_address, "gst_state") or "",
        "fromPincode": frappe.db.get_value("Address", doc.company_address, "pincode") or "",
        "fromStateCode": frappe.db.get_value("Address", doc.company_address, "gst_state_number") or "",
        "fromCord": from_coords,

        "toTrdName": doc.customer_name or "",
        "toStateCode": frappe.db.get_value("Address", doc.shipping_address_name, "gst_state_number") or "",
        "toAddr": (doc.shipping_address or "").replace("\n", " "),
        "toPlace": frappe.db.get_value("Address", doc.shipping_address_name, "gst_state") or "",
        "toPincode": frappe.db.get_value("Address", doc.shipping_address_name, "gst_state_number") or "",
        "amount": str(doc.grand_total or 0),

        "items": items_payload,
        

        "customerName": doc.customer_name or "",
        "customerPhone": doc.contact_mobile or "",
        "vehicleNumber": doc.vehicle_no or "",
  
        "toCord": to_coords,
        "driverName": doc.driver_name or "",
        "driverPhone": doc.contact_mobile or "",
        "net_weight": doc.custom_block_weight or 0,
        "invoiceNo": doc.name,
        "validUpto": format_datetime(valid_upto, "dd/MM/yyyy hh:mm:ss a") if valid_upto else "",
    }

    headers = {
        "Authorization": token,
        "Content-Type": "application/json"
    }

    # ------------------ ALWAYS CAPTURE RESPONSE ------------------
    response_text = ""
    try:
        response = requests.post(url, json=payload, headers=headers)
        response_text = f"STATUS: {response.status_code}\n{response.text}"
    except Exception as e:
        response_text = f"REQUEST ERROR: {str(e)}"

    # ---------------------- ALWAYS LOG THE RESPONSE ----------------------
    try:
        log = frappe.get_doc({
            "doctype": "Zimpra log",
            "reference_doctype": doc_doctype,
            "reference_name": doc_name,
            "payload": json.dumps(payload, indent=2),
            "response": response_text
        })
        log.insert(ignore_permissions=True)
        frappe.db.commit()
    except Exception as e:
        frappe.log_error(
            f"Zimpra Log Insert Failed:\n{str(e)}\n\nORIGINAL RESPONSE:\n{response_text}",
            "Zimpra Log Error"
        )
