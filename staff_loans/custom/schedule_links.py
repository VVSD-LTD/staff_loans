import re
from urllib.parse import quote

import frappe
from frappe import _
from frappe.utils import cint, flt

ANCHOR_RE = re.compile(r"<a\b([^>]*)>(.*?)</a>", re.IGNORECASE | re.DOTALL)
ATTR_RE = re.compile(r"""([\w:-]+)\s*=\s*"([^"]*)\"""", re.IGNORECASE)
PAID_TOLERANCE = 0.004


def _attrs(raw):
	return {match.group(1).lower(): match.group(2) for match in ATTR_RE.finditer(raw or "")}


def iter_references(value):
	"""Yield name, doctype and amount from a reference field.

	Legacy rows store a plain document name. New rows store one or more anchors.
	"""
	if not value:
		return
	text = str(value)
	if "<a" not in text.lower():
		name = text.strip()
		if name:
			yield {"name": name, "doctype": None, "amount": None}
		return
	for match in ANCHOR_RE.finditer(text):
		attrs = _attrs(match.group(1))
		name = re.sub(r"<[^>]+>", "", match.group(2)).strip()
		if not name:
			continue
		raw_amount = attrs.get("data-value")
		amount = flt(raw_amount) if raw_amount not in (None, "") else None
		yield {"name": name, "doctype": attrs.get("title") or None, "amount": amount}


def reference_names(value):
	return [ref["name"] for ref in iter_references(value)]


def reference_amount(value, name):
	total = 0
	found = False
	for ref in iter_references(value):
		if ref["name"] != name or ref["amount"] is None:
			continue
		total += flt(ref["amount"])
		found = True
	return total if found else None


def _anchor(doctype, name, amount):
	slug = (doctype or "").strip().lower().replace(" ", "-")
	href = f"/app/{slug}/{quote(name, safe='')}" if slug else "#"
	amount_attr = ""
	if amount is not None:
		amount_attr = f' data-value="{flt(amount)}"'
	title = frappe.utils.escape_html(doctype or "")
	label = frappe.utils.escape_html(name)
	return f'<a href="{href}" target="_blank" title="{title}"{amount_attr}>{label}</a>'


def _normalize(current, doctype):
	refs = []
	if current and "<a" not in str(current).lower():
		name = str(current).strip()
		if name:
			refs.append({"name": name, "doctype": doctype, "amount": None})
		return refs
	for ref in iter_references(current):
		refs.append(
			{
				"name": ref["name"],
				"doctype": ref["doctype"] or doctype,
				"amount": ref["amount"],
			}
		)
	return refs


def _render(refs, doctype):
	return " ".join(_anchor(ref["doctype"] or doctype, ref["name"], ref["amount"]) for ref in refs)


def append_reference(current, doctype, name, amount=None):
	name = (name or "").strip()
	if not name:
		return current or ""
	refs = _normalize(current, doctype)
	updated = False
	for ref in refs:
		if ref["name"] != name:
			continue
		if amount is not None:
			ref["amount"] = flt(ref["amount"]) + flt(amount)
		ref["doctype"] = ref["doctype"] or doctype
		updated = True
		break
	if not updated:
		refs.append(
			{
				"name": name,
				"doctype": doctype,
				"amount": flt(amount) if amount is not None else None,
			}
		)
	return _render(refs, doctype)


def set_reference_amount(current, doctype, name, amount):
	html, _removed = remove_reference(current, name)
	return append_reference(html, doctype, name, amount)


def remove_reference(current, name):
	"""Drop every anchor for name. Returns the new html and the summed data-value, if any."""
	name = (name or "").strip()
	if not name:
		return current or "", 0
	if current and "<a" not in str(current).lower():
		if str(current).strip() == name:
			return "", None
		return current, 0
	kept = []
	removed = 0
	found_amount = False
	for ref in iter_references(current):
		if ref["name"] == name:
			if ref["amount"] is not None:
				removed += flt(ref["amount"])
				found_amount = True
			continue
		kept.append(ref)
	doctype = kept[0]["doctype"] if kept else ""
	return _render(kept, doctype), (removed if found_amount else None)


def row_paid_amount(row):
	paid = flt(row.amount_paid)
	if (
		paid == 0
		and cint(row.is_paid)
		and flt(row.salary_paid) == 0
		and flt(row.external_paid) == 0
	):
		return flt(row.total_payment)
	return paid


