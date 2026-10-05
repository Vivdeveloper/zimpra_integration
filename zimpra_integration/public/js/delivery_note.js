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

	// Auto-send on submit is handled server-side in
	// webhook_job.auto_send_on_submit (reliable; no browser dependency).
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
