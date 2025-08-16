import os
from datetime import datetime, timedelta
from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, send_file, jsonify, session
)
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv

# Utils
from utils.shopify_utils import fetch_products, fetch_locations, set_inventory
from utils.barcode_utils import generate_code128_png
from utils.pdf_utils import label_pdf as build_label_pdf

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "mss-secret")

# ---- DB config (Railway postgres fix) ----
DB_URL = os.getenv("DATABASE_URL", "sqlite:///data.db")
if DB_URL.startswith("postgres://"):
    DB_URL = DB_URL.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = DB_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# ===================== MODELS =====================
class Settings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    shop_url = db.Column(db.String(255))
    api_token = db.Column(db.String(255))
    location_id = db.Column(db.String(64))

class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.String(50))
    email = db.Column(db.String(200))
    debt = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    source = db.Column(db.String(32), default="manual")  # shopify/manual
    title = db.Column(db.String(255), nullable=False)
    barcode = db.Column(db.String(64), unique=True)
    price = db.Column(db.Float, default=0.0)
    stock = db.Column(db.Integer, default=0)
    shopify_variant_id = db.Column(db.String(64))
    shopify_inventory_item_id = db.Column(db.String(64))

class Sale(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'))
    qty = db.Column(db.Integer, default=1)
    unit_price = db.Column(db.Float, default=0.0)
    total_price = db.Column(db.Float, default=0.0)
    payment = db.Column(db.String(20), default="nakit")  # nakit/kart/veresiye
    is_paid = db.Column(db.Boolean, default=True)        # veresiye ise False

class CreditPayment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'))
    amount = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class ReturnExchange(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    type = db.Column(db.String(16))  # iade/degisim
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=True)
    old_product_id = db.Column(db.Integer, db.ForeignKey('product.id'))
    new_product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=True)
    qty = db.Column(db.Integer, default=1)
    note = db.Column(db.String(255))

with app.app_context():
    db.create_all()

# ===================== HELPERS =====================
def get_settings():
    s = Settings.query.first()
    if not s:
        s = Settings(
            shop_url=os.getenv("SHOP_URL"),
            api_token=os.getenv("SHOPIFY_API_TOKEN"),
            location_id=os.getenv("SHOPIFY_LOCATION_ID"),
        )
        db.session.add(s)
        db.session.commit()
    return s

def generate_internal_barcode():
    last = Product.query.filter(Product.barcode.like("MS%")).order_by(Product.id.desc()).first()
    n = 1
    if last and last.barcode and last.barcode.startswith("MS"):
        try:
            n = int(last.barcode[2:]) + 1
        except:
            n = 1
    return f"MS{n:06d}"

def adjust_shopify_stock(prod: Product):
    s = get_settings()
    if not (prod.shopify_inventory_item_id and s.shop_url and s.api_token and s.location_id):
        return
    try:
        set_inventory(s.shop_url, s.api_token, s.location_id, prod.shopify_inventory_item_id, prod.stock)
    except Exception as e:
        print("Shopify stok güncelleme hatası:", e)

# ---- Cart helpers (session) ----
def get_cart():
    return session.get("cart", [])

def save_cart(cart):
    session["cart"] = cart
    session.modified = True

def cart_totals(cart):
    total_qty = sum(int(i["qty"]) for i in cart)
    total_amount = sum(float(i["qty"]) * float(i["price"]) for i in cart)
    return {"qty": total_qty, "amount": round(total_amount, 2)}

# ===================== ROUTES =====================

