from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import landscape, A7
from reportlab.lib.utils import ImageReader

def label_pdf(code, name, price, barcode_png_path, pdf_path):
    c = canvas.Canvas(pdf_path, pagesize=landscape(A7))
    w, h = landscape(A7)
    y = h - 10*mm
    c.setFont("Helvetica-Bold", 12)
    c.drawString(8*mm, y, (name or '')[:22])
    y -= 7*mm
    c.setFont("Helvetica", 11)
    c.drawString(8*mm, y, f"{price:.2f} ₺")
    y -= 25*mm
    img = ImageReader(barcode_png_path)
    c.drawImage(img, 8*mm, y, width=60*mm, height=20*mm, preserveAspectRatio=True, mask='auto')
    c.setFont("Helvetica", 9)
    c.drawString(8*mm, 6*mm, code)
    c.showPage()
    c.save()
    return pdf_path
