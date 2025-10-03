import re
import io
import csv
import pdfplumber
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
import smtplib
from email.message import EmailMessage
import os

app = FastAPI(title="Proforma & Agreement Extractor + Matcher")

SELLER_EMAIL = "techcodexautomation@gmail.com"
SELLER_PASSWORD = "YOUR_EMAIL_PASSWORD"  # Use app password if Gmail
BUYER_SWIFT = "SWIFT MESSAGE: Buyer informed about matched Proforma."

# ---------------- Helper Functions ----------------

def normalize_text(text):
    """Remove special chars, commas, extra spaces, normalize string."""
    if not text:
        return "NOT FOUND"
    text = re.sub(r'[^A-Za-z0-9\s]', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip() or "NOT FOUND"

def extract_pdf_data(pdf_bytes):
    try:
        pdf_file = io.BytesIO(pdf_bytes)
        with pdfplumber.open(pdf_file) as pdf:
            text = "\n".join([page.extract_text() or "" for page in pdf.pages])
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"PDF extraction failed: {str(e)}")

    data = {}
    fields_regex = {
        'contract_no': r'Contract\s*No[:\s]*([A-Z0-9\-]+)',
        'date': r'Date[:\s]*([0-9]{4}[-/][0-9]{2}[-/][0-9]{2})',
        'buyer_name': r'(?:Buyer\s*Name|Company\s*Name)[:\s]*([A-Za-z0-9\s,&\.-]+)',
        'buyer_email': r'[\w\.-]+@[\w\.-]+',
        'website': r'(?:Website|Web)[:\s]*(https?://[^\s]+|www\.[^\s]+)',
        'address': r'Address[:\s]*(.+?)(?:\n|GSTIN|$)',
        'gstin': r'GSTIN[:\s]*([A-Z0-9]+)',
        'packing': r'Packing[:\s]*(.+?)(?:\n|$)',
        'loading_port': r'Loading\s*Port[:\s]*(.+?)(?:\n|$)',
        'destination_port': r'Destination\s*Port[:\s]*(.+?)(?:\n|$)',
        'shipment_date': r'Shipment\s*Date[:\s]*(.+?)(?:\n|$)',
        'seller_bank': r'Seller\s*Bank[:\s]*(.+?)(?:\n|$)',
        'buyer_bank': r'Buyer\s*Bank[:\s]*(.+?)(?:\n|$)',
        'account_no': r'Account\s*No[:\s]*(.+?)(?:\n|$)',
        'documents': r'Documents[:\s]*(.+?)(?:\n|$)',
        'payment_terms': r'Payment\s*Terms[:\s]*(.+?)(?:\n|$)',
    }

    for key, pattern in fields_regex.items():
        match = re.search(pattern, text, re.I | re.S)
        try:
            data[key] = normalize_text(match.group(1) if match and match.lastindex else "")
        except IndexError:
            data[key] = "NOT FOUND"

    # Line items
    products = re.findall(r'([A-Za-z\s]+)\s+(\d+)\s+([0-9,\.]+)\s+([A-Za-z$/]+)', text)
    data['line_items'] = [
        {
            "product_name": normalize_text(p[0]),
            "product_quantity": normalize_text(p[1]),
            "product_price": normalize_text(p[2]),
            "product_amount": normalize_text(p[3])
        } for p in products
    ]

    return data

def compare_data(proforma, agreement):
    comparison = {"match_message": "Unsuccessful Match", "matches": [], "unmatched": []}
    for key in proforma:
        if key in agreement:
            if proforma[key] == agreement[key]:
                comparison["matches"].append(key)
            else:
                comparison["unmatched"].append(key)
    if not comparison["unmatched"]:
        comparison["match_message"] = "Successful Match"
    return comparison

def save_to_csv(proforma, agreement, comparison, path='comparison.csv'):
    keys = list(proforma.keys())
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["Field", "Proforma", "Agreement", "Match"])
        for key in keys:
            pro_val = str(proforma.get(key, "NOT FOUND"))
            ag_val = str(agreement.get(key, "NOT FOUND"))
            match_status = "MATCH" if key not in comparison["unmatched"] else "MISMATCH"
            writer.writerow([key, pro_val, ag_val, match_status])
    return path

def generate_pdf(proforma_data, path='matched_proforma.pdf', sign='sign.png', seal='seal.png'):
    c = canvas.Canvas(path, pagesize=A4)
    width, height = A4
    textobject = c.beginText(40, height-50)
    for k, v in proforma_data.items():
        if k != "line_items":
            textobject.textLine(f"{k}: {v}")
    c.drawText(textobject)
    if os.path.exists(sign):
        c.drawImage(sign, 50, 100, width=150, height=50, mask='auto')
    if os.path.exists(seal):
        c.drawImage(seal, 220, 100, width=100, height=100, mask='auto')
    c.showPage()
    c.save()
    return path

def send_email(to_email, subject, body, attachment_path=None):
    msg = EmailMessage()
    msg['From'] = SELLER_EMAIL
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.set_content(body)
    if attachment_path:
        with open(attachment_path, 'rb') as f:
            file_data = f.read()
            file_name = os.path.basename(attachment_path)
        msg.add_attachment(file_data, maintype='application', subtype='pdf', filename=file_name)
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(SELLER_EMAIL, SELLER_PASSWORD)
            smtp.send_message(msg)
    except Exception as e:
        print(f"Email sending failed: {str(e)}")

# ---------------- API Endpoint ----------------

@app.post("/extract-and-compare/")
async def extract_and_compare(
    proforma_file: UploadFile = File(...),
    agreement_file: UploadFile = File(...)
):
    if not proforma_file or not agreement_file:
        raise HTTPException(status_code=422, detail="Both proforma_file and agreement_file are required")

    pro_bytes = await proforma_file.read()
    ag_bytes = await agreement_file.read()

    pro_data = extract_pdf_data(pro_bytes)
    ag_data = extract_pdf_data(ag_bytes)
    comparison = compare_data(pro_data, ag_data)
    csv_path = save_to_csv(pro_data, ag_data, comparison)

    response = {
        "proforma": pro_data,
        "agreement": ag_data,
        "comparison": comparison,
        "csv_path": csv_path
    }

    if comparison["match_message"] == "Successful Match":
        pdf_path = generate_pdf(pro_data)
        response["matched_pdf"] = pdf_path
        # Email to seller
        send_email(
            to_email=SELLER_EMAIL,
            subject="Proforma Matched Successfully",
            body="Proforma matches the agreement. PDF attached.",
            attachment_path=pdf_path
        )
        # Swift message for buyer
        response["swift_message"] = BUYER_SWIFT

    return JSONResponse(response)

@app.get("/download/{file_path}")
def download_file(file_path: str):
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path)
