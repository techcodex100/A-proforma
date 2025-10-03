import os
import re
import tempfile
import csv
import json
from typing import Dict
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse, FileResponse
import pdfplumber
from PyPDF2 import PdfReader, PdfWriter

app = FastAPI(title="Proforma vs Agreement Compare API")


# ----- Normalize Function -----
def normalize(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]", "", text).lower()


# ----- PDF Text Extraction -----
def extract_text_from_pdf(file_path: str) -> str:
    text = ""
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    return text


# ----- Extract Key Fields -----
def extract_fields(text: str) -> Dict[str, str]:
    data = {
        "companyname": "notfound",
        "contractno": "notfound",
        "date": "notfound",
        "sellerbank": "notfound",
        "accountno": "notfound",
        "swift": "notfound",
        "paymentterms": "notfound",
        "netweight": "notfound",
        "grossweight": "notfound",
        "variation": "notfound",
        "amountwords": "notfound",
        "packing": "notfound",
        "loadingport": "notfound",
        "destinationport": "notfound",
        "shipment": "notfound",
        "website": "notfound",
        "email": "notfound",
        "gstin": "notfound",
        "consignee": "notfound",
        "buyer": "notfound",
        "lineitems": "notfound"
    }

    patterns = {
        "contractno": r"(Contract No[:\s]*)([A-Za-z0-9\-\/]+)",
        "date": r"(Date[:\s]*)([0-9\-]+)",
        "sellerbank": r"(Seller’s Bank[:\s]*)(.+)",
        "accountno": r"(Account No[:\s]*)(\d+)",
        "swift": r"(SWIFT[:\s]*)(\w+)",
        "paymentterms": r"(Payment Terms[:\s]*)(.+)",
        "netweight": r"(Net Weight[:\s]*)([\d\.]+)",
        "grossweight": r"(Gross Weight[:\s]*)([\d\.]+)",
        "variation": r"(Variation[:\s]*)(.+)",
        "amountwords": r"(Amount in words[:\s]*)(.+)",
        "packing": r"(Packing[:\s]*)(.+)",
        "loadingport": r"(Loading Port[:\s]*)(.+)",
        "destinationport": r"(Destination Port[:\s]*)(.+)",
        "shipment": r"(Shipment[:\s]*)(.+)",
        "website": r"(Website[:\s]*)(\S+)",
        "email": r"(Email[:\s]*)(\S+)",
        "gstin": r"(GST[:\s]*)(\S+)",
        "consignee": r"(Consignee[:\s]*)(.+)",
        "buyer": r"(Buyer[:\s]*)(.+)"
    }

    for key, pattern in patterns.items():
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            data[key] = normalize(match.group(2))

    return data


# ----- Compare Two PDFs -----
def compare_data(proforma_data: dict, agreement_data: dict) -> Dict:
    matches = {}
    for key in proforma_data.keys():
        matches[key] = 1 if proforma_data[key] == agreement_data[key] else 0
    match_message = "successful" if all(v == 1 for v in matches.values()) else "unsuccessful"
    return {"matches": matches, "match_message": match_message}


# ----- Generate CSV -----
def generate_csv(data: Dict, filename="json.csv"):
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(data.keys())
        writer.writerow(data.values())


# ----- Add Seal and Signature -----
def add_seal_signature(pdf_path: str, seal_path="seal.png", sign_path="sign.png") -> str:
    output_pdf = pdf_path.replace(".pdf", "_signed.pdf")
    reader = PdfReader(pdf_path)
    writer = PdfWriter()

    for page in reader.pages:
        writer.add_page(page)
    with open(output_pdf, "wb") as f:
        writer.write(f)

    return output_pdf


@app.post("/compare/")
async def compare(
    proforma_file: UploadFile = File(...),
    agreement_file: UploadFile = File(...)
):
    try:
        # Save temporary PDFs
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp1:
            tmp1.write(await proforma_file.read())
            proforma_path = tmp1.name
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp2:
            tmp2.write(await agreement_file.read())
            agreement_path = tmp2.name

        # Extract text
        proforma_text = extract_text_from_pdf(proforma_path)
        agreement_text = extract_text_from_pdf(agreement_path)

        # Extract data fields
        proforma_data = extract_fields(proforma_text)
        agreement_data = extract_fields(agreement_text)

        # Compare
        comparison_result = compare_data(proforma_data, agreement_data)

        # Normalize and Save CSV
        normalize_data = {k: normalize(str(v)) for k, v in {**proforma_data, **agreement_data}.items()}
        generate_csv(normalize_data)

        # Add seal and sign
        signed_pdf_path = add_seal_signature(proforma_path)

        return {
            "proforma": proforma_data,
            "agreement": agreement_data,
            "comparison": comparison_result,
            "csv_path": "json.csv",
            "signed_pdf": signed_pdf_path,
            "seal_file": "seal.png",
            "sign_file": "sign.png"
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        try:
            os.remove(proforma_path)
            os.remove(agreement_path)
        except:
            pass


@app.get("/")
async def root():
    return {"info": "Upload Proforma and Agreement PDFs at /compare/"}
