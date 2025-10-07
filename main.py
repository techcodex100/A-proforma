import re
import csv
import os
import tempfile
import yagmail
import pdfplumber
import pytesseract
from pdf2image import convert_from_path
from typing import Dict
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse
from PyPDF2 import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

app = FastAPI(title="Proforma ↔ Agreement Matcher & SWIFT Generator")

SEAL_PATH = "seal.png"
SIGN_PATH = "sign.png"

SENDER_EMAIL = "team.codex1209@gmail.com"
SENDER_PASSWORD = "ieiu oylf tauy wbvf"

SELLER_EMAIL = "team.codex1209@gmail.com"
BUYER_EMAIL = "techcodexautomation@gmail.com"


def normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip()) if s else ""


def extract_text_from_pdf(path: str) -> str:
    text = ""
    try:
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    text += t + "\n"
    except Exception:
        pass

    if not text.strip():
        images = convert_from_path(path, dpi=300)
        for img in images:
            text += pytesseract.image_to_string(img) + "\n"
    return text


def parse_proforma_fields(text: str) -> Dict[str, str]:
    data = {}
    match = re.search(r"(AGR|PF)[-\s]?\d{4}[-\s]?\d{3,}", text, re.I)
    data["contract_no"] = normalize(match.group(0)) if match else ""
    date_match = re.search(r"\b(20\d{2}[-/]\d{2}[-/]\d{2})\b", text)
    data["date"] = date_match.group(1) if date_match else ""
    acc_match = re.search(r"A/C\s*No\.?:\s*([0-9]+)", text, re.I)
    data["sender_account"] = acc_match.group(1).strip() if acc_match else ""
    swift_match = re.search(r"SWIFT\s*[:\-]?\s*([A-Z0-9]{8,11})", text, re.I)
    data["sender_swift"] = swift_match.group(1).strip() if swift_match else ""
    seller_match = re.search(r"(Seller|Exporter)\s*[:\-]?\s*(.+)", text, re.I)
    data["seller_name"] = normalize(seller_match.group(2).split("\n")[0]) if seller_match else ""
    bank_match = re.search(r"(Bank\s*of\s*Exporter|Bank)\s*[:\-]?\s*(.+)", text, re.I)
    data["seller_bank"] = normalize(bank_match.group(2).split("\n")[0]) if bank_match else ""
    addr_match = re.search(r"(Address)\s*[:\-]?\s*(.+)", text, re.I)
    data["seller_address"] = normalize(addr_match.group(2).split("\n")[0]) if addr_match else ""
    currency_match = re.search(r"Currency\s*[:\-]?\s*([A-Z]{3})", text, re.I)
    data["amount_currency"] = currency_match.group(1).strip() if currency_match else "USD"
    amount_match = re.search(r"Amount\s*[:\-]?\s*([\d,.]+)", text, re.I)
    data["amount_numeric"] = amount_match.group(1).strip() if amount_match else "0,00"
    return data