# ---- Dashboard
@app.route("/")
def dashboard():
    today = datetime.utcnow().date()
    month_start = datetime(today.year, today.month, 1)

    today_sales = db.session.query(db.func.coalesce(db.func.sum(Sale.total_price), 0.0))\
        .filter(Sale.is_paid == True, db.func.date(Sale.created_at) == today).scalar()
    today_collections = db.session.query(db.func.coalesce(db.func.sum(CreditPayment.amount), 0.0))\
        .filter(db.func.date(CreditPayment.created_at) == today).scalar()

    month_sales = db.session.query(db.func.coalesce(db.func.sum(Sale.total_price), 0.0))\
        .filter(Sale.is_paid == True, Sale.created_at >= month_start).scalar()
    month_collections = db.session.query(db.func.coalesce(db.func.sum(CreditPayment.amount), 0.0))\
        .filter(CreditPayment.created_at >= month_start).scalar()

    open_credit = db.session.query(db.func.coalesce(db.func.sum(Customer.debt), 0.0)).scalar()
    low_stock = Product.query.filter(Product.stock <= 2).count()

    labels, vals = [], []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        v = db.session.query(db.func.coalesce(db.func.sum(Sale.total_price), 0.0))\
            .filter(Sale.is_paid == True, db.func.date(Sale.created_at) == d).scalar()
        c = db.session.query(db.func.coalesce(db.func.sum(CreditPayment.amount), 0.0))\
            .filter(db.func.date(CreditPayment.created_at) == d).scalar()
        labels.append(d.strftime("%d.%m"))
        vals.append(float(v) + float(c))

    pay_labels = ["nakit", "kart", "veresiye"]
    pay_values = []
    for p in pay_labels:
        if p == "veresiye":
            v = db.session.query(db.func.coalesce(db.func.sum(Sale.total_price), 0.0))\
                .filter(Sale.payment == "veresiye").scalar()
        else:
            v = db.session.query(db.func.coalesce(db.func.sum(Sale.total_price), 0.0))\
                .filter(Sale.payment == p, Sale.is_paid == True).scalar()
        pay_values.append(float(v))

    kpis = {
        "today_revenue": float(today_sales) + float(today_collections),
        "month_revenue": float(month_sales) + float(month_collections),
        "open_credit": float(open_credit),
        "low_stock": low_stock
    }
    # NOT: Jinja'da charts.daily['values'] / charts.pay['values'] diye erişeceğiz
    charts = {"daily": {"labels": labels, "values": vals},
              "pay": {"labels": pay_labels, "values": pay_values}}
    return render_template("dashboard.html", kpis=kpis, charts=charts)

# ---- Products
@app.route("/products")
def products_page():
    products = Product.query.order_by(Product.title.asc()).all()
    return render_template("products.html", products=products)

@app.route("/products/add", methods=["GET", "POST"])
def add_product_page():
    if request.method == "POST":
        title = request.form["title"].strip()
        price = float(request.form.get("price", 0))
        stock = int(request.form.get("stock", 0))
        barcode = request.form.get("barcode", "").strip() or generate_internal_barcode()
        p = Product(source="manual", title=title, price=price, stock=stock, barcode=barcode)
        db.session.add(p)
        db.session.commit()
        flash("Ürün eklendi", "success")
        return redirect(url_for("products_page"))
    return render_template("add_product.html")

@app.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
def edit_product_page(product_id):
    p = Product.query.get_or_404(product_id)
    if request.method == "POST":
        p.title = request.form["title"].strip()
        p.price = float(request.form.get("price", 0))
        p.stock = int(request.form.get("stock", 0))
        p.barcode = request.form.get("barcode", "").strip() or p.barcode
        db.session.commit()
        adjust_shopify_stock(p)
        flash("Güncellendi", "success")
        return redirect(url_for("products_page"))
    return render_template("edit_product.html", p=p)

@app.route("/products/sync")
def sync_shopify_products():
    s = get_settings()
    if not (s.shop_url and s.api_token):
        flash("Önce Ayarlar'dan Shopify bilgilerini girin.", "danger")
        return redirect(url_for("products_page"))
    try:
        data = fetch_products(s.shop_url, s.api_token)
        count = 0
        for prod in data:
            for v in prod.get("variants", []):
                title = f"{prod.get('title')}"
                price = float(v.get("price") or 0.0)
                stock = int(v.get("inventory_quantity") or 0)
                barcode = v.get("barcode") or None
                inv_item = v.get("inventory_item_id")
                variant_id = v.get("id")

                existing = None
                if barcode:
                    existing = Product.query.filter_by(barcode=barcode).first()
                if not existing and variant_id:
                    existing = Product.query.filter_by(shopify_variant_id=str(variant_id)).first()

                if existing:
                    existing.title = title
                    existing.price = price
                    existing.stock = stock
                    existing.shopify_variant_id = str(variant_id)
                    existing.shopify_inventory_item_id = str(inv_item)
                    existing.source = "shopify"
                else:
                    db.session.add(Product(
                        source="shopify", title=title, price=price, stock=stock,
                        barcode=barcode, shopify_variant_id=str(variant_id),
                        shopify_inventory_item_id=str(inv_item)))
                count += 1
        db.session.commit()
        flash(f"Shopify'dan {count} varyant senkronize edildi.", "success")
    except Exception as e:
        flash(f"Senkron hata: {e}", "danger")
    return redirect(url_for("products_page"))