def unpaid_portion(row):
	return max(flt(row.total_payment) - row_paid_amount(row), 0)


def sync_row_paid(row):
	row.amount_paid = flt(row.salary_paid) + flt(row.external_paid)
	row.is_paid = 1 if flt(row.total_payment) > 0 and row.amount_paid + PAID_TOLERANCE >= flt(row.total_payment) else 0


def schedule_paid_total(staff_loan):
	return sum(row_paid_amount(row) for row in staff_loan.repayment_schedule)


def _salary_slip_rows(names):
	if not names:
		return []
	return frappe.db.sql(
		"""
		SELECT ss.name, ss.docstatus, sd.name AS detail_name, sd.additional_salary
		FROM `tabSalary Detail` sd
		INNER JOIN `tabSalary Slip` ss ON ss.name = sd.parent
		WHERE sd.additional_salary IN %(names)s
			AND sd.parenttype = 'Salary Slip'
			AND ss.docstatus < 2
		""",
		{"names": tuple(names)},
		as_dict=True,
	)


def salary_slip_state(names):
	rows = _salary_slip_rows(names)
	if any(cint(row.docstatus) == 1 for row in rows):
		return "submitted", rows
	if rows:
		return "draft", rows
	return None, []


def _cancel_additional_salaries(names):
	frappe.flags.skip_staff_loan_salary_unlink = True
	try:
		for name in names:
			if cint(frappe.db.get_value("Additional Salary", name, "docstatus")) != 1:
				continue
			document = frappe.get_doc("Additional Salary", name)
			document.flags.ignore_links = True
			document.cancel()
	finally:
		frappe.flags.skip_staff_loan_salary_unlink = False


def _amend_additional_salary(name, amount):
	document = frappe.get_doc("Additional Salary", name)
	if flt(document.amount) == flt(amount) and cint(document.docstatus) == 1:
		return document.name
	frappe.flags.skip_staff_loan_salary_unlink = True
	try:
		if cint(document.docstatus) == 1:
			document.flags.ignore_links = True
			document.cancel()
			document.reload()
		amendment = frappe.copy_doc(document)
		amendment.docstatus = 0
		amendment.amended_from = document.name
		amendment.amount = flt(amount)
		amendment.overwrite_salary_structure_amount = 0
		amendment.save()
		amendment.submit()
		return amendment.name
	finally:
		frappe.flags.skip_staff_loan_salary_unlink = False


def _update_draft_slips(slip_rows, new_name, new_amount):
	by_slip = {}
	for row in slip_rows:
		if cint(row.docstatus) != 0:
			continue
		by_slip.setdefault(row.name, []).append(row)
	for slip_name, details in by_slip.items():
		slip = frappe.get_doc("Salary Slip", slip_name)
		detail_names = {detail.detail_name for detail in details}
		salary_names = {detail.additional_salary for detail in details}
		for deduction in slip.deductions:
			if deduction.name in detail_names or deduction.additional_salary in salary_names:
				deduction.amount = flt(new_amount)
				if new_name:
					deduction.additional_salary = new_name
		slip.set_net_pay()
		slip.flags.ignore_validate = True
		slip.save()


def _set_salary_remainder(row, names, remainder, slip_rows):
	if not names:
		return
	new_name = _amend_additional_salary(names[-1], remainder)
	row.payment_reference = set_reference_amount(row.payment_reference, "Additional Salary", names[-1], 0)
	if new_name != names[-1]:
		row.payment_reference, _removed = remove_reference(row.payment_reference, names[-1])
		row.payment_reference = append_reference(row.payment_reference, "Additional Salary", new_name, 0)
	if slip_rows:
		_update_draft_slips(slip_rows, new_name, remainder)