def parse_agreement_fields(text: str) -> Dict[str, str]:
    data = {}
    match = re.search(r"Contract\s*No[:\s]*([A-Z0-9-]+)", text, re.I)
    data["contract_no"] = normalize(match.group(1)) if match else ""
    date_match = re.search(r"Date[:\s]*([0-9-]+)", text, re.I)
    data["date"] = date_match.group(1) if date_match else ""
    acc_match = re.search(r"Account\s*No\.?:\s*([0-9]+)", text, re.I)
    data["sender_account"] = acc_match.group(1) if acc_match else ""
    swift_match = re.search(r"SWIFT\s*[:\-]?\s*([A-Z0-9]{8,11})", text, re.I)
    data["sender_swift"] = swift_match.group(1).strip() if swift_match else "BKIDINBBXXX"
    load = re.search(r"Loading\s*Port[:\s]*(.*?)Destination", text, re.I | re.S)
    data["loading_port"] = normalize(load.group(1)) if load else ""
    dest = re.search(r"Destination\s*Port[:\s]*(.*?)Shipment", text, re.I | re.S)
    data["destination_port"] = normalize(dest.group(1)) if dest else ""
    seller_match = re.search(r"(Seller|Exporter)\s*[:\-]?\s*(.+)", text, re.I)
    data["seller_name"] = normalize(seller_match.group(2).split("\n")[0]) if seller_match else ""
    bank_match = re.search(r"(Bank\s*of\s*Exporter|Bank)\s*[:\-]?\s*(.+)", text, re.I)
    data["seller_bank"] = normalize(bank_match.group(2).split("\n")[0]) if bank_match else ""
    addr_match = re.search(r"(Address)\s*[:\-]?\s*(.+)", text, re.I)
    data["seller_address"] = normalize(addr_match.group(2).split("\n")[0]) if addr_match else ""
    currency_match = re.search(r"Currency\s*[:\-]?\s*([A-Z]{3})", text, re.I)
    data["amount_currency"] = currency_match.group(1).strip() if currency_match else "USD"
    amount_match = re.search(r"Amount\s*[:\-]?\s*([\d,.]+)", text, re.I)
    data["amount_numeric"] = amount_match.group(1).strip() if amount_match else "0,00"
    return data


def compare_fields(p: Dict[str, str], a: Dict[str, str]) -> Dict[str, int]:
    keys = ["contract_no", "sender_account", "sender_swift", "loading_port", "destination_port"]
    matches = {}
    for k in keys:
        v1, v2 = normalize(p.get(k, "")).lower(), normalize(a.get(k, "")).lower()
        matches[k] = 1 if re.sub(r"[^\d.]", "", v1) == re.sub(r"[^\d.]", "", v2) or (v1 and v1 in v2) else 0
    return matches


def create_swift_pdf(prof: Dict[str, str], output_path: str):
    c = canvas.Canvas(output_path, pagesize=A4)
    w, h = A4
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, h - 60, "SWIFT Message MT103 – Generated")

    y = h - 90
    c.setFont("Helvetica", 10)
    c.drawString(50, y, "Sender (Ordering Customer):"); y -= 15
    c.drawString(70, y, f"{prof.get('seller_name', '')}"); y -= 15
    c.drawString(70, y, f"Account: {prof.get('sender_account', '')}"); y -= 15
    c.drawString(70, y, f"Bank: {prof.get('seller_bank', '')}"); y -= 15
    c.drawString(70, y, f"Address: {prof.get('seller_address', '')}"); y -= 15

    y -= 10
    c.drawString(50, y, "Receiver (Beneficiary):"); y -= 15
    c.drawString(70, y, f"{prof.get('seller_name', '')}"); y -= 15
    c.drawString(70, y, f"Account: {prof.get('sender_account', '')}"); y -= 15
    c.drawString(70, y, f"Bank: {prof.get('seller_bank', '')}"); y -= 15
    c.drawString(70, y, f"Address: {prof.get('seller_address', '')}"); y -= 15

    y -= 10
    c.drawString(50, y, "SWIFT Message (MT103 Format):"); y -= 15
    c.drawString(70, y, f":20:{prof.get('contract_no', '')}"); y -= 15
    c.drawString(70, y, ":23B:CRED"); y -= 15
    c.drawString(70, y, f":32A:{prof.get('date', '').replace('-', '')}{prof.get('amount_currency', '')}{prof.get('amount_numeric', '')}"); y -= 15
    c.drawString(70, y, f":50K:/{prof.get('sender_account', '')}"); y -= 15
    c.drawString(70, y, f"{prof.get('seller_name', '')}"); y -= 15
    c.drawString(70, y, f"{prof.get('seller_address', '')}"); y -= 15
    c.drawString(70, y, f":59:/{prof.get('sender_account', '')}"); y -= 15
    c.drawString(70, y, f"{prof.get('seller_name', '')}"); y -= 15
    c.drawString(70, y, f"{prof.get('seller_address', '')}"); y -= 15
    c.drawString(70, y, f":70:{prof.get('contract_no', '')}"); y -= 15
    c.drawString(70, y, ":71A:OUR")
    c.save()


