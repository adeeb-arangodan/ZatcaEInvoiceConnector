from openpyxl import Workbook
from openpyxl.styles import Font

HEADERS = [
    "Type", "Invoice Number", "Customer", "Issue Date", "Total", "Discount",
    "Net before Tax", "Tax", "Net with Tax", "ICV", "Remarks", "ZATCA Status",
]


def build_invoice_workbook(submissions, summary):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Invoices"

    sheet.append(HEADERS)
    for cell in sheet[1]:
        cell.font = Font(bold=True)

    for submission in submissions:
        sheet.append([
            submission.get_document_type_display(),
            submission.payload.get("invoice_number", ""),
            submission.payload.get("customer_name", ""),
            submission.payload.get("issue_date", ""),
            submission.total_amount,
            submission.discount_amount,
            submission.net_before_tax,
            submission.tax_amount,
            submission.net_with_tax,
            submission.icv,
            submission.remarks,
            submission.get_status_display(),
        ])

    count = summary["count"]
    sheet.append([
        f"Summary ({count} invoice{'s' if count != 1 else ''})", "", "", "",
        summary["total_amount"], summary["discount_amount"], summary["net_before_tax"],
        summary["tax_amount"], summary["net_with_tax"], "", "", "",
    ])
    for cell in sheet[sheet.max_row]:
        cell.font = Font(bold=True)

    for column_cells in sheet.columns:
        length = max((len(str(cell.value)) for cell in column_cells if cell.value is not None), default=0)
        sheet.column_dimensions[column_cells[0].column_letter].width = min(max(length + 2, 10), 40)

    return workbook
