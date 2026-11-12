import frappe
from frappe.utils import cint, flt

from staff_loans.custom.schedule_links import set_reference_amount


LOAN = "ACC-LOANS-2025-00135"
REPAYMENT = "ACC-REP-2026-00002"
SALARY_100K = "HR-ADS-26-11-00001"
SALARY_700K = "HR-ADS-26-10-00143-1"
SLIP = "Sal Slip/HR-EMP-00328/00027"
BAD_ROW_NAMES = {"6454", "6455", "6456"}

RESTORED_ROWS = (
	("2026-10-01", 700000, False),
	("2026-11-01", 600000, True),
	("2026-12-01", 500000, True),
	("2027-01-01", 400000, True),
	("2027-02-01", 300000, True),
	("2027-03-01", 200000, True),
	("2027-04-01", 100000, True),
	("2027-05-01", 0, True),
)


def execute():
	backfill_amounts()
	wrap_legacy_references()
	refresh_loan_totals()
	repair_acc_loans_2025_00135()


def backfill_amounts():
	frappe.db.sql(
		"""
		UPDATE `tabStaff Loan Repayment Schedule`
		SET
			amount_paid = CASE WHEN is_paid = 1 THEN total_payment ELSE 0 END,
			salary_paid = CASE WHEN is_paid = 1 AND IFNULL(outsource, 0) = 0 THEN total_payment ELSE 0 END,
			external_paid = CASE WHEN is_paid = 1 AND IFNULL(outsource, 0) = 1 THEN total_payment ELSE 0 END
		WHERE IFNULL(amount_paid, 0) = 0
			AND IFNULL(salary_paid, 0) = 0
			AND IFNULL(external_paid, 0) = 0
			AND is_paid = 1
		"""
	)


def wrap_legacy_references():
	rows = frappe.db.sql(
		"""
		SELECT name, parent, payment_reference, repayment_reference, is_paid, outsource, total_payment
		FROM `tabStaff Loan Repayment Schedule`
		WHERE (IFNULL(payment_reference, '') != '' AND payment_reference NOT LIKE '%<a%')
			OR (IFNULL(repayment_reference, '') != '' AND repayment_reference NOT LIKE '%<a%')
		""",
		as_dict=True,
	)
	for row in rows:
		updates = {}
		if row.payment_reference and "<a" not in row.payment_reference.lower():
			salary_amount = flt(row.total_payment) if cint(row.is_paid) and not cint(row.outsource) else 0
			updates["payment_reference"] = set_reference_amount(
				"", "Additional Salary", row.payment_reference.strip(), salary_amount
			)
		if row.repayment_reference and "<a" not in row.repayment_reference.lower():
			external_amount = flt(row.total_payment) if cint(row.is_paid) else 0
			updates["repayment_reference"] = set_reference_amount(
				"", "Staff Loan Repayment", row.repayment_reference.strip(), external_amount
			)
		if updates:
			frappe.db.set_value(
				"Staff Loan Repayment Schedule", row.name, updates, update_modified=False
			)


def refresh_loan_totals():
	frappe.db.sql(
		"""
		UPDATE `tabStaff Loan` loan
		SET total_amount_paid = (
			SELECT IFNULL(SUM(schedule.amount_paid), 0)
			FROM `tabStaff Loan Repayment Schedule` schedule
			WHERE schedule.parent = loan.name
				AND schedule.parenttype = 'Staff Loan'
				AND schedule.parentfield = 'repayment_schedule'
		)
		WHERE loan.docstatus = 1
		"""
	)


@frappe.whitelist()
def repair_acc_loans_2025_00135():
	"""Repair ACC-LOANS-2025-00135. Safe to run more than once."""
	frappe.only_for("System Manager")
	if not frappe.db.exists("Staff Loan", LOAN):
		return
	if not frappe.db.exists("Additional Salary", SALARY_100K):
		frappe.throw(f"Cannot repair {LOAN}: {SALARY_100K} is missing")
	if cint(frappe.db.get_value("Additional Salary", SALARY_100K, "docstatus")) != 1:
		frappe.throw(f"Cannot repair {LOAN}: {SALARY_100K} is not submitted")

	cancel_replaced_salary()
	restore_schedule()
	fix_october_slip()


def cancel_replaced_salary():
	if not frappe.db.exists("Additional Salary", SALARY_700K):
		return
	if cint(frappe.db.get_value("Additional Salary", SALARY_700K, "docstatus")) != 1:
		return
	frappe.flags.skip_staff_loan_salary_unlink = True
	try:
		document = frappe.get_doc("Additional Salary", SALARY_700K)
		document.flags.ignore_links = True
		document.cancel()
	finally:
		frappe.flags.skip_staff_loan_salary_unlink = False


def restore_schedule():
	loan = frappe.get_doc("Staff Loan", LOAN)
	for row in list(loan.repayment_schedule):
		if _is_bad_row(row):
			loan.remove(row)

	for payment_date, balance, external in RESTORED_ROWS:
		row = _row_for_date(loan, payment_date)
		if not row:
			row = loan.append("repayment_schedule", {})
		row.payment_date = payment_date
		row.principal_amount = 100000
		row.total_payment = 100000
		row.balance_loan_amount = balance
		row.outsource = 1 if external else 0
		row.salary_paid = 0
		row.external_paid = 100000 if external else 0
		row.amount_paid = 100000 if external else 0
		row.is_paid = 1 if external else 0
		if external:
			row.payment_reference = ""
			row.repayment_reference = set_reference_amount("", "Staff Loan Repayment", REPAYMENT, 100000)
		else:
			row.repayment_reference = ""
			row.payment_reference = set_reference_amount("", "Additional Salary", SALARY_100K, 0)

	loan.repayment_schedule.sort(key=lambda schedule_row: str(schedule_row.payment_date))
	for index, schedule_row in enumerate(loan.repayment_schedule, start=1):
		schedule_row.idx = index
	loan.save()


def fix_october_slip():
	if not frappe.db.exists("Salary Slip", SLIP):
		return
	slip = frappe.get_doc("Salary Slip", SLIP)
	if cint(slip.docstatus) != 0:
		return
	changed = False
	for deduction in slip.deductions:
		if deduction.salary_component != "Staff Loan":
			continue
		if flt(deduction.amount) != 100000 or deduction.additional_salary != SALARY_100K:
			deduction.amount = 100000
			deduction.additional_salary = SALARY_100K
			changed = True
	if not changed and flt(slip.net_pay) == 255284:
		return
	slip.set_net_pay()
	slip.flags.ignore_validate = True
	slip.save()


def _is_bad_row(row):
	if str(row.name) in BAD_ROW_NAMES:
		return True
	if flt(row.total_payment) == 700000:
		return True
	return str(row.payment_date) == "2026-10-01" and flt(row.principal_amount) == 0


def _row_for_date(loan, payment_date):
	for row in loan.repayment_schedule:
		if str(row.payment_date) == payment_date:
			return row
	return None