@app.route("/label/<int:product_id>")
def product_label_pdf(product_id):
    p = Product.query.get_or_404(product_id)
    code = p.barcode or generate_internal_barcode()
    png_path = f"barcodes/{code}.png"
    pdf_path = f"labels/{code}.pdf"
    generate_code128_png(code, png_path)
    path = build_label_pdf(code, p.title, p.price or 0.0, png_path, pdf_path)
    return send_file(path, as_attachment=True)

@app.route("/label_by_code/<code>")
def label_by_code(code):
    p = Product.query.filter_by(barcode=code).first()
    if not p:
        return "Ürün bulunamadı", 404
    png_path = f"barcodes/{code}.png"
    pdf_path = f"labels/{code}.pdf"
    generate_code128_png(code, png_path)
    path = build_label_pdf(code, p.title, p.price or 0.0, png_path, pdf_path)
    return send_file(path, as_attachment=True)

# ---- Sales (AJAX Sepet)
@app.route("/sales", methods=["GET"])
def sales_page():
    customers = Customer.query.order_by(Customer.name.asc()).all()
    return render_template("sales.html",
                           customers=customers,
                           cart=get_cart(),
                           totals=cart_totals(get_cart()))

@app.post("/api/cart/add")
def api_cart_add():
    data = request.get_json(force=True)
    barcode = (data.get("barcode") or "").strip()
    qty = int(data.get("qty") or 1)

    prod = Product.query.filter_by(barcode=barcode).first()
    if not prod:
        return jsonify({"ok": False, "message": "Barkod bulunamadı"}), 404
    if qty < 1:
        qty = 1

    cart = get_cart()
    for item in cart:
        if item["product_id"] == prod.id:
            item["qty"] += qty
            save_cart(cart)
            return jsonify({"ok": True, "cart": cart, "totals": cart_totals(cart)})

    cart.append({
        "product_id": prod.id,
        "title": prod.title,
        "barcode": prod.barcode,
        "price": float(prod.price or 0),
        "qty": qty
    })
    save_cart(cart)
    return jsonify({"ok": True, "cart": cart, "totals": cart_totals(cart)})

@app.post("/api/cart/update")
def api_cart_update():
    data = request.get_json(force=True)
    pid = int(data.get("product_id"))
    qty = int(data.get("qty"))

    cart = get_cart()
    for item in cart:
        if item["product_id"] == pid:
            if qty <= 0:
                cart = [i for i in cart if i["product_id"] != pid]
            else:
                item["qty"] = qty
            save_cart(cart)
            return jsonify({"ok": True, "cart": cart, "totals": cart_totals(cart)})
    return jsonify({"ok": False, "message": "Ürün sepette yok"}), 404

@app.post("/api/cart/remove")
def api_cart_remove():
    data = request.get_json(force=True)
    pid = int(data.get("product_id"))
    cart = [i for i in get_cart() if i["product_id"] != pid]
    save_cart(cart)
    return jsonify({"ok": True, "cart": cart, "totals": cart_totals(cart)})

@app.post("/api/cart/clear")
def api_cart_clear():
    save_cart([])
    return jsonify({"ok": True, "cart": [], "totals": {"qty": 0, "amount": 0}})

