import frappe
from frappe.integrations.utils import make_get_request

def update_coordinates(doc, event=None):
    # Build geocode address (city, state, pincode, country)
    address = ", ".join(filter(None, [
        doc.city,
        doc.state,
        doc.pincode,
        doc.country
    ]))

    if not address:
        doc.custom_latitude = ""
        doc.custom_longitude = ""
        return

    url = (
        "https://nominatim.openstreetmap.org/search"
        f"?q={address.replace(' ', '+')}&format=json&limit=1"
    )

    headers = {"User-Agent": "ERPNext-Zimpra/1.0"}

    try:
        result = make_get_request(url, headers=headers)
    except Exception:
        doc.custom_latitude = ""
        doc.custom_longitude = ""
        return

    if result:
        doc.custom_latitude = result[0].get("lat") or ""
        doc.custom_longitude = result[0].get("lon") or ""
    else:
        doc.custom_latitude = ""
        doc.custom_longitude = ""
