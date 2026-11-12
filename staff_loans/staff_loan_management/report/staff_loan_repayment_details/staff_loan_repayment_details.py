# Copyright (c) 2023, VV System Developers LTD and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt

def execute(filters=None):
	columns, data = [], []
	columns = get_columns()
	data = get_data(filters)
	# chart_data = get_chart_data(data)
	return columns, data, None

def get_columns():
	return [
		{"fieldname": "applicant", "fieldtype": "Data", "label": _("Applicant"), "width": "150px"},
		{"fieldname": "applicant_name", "fieldtype": "Data", "label": _("Applicant Name"), "width": "150px"},
		{"fieldname": "company", "fieldtype": "Data", "label": _("Company"), "width": "150px"},
		{"fieldname": "loan", "fieldtype": "Data", "label": _("Loan"), "width": "100px"},
		{"fieldname": "total_payable_amount", "fieldtype": "Currency", "label": _("Total Payable Amount"), "width": "150px"},
		{"fieldname": "amount_paid_from_salary", "fieldtype": "Currency", "label": _("Amount Paid From Salary"), "width": "150px"},
		{"fieldname": "amount_paid_not_from_salary", "fieldtype": "Currency", "label": _("Amount Paid not From Salary"), "width": "150px"},
		{"fieldname": "write_off_amount", "fieldtype": "Currency", "label": _("Write Off Amount"), "width": "150px"},
		{"fieldname": "loan_balance", "fieldtype": "Currency", "label": _("Loan Balance"), "width": "150px"},
	]


@frappe.whitelist()
def get_data(filters):
	if filters.get("employee"):
		employee_filter = f"AND l.applicant = '{filters.employee}'"
	else:
		employee_filter = ""

	if filters.get("company"):
		company_filter = f"AND l.company = '{filters.company}'"
	else:
		company_filter = ""

	loans = frappe.db.sql(f"""
		SELECT
			l.applicant AS applicant, 
			l.applicant_name AS applicant_name,
			l.company AS company,
			l.name AS loan,
			l.loan_amount AS total_payable_amount,
			l.written_off_amount AS write_off_amount,
			(
				SELECT SUM(lrs.salary_paid) FROM `tabStaff Loan Repayment Schedule` lrs
				WHERE lrs.parent = l.name
				AND lrs.parentfield = 'repayment_schedule'
			) AS amount_paid_from_salary,
			(
				SELECT SUM(lrs.external_paid) FROM `tabStaff Loan Repayment Schedule` lrs
				WHERE lrs.parent = l.name
				AND lrs.parentfield = 'repayment_schedule'
			) AS amount_paid_not_from_salary,
			SUM(l.loan_amount - l.total_amount_paid) AS loan_balance
		FROM `tabStaff Loan` l 
		WHERE l.docstatus = 1
		AND l.status = "Disbursed" 
		{employee_filter}
		{company_filter}
		GROUP BY l.name ORDER BY loan,company ASC
		""", as_dict=1)
	return loans