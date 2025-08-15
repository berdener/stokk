from barcode import Code128
from barcode.writer import ImageWriter
import os

def ensure_dir(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)

def generate_code128_png(code, out_path):
    ensure_dir(out_path)
    with open(out_path, 'wb') as f:
        Code128(code, writer=ImageWriter()).write(f)
    return out_path