@app.post("/api/cart/checkout")
def api_cart_checkout():
    data = request.get_json(force=True)
    payment = (data.get("payment") or "nakit").strip()   # nakit/kart/veresiye
    cust_id = data.get("customer_id")
    customer = Customer.query.get(cust_id) if cust_id else None

    disc_type = (data.get("discount_type") or "none").strip()   # none/percent/amount
    try:
        disc_value = float(data.get("discount_value") or 0)
    except:
        disc_value = 0.0

    cart = get_cart()
    if not cart:
        return jsonify({"ok": False, "message": "Sepet boş"}), 400

    # 1) Ara toplam
    subtotal = sum(float(i["price"]) * int(i["qty"]) for i in cart)

    # 2) İndirim
    discount = 0.0
    if disc_type == "percent":
        p = min(max(disc_value, 0), 100)      # 0–100 arası
        discount = subtotal * (p / 100.0)
    elif disc_type == "amount":
        discount = min(max(disc_value, 0.0), subtotal)

    grand_total = round(subtotal - discount, 2)
    factor = (grand_total / subtotal) if subtotal > 0 else 1.0  # Ürünlere oransal dağıt

    # 3) Satış kalemlerini kaydet + stok düş
    for item in cart:
        prod = Product.query.get(item["product_id"])
        if not prod:
            return jsonify({"ok": False, "message": f"Ürün bulunamadı: {item.get('title')}"}), 400

        qty = int(item["qty"])
        unit_price = float(item["price"])
        line_total = round(unit_price * qty * factor, 2)  # indirim dağıtılmış tutar

        sale = Sale(customer_id=customer.id if customer else None,
                    product_id=prod.id,
                    qty=qty,
                    unit_price=unit_price,         # etiket fiyatı
                    total_price=line_total,        # indirimli satır toplamı
                    payment=payment,
                    is_paid=(payment != "veresiye"))
        db.session.add(sale)

        prod.stock = (prod.stock or 0) - qty
        db.session.flush()
        try:
            adjust_shopify_stock(prod)
        except Exception as e:
            print("Shopify sync error:", e)

    # 4) Veresiye borcu
    if payment == "veresiye" and customer:
        customer.debt = (customer.debt or 0.0) + grand_total

    db.session.commit()
    save_cart([])

    return jsonify({
        "ok": True,
        "message": "Satış tamamlandı",
        "subtotal": round(subtotal, 2),
        "discount": round(discount, 2),
        "total": round(grand_total, 2)
    })

# ---- Customers
@app.route("/customers")
def customers_page():
    customers = Customer.query.order_by(Customer.name.asc()).all()
    return render_template("customers.html", customers=customers)

@app.route("/customers/add", methods=["GET", "POST"])
def add_customer_page():
    if request.method == "POST":
        c = Customer(
            name=request.form["name"].strip(),
            phone=request.form.get("phone", "").strip(),
            email=request.form.get("email", "").strip()
        )
        db.session.add(c)
        db.session.commit()
        flash("Müşteri eklendi", "success")
        return redirect(url_for("customers_page"))
    return render_template("add_customer.html")

appings().all()
@app.route("/customers/<int:customer_id>")
def customer_detail(customer_id):
    c = Customer.query.get_or_404(customer_id)
    year_ago = datetime.utcnow() - timedelta(days=365)

    rows = db.session.execute(db.text("""
        SELECT s.created_at as date, p.title as product_name, s.qty as qty,
               s.total_price as total, s.payment as payment
        FROM sale s
        JOIN product p ON p.id = s.product_id
        WHERE s.customer_id = :cid AND s.created_at >= :d
        ORDER BY s.created_at DESC
    """), {"cid": c.id, "d": year_ago}).mappings().all()

    # datetime/string uyumlusu
    sales = []
    for r in rows:
        d = r["date"]
        if hasattr(d, "strftime"):
            d_str = d.strftime("%Y-%m-%d %H:%M")
        else:
            d_str = str(d)  # ISO string ise direkt
        sales.append({
            "date_str": d_str,
            "product_name": r["product_name"],
            "qty": r["qty"],
            "total": r["total"],
            "payment": r["payment"],
        })

    return render_template("customer_detail.html", c=c, sales=sales)

@app.route("/customers/<int:customer_id>/collect", methods=["POST"])
def collect_credit(customer_id):
    c = Customer.query.get_or_404(customer_id)
    amount = float(request.form.get("amount", 0))
    if amount <= 0:
        flash("Geçersiz tutar", "danger")
        return redirect(url_for("customer_detail", customer_id=c.id))
    if (c.debt or 0.0) < amount:
        amount = c.debt or 0.0
    c.debt = (c.debt or 0.0) - amount
    db.session.add(CreditPayment(customer_id=c.id, amount=amount))
    db.session.commit()
    flash("Tahsilat kaydedildi (ciroya eklendi)", "success")
    return redirect(url_for("customer_detail", customer_id=c.id))