def sign_pdf(input_pdf: str, output_pdf: str):
    reader = PdfReader(input_pdf)
    writer = PdfWriter()
    overlay_fd, overlay_path = tempfile.mkstemp(suffix=".pdf")
    os.close(overlay_fd)
    c = canvas.Canvas(overlay_path, pagesize=A4)
    if os.path.exists(SEAL_PATH):
        c.drawImage(SEAL_PATH, 400, 100, width=120, height=70, mask='auto')
    if os.path.exists(SIGN_PATH):
        c.drawImage(SIGN_PATH, 300, 50, width=120, height=60, mask='auto')
    c.save()
    overlay_reader = PdfReader(overlay_path)
    overlay_page = overlay_reader.pages[0]
    for page in reader.pages:
        page.merge_page(overlay_page)
        writer.add_page(page)
    with open(output_pdf, "wb") as f:
        writer.write(f)
    os.remove(overlay_path)
    return output_pdf


def send_mail(to_email: str, subject: str, body: str, attachment_path: str):
    yag = yagmail.SMTP(SENDER_EMAIL, SENDER_PASSWORD)
    yag.send(to=to_email, subject=subject, contents=body, attachments=[attachment_path])


@app.post("/compare/")
async def compare_files(proforma_file: UploadFile = File(...), agreement_file: UploadFile = File(...)):
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as ptmp:
            ptmp.write(await proforma_file.read())
            p_path = ptmp.name
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as atmp:
            atmp.write(await agreement_file.read())
            a_path = atmp.name

        p_text = extract_text_from_pdf(p_path)
        a_text = extract_text_from_pdf(a_path)

        p_data = parse_proforma_fields(p_text)
        a_data = parse_agreement_fields(a_text)

        # Fill missing seller details from Agreement
        if not p_data.get("seller_name"):
            p_data["seller_name"] = a_data.get("seller_name", "")
        if not p_data.get("seller_bank"):
            p_data["seller_bank"] = a_data.get("seller_bank", "")
        if not p_data.get("seller_address"):
            p_data["seller_address"] = a_data.get("seller_address", "")

        matches = compare_fields(p_data, a_data)

        csv_path = os.path.join(tempfile.gettempdir(), "json.csv")
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["field", "match"])
            for k, v in matches.items():
                writer.writerow([k, v])

        signed_pdf = os.path.join(tempfile.gettempdir(), "Proforma_Signed.pdf")
        swift_pdf = os.path.join(tempfile.gettempdir(), "SWIFT_MT103.pdf")

        sign_pdf(p_path, signed_pdf)
        create_swift_pdf(p_data, swift_pdf)

        match_message = "successful" if all(v == 1 for v in matches.values()) else "unsuccessful"

        # Send emails
        if match_message == "successful":
            send_mail(BUYER_EMAIL, "SWIFT Message - Verified", "Please find attached SWIFT Message PDF.", swift_pdf)
            send_mail(SELLER_EMAIL, "Proforma Invoice - Signed Copy", "Please find attached signed Proforma Invoice PDF.", signed_pdf)

        return JSONResponse({
            "match_message": match_message,
            "matches": matches,
            "proforma_extracted": p_data,
            "agreement_extracted": a_data,
            "signed_proforma_path": signed_pdf,
            "swift_pdf_path": swift_pdf,
            "csv_path": csv_path
        })

    except Exception as e:
        return {"error": "Unknown error", "details": str(e)}


@app.get("/")
def home():
    return {"message": "Proforma ↔ Agreement Matcher with SWIFT Generator is running!"}
