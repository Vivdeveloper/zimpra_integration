// Delivery Note → Zimpra Vehicle Portal
// If you also have a Desk Client Script for Delivery Note, disable that one
// to avoid double webhook calls.

frappe.ui.form.on("Delivery Note", {
	refresh(frm) {
		if (frm.doc.docstatus !== 1) return;

		frm.remove_custom_button("Send to Vehicle Portal");
		frm.remove_custom_button("Update to Vehicle Portal");

		if (frm.doc.custom_zimpra_status === "Success") {
			frm.add_custom_button(__("Update to Vehicle Portal"), () => {
				zimpra_trigger(frm, "manual_update", "Updating Vehicle Portal...");
			});
		} else {
			frm.add_custom_button(__("Send to Vehicle Portal"), () => {
				zimpra_trigger(frm, "manual_send", "Sending to Vehicle Portal...");
			});
		}
	},

	on_submit(frm) {
		// First submit should CREATE (manual_send), not UPDATE
		zimpra_maybe_auto_send(frm, "manual_send", "Sending to Vehicle Portal...");
	},
});

function zimpra_trigger(frm, method_name, freeze_message) {
	frappe.call({
		method: `zimpra_integration.zimpra_integration.background_jobs.webhook_job.${method_name}`,
		args: {
			doctype: frm.doc.doctype,
			doc_name: frm.doc.name,
		},
		freeze: true,
		freeze_message: __(freeze_message),
		callback(r) {
			if (r.exc) {
				frappe.msgprint({
					title: __("Zimpra Error"),
					message: __("Webhook failed to queue. Check Error Log."),
					indicator: "red",
				});
				return;
			}
			frappe.show_alert({
				message: __("Zimpra webhook queued. Status will update shortly."),
				indicator: "blue",
			});
			// Refresh after background job usually finishes
			setTimeout(() => frm.reload_doc(), 5000);
		},
		error() {
			frappe.msgprint({
				title: __("Zimpra Error"),
				message: __("Could not trigger webhook. Check Error Log."),
				indicator: "red",
			});
		},
	});
}

function zimpra_maybe_auto_send(frm, method_name, freeze_message) {
	const item_codes = (frm.doc.items || [])
		.map((row) => row.item_code)
		.filter(Boolean);

	if (!item_codes.length) {
		return;
	}

	// item_group is NOT on Delivery Note Item — fetch from Item master
	frappe.call({
		method: "frappe.client.get_list",
		args: {
			doctype: "Item",
			filters: { name: ["in", item_codes] },
			fields: ["name", "item_group"],
			limit_page_length: item_codes.length,
		},
		callback(r) {
			const rows = r.message || [];
			const group_map = {};
			rows.forEach((row) => {
				group_map[row.name] = row.item_group;
			});

			const all_alphalite = item_codes.every(
				(code) => group_map[code] === "Alphalite AAC"
			);

			if (!all_alphalite) {
				return;
			}

			zimpra_trigger(frm, method_name, freeze_message);
		},
		error() {
			frappe.msgprint({
				title: __("Zimpra Error"),
				message: __("Could not verify Item Group for Zimpra auto-send."),
				indicator: "orange",
			});
		},
	});
}