def apply_external_repayment(loan, amount, source):
	"""Apply an external repayment or write-off onto existing installment rows."""
	staff_loan = frappe.get_doc("Staff Loan", loan)
	amount = flt(amount)
	source = (source or "").strip()
	if amount <= 0:
		frappe.throw(_("Amount must be greater than zero"))
	if not source:
		frappe.throw(_("Repayment reference is missing"))

	pending = flt(staff_loan.total_payment) - schedule_paid_total(staff_loan)
	if amount > pending + PAID_TOLERANCE:
		frappe.throw(_("Repayment amount cannot be greater than pending loan amount"))

	rows = [row for row in staff_loan.repayment_schedule if unpaid_portion(row) > PAID_TOLERANCE]
	rows.sort(key=lambda row: (str(row.payment_date), cint(row.idx)))
	remaining = amount

	for row in rows:
		if remaining <= PAID_TOLERANCE:
			break
		unpaid = unpaid_portion(row)
		names = reference_names(row.payment_reference)
		slip_state, slip_rows = salary_slip_state(names)

		if slip_state == "submitted":
			continue
		if slip_state == "draft" and remaining + PAID_TOLERANCE >= unpaid:
			continue

		portion = min(remaining, unpaid)
		covers_row = portion + PAID_TOLERANCE >= unpaid
		row.external_paid = flt(row.external_paid) + portion
		row.repayment_reference = append_reference(
			row.repayment_reference, "Staff Loan Repayment", source, portion
		)
		if covers_row:
			if names and slip_state is None:
				_cancel_additional_salaries(names)
				row.payment_reference = ""
		else:
			_set_salary_remainder(row, names, unpaid - portion, slip_rows)
		sync_row_paid(row)
		remaining -= portion

	if remaining > PAID_TOLERANCE:
		frappe.throw(
			_(
				"This repayment does not fit on the open installments. {0} is still unapplied because a salary deduction on a submitted slip was left unchanged."
			).format(frappe.format_value(remaining, {"fieldtype": "Currency"}))
		)

	staff_loan.save()
	return "pass"


def _sum_anchor_amounts(value):
	refs = list(iter_references(value))
	if not refs or any(ref["amount"] is None for ref in refs):
		return None
	return sum(flt(ref["amount"]) for ref in refs)


def reverse_external_repayment(loan, source):
	"""Remove one repayment document from the schedule rows that carry its link.

	Only that document's data-value is removed. Any other repayment on the same
	row stays, and the salary deduction is put back to the unpaid remainder.
	"""
	staff_loan = frappe.get_doc("Staff Loan", loan)
	source = (source or "").strip()
	changed = False
	for row in staff_loan.repayment_schedule:
		if source not in reference_names(row.repayment_reference):
			continue
		removed = reference_amount(row.repayment_reference, source)
		row.repayment_reference, legacy_removed = remove_reference(row.repayment_reference, source)
		if removed is None:
			removed = legacy_removed
		anchored = _sum_anchor_amounts(row.repayment_reference)
		if anchored is not None:
			row.external_paid = anchored
		else:
			if removed is None:
				removed = flt(row.external_paid)
			row.external_paid = max(flt(row.external_paid) - flt(removed or 0), 0)
		sync_row_paid(row)
		changed = True
		_restore_salary_after_reversal(row)
	if changed:
		staff_loan.save()


def _restore_salary_after_reversal(row):
	remainder = unpaid_portion(row)
	if remainder <= PAID_TOLERANCE:
		return
	names = reference_names(row.payment_reference)
	if not names:
		return
	slip_state, slip_rows = salary_slip_state(names)
	if slip_state == "submitted":
		return
	_set_salary_remainder(row, names, remainder, slip_rows)


def unlink_additional_salary(additional_salary):
	"""Drop a salary link when that Additional Salary is cancelled."""
	if frappe.flags.get("skip_staff_loan_salary_unlink"):
		return
	name = additional_salary.name
	rows = frappe.db.sql(
		"""
		SELECT DISTINCT parent
		FROM `tabStaff Loan Repayment Schedule`
		WHERE payment_reference LIKE %(needle)s
		""",
		{"needle": f"%{name}%"},
		as_dict=True,
	)
	for row in rows:
		staff_loan = frappe.get_doc("Staff Loan", row.parent)
		changed = False
		for schedule_row in staff_loan.repayment_schedule:
			if name not in reference_names(schedule_row.payment_reference):
				continue
			amount = reference_amount(schedule_row.payment_reference, name)
			schedule_row.payment_reference, legacy_removed = remove_reference(
				schedule_row.payment_reference, name
			)
			if amount is None:
				amount = legacy_removed
			anchored = _sum_anchor_amounts(schedule_row.payment_reference)
			if anchored is not None:
				schedule_row.salary_paid = anchored
			elif amount:
				schedule_row.salary_paid = max(flt(schedule_row.salary_paid) - flt(amount), 0)
			elif cint(schedule_row.is_paid) and flt(schedule_row.external_paid) == 0:
				schedule_row.salary_paid = 0
			sync_row_paid(schedule_row)
			changed = True
		if changed:
			staff_loan.save()
