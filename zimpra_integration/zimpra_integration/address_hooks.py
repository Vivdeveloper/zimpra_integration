import time
from urllib.parse import quote_plus

import frappe
import requests


NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "ERPNext-Zimpra/1.0 (zimpra_integration; contact: admin@localhost)"
CACHE_KEY = "zimpra_nominatim_last_call"
MIN_INTERVAL_SECONDS = 1.1  # Nominatim usage policy: max 1 request/second


def update_coordinates(doc, event=None):
	"""Geocode Address before_save. Never raise — failures are logged and coords left usable."""
	address_parts = [doc.city, doc.state, doc.pincode, doc.country]
	address = ", ".join(filter(None, address_parts))

	if not address:
		return

	# Do not re-hit Nominatim if coordinates already exist and address key fields unchanged
	if doc.custom_latitude and doc.custom_longitude and not _address_fields_changed(doc):
		return

	# Soft rate-limit across workers using cache
	_wait_for_rate_limit()

	url = f"{NOMINATIM_URL}?q={quote_plus(address)}&format=json&limit=1"
	headers = {"User-Agent": USER_AGENT}

	try:
		# Use requests directly so Frappe make_request does not spam Error Log on 429
		response = requests.get(url, headers=headers, timeout=10)

		if response.status_code == 429:
			frappe.log_error(
				title=f"Nominatim Rate Limited (429): {doc.name or 'new Address'}",
				message=(
					f"Too many geocode requests for address:\n{address}\n\n"
					"Existing coordinates were kept (if any). "
					"Retry later or set custom_latitude / custom_longitude manually."
				),
			)
			return

		if response.status_code != 200:
			frappe.log_error(
				title=f"Nominatim Geocode Failed: {doc.name or 'new Address'}",
				message=f"HTTP {response.status_code} for address:\n{address}\n\n{response.text[:1000]}",
			)
			return

		result = response.json()
		if result:
			doc.custom_latitude = result[0].get("lat") or doc.custom_latitude or ""
			doc.custom_longitude = result[0].get("lon") or doc.custom_longitude or ""
		else:
			frappe.log_error(
				title=f"Nominatim No Result: {doc.name or 'new Address'}",
				message=f"No geocode result for address:\n{address}",
			)

	except Exception:
		frappe.log_error(
			title=f"Nominatim Exception: {doc.name or 'new Address'}",
			message=frappe.get_traceback(),
		)


def _address_fields_changed(doc):
	if doc.is_new():
		return True

	before = doc.get_doc_before_save()
	# Outside a save cycle there is no "before" snapshot — do not force re-geocode
	if not before:
		return False

	for field in ("city", "state", "pincode", "country"):
		if (doc.get(field) or "") != (before.get(field) or ""):
			return True
	return False


def _wait_for_rate_limit():
	"""Best-effort 1 req/sec spacing to reduce Nominatim 429s."""
	try:
		last = frappe.cache().get_value(CACHE_KEY)
		now = time.time()
		if last:
			elapsed = now - float(last)
			if elapsed < MIN_INTERVAL_SECONDS:
				time.sleep(MIN_INTERVAL_SECONDS - elapsed)
		frappe.cache().set_value(CACHE_KEY, time.time(), expires_in_sec=60)
	except Exception:
		pass
