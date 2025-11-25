import frappe
import requests
import json

def send_webhook(doc, event=None):

    url = "https://backend.graviti-test.in/api/v1/ewaybill/webhook-track"
    token = "d1a4c0d2-6c2b-4c79-bf2a-8c1f42fda539"

    payload = {
        "ewaybill_no": "444446789555",
        "lrNo": "1134888",
        "ewayBillDate": "01/01/2025 12:00:00 PM",
        "userGstin": "29ABCDE1234F2Z5",
        "fromAddr": "Plot No. 12, Industrial Area ",
        "fromPlace": "Bengaluru",
        "fromPincode": "560066",
        "fromStateCode": "29",
        "toStateCode": "20",
        "toTrdName": "Sharma Traders Pvt Ltd",
        "toAddr": "Shop No. 8, Sector 21 Market, Vashi",
        "toPlace": "Mumbai",
        "toPincode": "400703",
        "amount": "45000",
        "items": {
            "Cement": {"code": "CEM001", "weight": 50, "unit": "kg"},
            "Steel Rods": {"code": "STL002", "weight": 120, "unit": "kg"},
            "Bricks": {"code": "BRK003", "weight": 500, "unit": "nos"}
        },
        "customerName": "Demo name",
        "customerPhone": "1234567890",
        "vehicleNumber": "AB 12 AB 1234",
        "fromCord": [11.0764467, 77.1321102],
        "toCord": [8.8038527, 78.15272660000001],
        "driverName": "Demo driver",
        "driverPhone": "1234567899",
        "net_weight": 490.5,
        "invoiceNo": "INV-2025-5678",
        "validUpto": "01/01/2025 12:00:00 PM"
    }

    headers = {
        "Authorization": token,
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(url, json=payload, headers=headers)
        response_text = response.text
    except Exception as e:
        response_text = str(e)

    try:
        frappe.get_doc({
            "doctype": "Zimpra log",
            "reference_doctype": doc.doctype,
            "reference_name": doc.name,
            "payload": json.dumps(payload, indent=2),
            "response": response_text
        }).insert(ignore_permissions=True)
        frappe.db.commit()
    except:
        frappe.log_error(frappe.get_traceback(), "Zimpra Log Error")

    frappe.msgprint("Webhook sent. Check Zimpra log.")
