import os
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import landscape, A7
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

def ensure_dir(path):
    d = os.path.dirname(path)
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)

# Türkçe karakterleri PDF'in varsayılan fontlarına uygun hâle çevir
def tr_safe(text: str) -> str:
    if not text:
        return ""
    table = str.maketrans("İıŞşĞğÖöÜüÇç", "IiSsGgOoUuCc")
    txt = text.translate(table)
    # Latin-1'e sığmayanları at (ör. emoji vs.)
    try:
        txt.encode("latin-1")
    except UnicodeEncodeError:
        txt = txt.encode("ascii", "ignore").decode("ascii")
    return txt

# İstersen Unicode font kullan (DejaVuSans.ttf koyarsan otomatik seçer)
def pick_font():
    here = os.path.dirname(__file__)
    ttf = os.path.join(here, "DejaVuSans.ttf")  # dosyayı koyarsan devreye girer
    if os.path.exists(ttf):
        try:
            pdfmetrics.registerFont(TTFont("DejaVu", ttf))
            return "DejaVu"
        except Exception:
            pass
    return "Helvetica"  # fallback

def label_pdf(code, name, price, barcode_png_path, pdf_path):
    ensure_dir(barcode_png_path)
    ensure_dir(pdf_path)

    # Yazı tipi
    font = pick_font()

    # Canvas
    c = canvas.Canvas(pdf_path, pagesize=landscape(A7))
    w, h = landscape(A7)

    # Ürün adı (Türkçe karakterleri güvenli yaz)
    safe_name = name if font == "DejaVu" else tr_safe(name)
    y = h - 10*mm
    c.setFont(f"{font}-Bold" if font != "Helvetica" else "Helvetica-Bold", 12)
    c.drawString(8*mm, y, (safe_name or '')[:40])  # A7'de biraz daha geniş bıraktık

    # Fiyat
    y -= 7*mm
    c.setFont(font if font != "Helvetica" else "Helvetica", 11)
    c.drawString(8*mm, y, f"{(price or 0):.2f} ₺")

    # Barkod görseli
    y -= 25*mm
    img = ImageReader(barcode_png_path)
    c.drawImage(img, 8*mm, y, width=60*mm, height=20*mm, preserveAspectRatio=True, mask='auto')

    # Barkod yazısı
    c.setFont(font if font != "Helvetica" else "Helvetica", 9)
    c.drawString(8*mm, 6*mm, code)

    c.showPage()
    c.save()
    return pdf_path
