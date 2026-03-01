# check_sample.py — выборочная проверка файлов bill_pdf -> text_nokey
# Standalone: не зависит от модулей проекта
import csv
import os
import sys
import re
from unicodedata import normalize

# Принудительно UTF-8 на stdout
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CSV_PATH = r"M:\compare_289.csv"
PY_ROOT = r"M:\python_Files289"
BAS_ROOT = r"M:\bas_Files289"
SAMPLE = 10

# Инлайн ключевых слов (топ-50 самых частых для быстрой проверки)
BILL_KEYWORDS = [
    "invoice", "rechnung", "facture", "factura", "faktura", "bill",
    "statement", "account number", "billing period", "account summary",
    "total amount", "payment", "amount due", "balance", "due date",
    "invoice date", "billing", "numéro de compte", "kontonummer",
    "rechnungsnummer", "número de cuenta", "codice fiscale",
    "n° client", "customer number", "kundennummer", "policy number",
    "abrechnungszeitraum", "période de", "período de", "fakturadato",
    "számla", "рахунок", "фактура", "счёт", "счет", "оплата",
    "numer konta", "rachunek", "récapitulatif", "total ttc", "total ht",
    "montant", "betrag", "importo", "importe", "kwota", "сума",
    "votre numéro", "konto", "nº cliente",
]

MUSOR_KEYWORDS = [
    "ticket", "tiket", "online-ticket", "e-billet", "billet", "airlines",
    "booking", "medical", "produkty", "asortyment", "travel", "eticket",
    "product", "bilet", "biletu",
]


def norm(s):
    return normalize("NFC", s).casefold()


def contains_any(text, keywords):
    t = norm(text)
    for kw in keywords:
        if norm(kw) in t:
            return True, kw
    return False, None


def find_file(root, filename):
    for dirpath, _, filenames in os.walk(root):
        if filename in filenames:
            return os.path.join(dirpath, filename)
    return None


def main():
    candidates = []
    with open(CSV_PATH, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            bas = row["bas_category"]
            py = row["python_category"]
            if bas.startswith("Files289 (bill_pdf)") and py == "Files289 (text_pdf(nokey))":
                candidates.append((row["filename"], bas))

    print(f"Total bill_pdf->text_nokey: {len(candidates)}")
    sample = candidates[:SAMPLE]

    import fitz

    for i, (name, bas_cat) in enumerate(sample, 1):
        print(f"\n{'='*80}")
        print(f"[{i}/{SAMPLE}] {name}")
        print(f"  BAS category: {bas_cat}")

        path = find_file(PY_ROOT, name)
        if not path:
            path = find_file(BAS_ROOT, name)
        if not path:
            print("  FILE NOT FOUND")
            continue

        print(f"  Found at: {path}")
        size_kb = os.path.getsize(path) / 1024
        print(f"  Size: {size_kb:.1f} KB")

        try:
            doc = fitz.open(path)
            pages = len(doc)
            text = ""
            for p in range(min(pages, 5)):
                text += doc[p].get_text()
            doc.close()
        except Exception as e:
            print(f"  fitz error: {e}")
            continue

        text_stripped = text.strip()
        text_len = len(text_stripped)
        preview = text_stripped[:600].replace("\n", " | ")

        print(f"  Pages: {pages}")
        print(f"  Text length: {text_len} chars")

        has_letter = bool(re.search(r"[A-Za-z\u0400-\u04FF]", text_stripped))
        has_digit = bool(re.search(r"\d", text_stripped))
        print(f"  Has letters+digits: {has_letter and has_digit}")

        found_bill, matched_kw = contains_any(text_stripped, BILL_KEYWORDS)
        found_musor, matched_musor = contains_any(text_stripped, MUSOR_KEYWORDS)
        print(f"  Bill keyword found: {found_bill}" + (f" ('{matched_kw}')" if matched_kw else ""))
        print(f"  Musor keyword found: {found_musor}" + (f" ('{matched_musor}')" if matched_musor else ""))

        print(f"  Text preview: {preview[:400]}")

        if not has_letter or not has_digit:
            print(f"  -> VERDICT: No real text, should be img_pdf")
        elif text_len < 20:
            print(f"  -> VERDICT: Minimal text, probably garbage")
        elif found_bill:
            print(f"  -> VERDICT: Has bill keywords! Python should have caught this")
        else:
            print(f"  -> VERDICT: Text present but no keywords - text_nokey is correct")


if __name__ == "__main__":
    main()
