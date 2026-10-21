# Copyright (c) 2025, VV System Developers LTD and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from staff_loans.custom.loan import validate_repayment_jv_accounts


class StaffLoanCompanySetting(Document):
	def validate(self):
		validate_repayment_jv_accounts(self)
