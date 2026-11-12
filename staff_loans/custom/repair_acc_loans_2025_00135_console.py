# Paste into System Console (Python) after migrating the updated staff_loans app.
# Run it once with Commit unchecked to preview. Tick Commit and run it again to keep the fix.
# Migrating already repairs this loan. Running this as well is safe.

frappe.call("staff_loans.patches.v1_0.backfill_schedule_amounts.repair_acc_loans_2025_00135")

loan = frappe.get_doc("Staff Loan", "ACC-LOANS-2025-00135")
print(
	loan.name
	+ " status="
	+ str(loan.status)
	+ " paid="
	+ str(loan.total_amount_paid)
	+ " of "
	+ str(loan.total_payment)
)
for row in loan.repayment_schedule:
	if str(row.payment_date) < "2026-09-01":
		continue
	print(
		str(row.payment_date)
		+ " installment="
		+ str(row.total_payment)
		+ " paid="
		+ str(row.amount_paid)
		+ " salary="
		+ str(row.salary_paid)
		+ " external="
		+ str(row.external_paid)
		+ " deducted="
		+ str(row.is_paid)
	)

for salary_name in ("HR-ADS-26-10-00143-1", "HR-ADS-26-11-00001"):
	if frappe.db.exists("Additional Salary", salary_name):
		salary = frappe.db.get_value(
			"Additional Salary", salary_name, ["amount", "docstatus"], as_dict=True
		)
		print(salary_name + " amount=" + str(salary.amount) + " docstatus=" + str(salary.docstatus))

slip = frappe.get_doc("Salary Slip", "Sal Slip/HR-EMP-00328/00027")
staff_loan_amount = None
staff_loan_link = None
for deduction in slip.deductions:
	if deduction.salary_component == "Staff Loan":
		staff_loan_amount = deduction.amount
		staff_loan_link = deduction.additional_salary
print(
	"Slip "
	+ slip.name
	+ " docstatus="
	+ str(slip.docstatus)
	+ " staff_loan="
	+ str(staff_loan_amount)
	+ " link="
	+ str(staff_loan_link)
	+ " net_pay="
	+ str(slip.net_pay)
)

journals = frappe.get_all(
	"Journal Entry",
	filters={"cheque_no": "ACC-REP-2026-00002", "docstatus": 1},
	fields=["name", "total_debit"],
)
if journals:
	print("Repayment journal kept: " + journals[0].name + " debit=" + str(journals[0].total_debit))
else:
	print("No submitted journal found for ACC-REP-2026-00002")

print("Expected: paid 1900000, October unpaid, Nov 2026-May 2027 external 100000, slip net_pay 255284, journal still submitted.")
