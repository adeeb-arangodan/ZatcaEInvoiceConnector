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

    _autosize_columns(sheet)
    return workbook


def _autosize_columns(sheet):
    for column_cells in sheet.columns:
        length = max((len(str(cell.value)) for cell in column_cells if cell.value is not None), default=0)
        sheet.column_dimensions[column_cells[0].column_letter].width = min(max(length + 2, 10), 40)


VAT_EXEMPTION_ITEM_HEADERS = [
    "Type", "Invoice Number", "Issue Date", "Customer", "Item Code", "Item",
    "VAT Exception Reason", "Qty", "Unit Price", "Gross Amount", "Discount Share",
    "Amount After Discount",
]


def build_vat_exemption_item_workbook(rows, total):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "VAT Exemption Items"

    sheet.append(VAT_EXEMPTION_ITEM_HEADERS)
    for cell in sheet[1]:
        cell.font = Font(bold=True)

    for row in rows:
        sheet.append([
            row["type"], row["invoice_number"], row["issue_date"], row["customer_name"],
            row["code"], row["name"], row["reason"], row["qty"], row["price"],
            row["gross_amount"], row["discount_share"], row["amount_after_discount"],
        ])

    sheet.append([
        f"Total ({len(rows)} item{'s' if len(rows) != 1 else ''})", "", "", "", "", "", "", "", "", "", "", total,
    ])
    for cell in sheet[sheet.max_row]:
        cell.font = Font(bold=True)

    _autosize_columns(sheet)
    return workbook


def build_vat_exemption_invoice_workbook(rows, reason_codes, grand_total_amounts, grand_total):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "VAT Exemption by Invoice"

    headers = ["Type", "Invoice Number", "Issue Date", "Customer"] + reason_codes + ["Total"]
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True)

    for row in rows:
        sheet.append([
            row["type"], row["invoice_number"], row["issue_date"], row["customer_name"],
            *row["amounts"], row["row_total"],
        ])

    blank_lead_cells = ["", "", ""]
    sheet.append([f"Grand Total ({len(rows)} invoice{'s' if len(rows) != 1 else ''})", *blank_lead_cells, *grand_total_amounts, grand_total])
    for cell in sheet[sheet.max_row]:
        cell.font = Font(bold=True)

    _autosize_columns(sheet)
    return workbook