# ---- Returns / Exchanges
@app.route("/returns", methods=["GET", "POST"])
def returns_page():
    if request.method == "POST":
        rtype = request.form.get("rtype", "iade")
        old_barcode = request.form.get("old_barcode", "").strip()
        qty = int(request.form.get("qty", 1))
        new_barcode = request.form.get("new_barcode", "").strip() or None

        old_p = Product.query.filter_by(barcode=old_barcode).first()
        if not old_p:
            flash("Eski ürün barkodu bulunamadı", "danger")
            return redirect(url_for("returns_page"))

        # stok iade
        old_p.stock = (old_p.stock or 0) + qty
        adjust_shopify_stock(old_p)

        new_p = None
        if rtype == "degisim":
            if not new_barcode:
                flash("Değişim için yeni ürün barkodu gerekli", "danger")
                return redirect(url_for("returns_page"))
            new_p = Product.query.filter_by(barcode=new_barcode).first()
            if not new_p:
                flash("Yeni ürün barkodu bulunamadı", "danger")
                return redirect(url_for("returns_page"))
            new_p.stock = (new_p.stock or 0) - qty
            adjust_shopify_stock(new_p)

        re = ReturnExchange(type=rtype, old_product_id=old_p.id,
                            new_product_id=new_p.id if new_p else None, qty=qty)
        db.session.add(re)
        db.session.commit()
        flash("İşlem kaydedildi", "success")
        return redirect(url_for("returns_page"))
    return render_template("returns.html")

# ---- Reports
@app.route("/reports")
def reports_page():
    today = datetime.utcnow().date()
    month_start = datetime(today.year, today.month, 1)

    today_total_sales = db.session.query(db.func.coalesce(db.func.sum(Sale.total_price), 0))\
        .filter(Sale.is_paid == True, db.func.date(Sale.created_at) == today).scalar()
    today_collections = db.session.query(db.func.coalesce(db.func.sum(CreditPayment.amount), 0))\
        .filter(db.func.date(CreditPayment.created_at) == today).scalar()
    month_total_sales = db.session.query(db.func.coalesce(db.func.sum(Sale.total_price), 0))\
        .filter(Sale.is_paid == True, Sale.created_at >= month_start).scalar()
    month_collections = db.session.query(db.func.coalesce(db.func.sum(CreditPayment.amount), 0))\
        .filter(CreditPayment.created_at >= month_start).scalar()

    kpis = {"today": float(today_total_sales) + float(today_collections),
            "month": float(month_total_sales) + float(month_collections),
            "collections": float(month_collections)}

    labels, values = [], []
    d = month_start
    while d.month == month_start.month:
        day_sales = db.session.query(db.func.coalesce(db.func.sum(Sale.total_price), 0))\
            .filter(Sale.is_paid == True, db.func.date(Sale.created_at) == d.date()).scalar()
        day_col = db.session.query(db.func.coalesce(db.func.sum(CreditPayment.amount), 0))\
            .filter(db.func.date(CreditPayment.created_at) == d.date()).scalar()
        labels.append(d.strftime("%d.%m"))
        values.append(float(day_sales) + float(day_col))
        d += timedelta(days=1)

    pay_labels = ["nakit", "kart", "veresiye"]
    pay_values = []
    for p in pay_labels:
        if p == "veresiye":
            v = db.session.query(db.func.coalesce(db.func.sum(Sale.total_price), 0))\
                .filter(Sale.payment == "veresiye").scalar()
        else:
            v = db.session.query(db.func.coalesce(db.func.sum(Sale.total_price), 0))\
                .filter(Sale.payment == p, Sale.is_paid == True).scalar()
        pay_values.append(float(v))

    charts = {"month": {"labels": labels, "values": values},
              "pay": {"labels": pay_labels, "values": pay_values}}
    return render_template("reports.html", kpis=kpis, charts=charts)

# ---- Credit list
@app.route("/credit")
def credit_page():
    customers = Customer.query.order_by(Customer.name.asc()).all()
    return render_template("credit.html", customers=customers)

# ---- Settings
@app.route("/settings", methods=["GET", "POST"])
def settings_page():
    s = get_settings()
    locations = None
    if request.method == "POST":
        s.shop_url = request.form["shop_url"].strip()
        s.api_token = request.form["api_token"].strip()
        s.location_id = request.form["location_id"].strip()
        db.session.commit()
        flash("Ayarlar kaydedildi", "success")
        return redirect(url_for("settings_page"))
    return render_template("settings.html", settings=s, locations=locations)

@app.route("/settings/locations")
def get_locations():
    s = get_settings()
    try:
        locs = fetch_locations(s.shop_url, s.api_token)
    except Exception as e:
        flash(f"Lokasyon hatası: {e}", "danger")
        return redirect(url_for("settings_page"))
    return render_template("settings.html", settings=s, locations=locs)

# ---- App entry
if __name__ == "__main__":
    # Railway dinamik PORT verir
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
