# Copyright (c) 2023, VV System Developers LTD and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from staff_loans.custom.loan import validate_repayment_jv_accounts

class StaffLoanSettings(Document):
	def before_save(self):
		if self.enable_multi_company:
			self.credit_account = ""
			self.salary_component = ""
			self.debit_account = ""
			self.jv_posting_date_based_on = ""
			self.create_repayment_journal_entry = 0

	def validate(self):
		if not self.enable_multi_company:
			validate_repayment_jv_accounts(self)
