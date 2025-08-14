from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "mss-secret")

# SQLite (lokal) — Railway’de istersen DATABASE_URL env ile Postgres de kullanabilirsin
DB_URL = os.getenv("DATABASE_URL", "sqlite:///data.db")
# Railway'in eski "postgres://" şemasını düzelt
if DB_URL.startswith("postgres://"):
    DB_URL = DB_URL.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = DB_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# ---------------- MODELLER ----------------
class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(180), nullable=False)
    phone = db.Column(db.String(60))
    email = db.Column(db.String(180))
    debt = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# İstersen ileride Product/Sale vb. modelleri de ekleyebilirsin

with app.app_context():
    db.create_all()

# ---------------- SAYFALAR ----------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/urunler")
def urunler():
    return render_template("urunler.html")

@app.route("/satis", methods=["GET", "POST"])
def satis():
    if request.method == "POST":
        flash("Satış kaydedildi (örnek).", "success")
        return redirect(url_for("satis"))
    return render_template("satis.html")

@app.route("/raporlar")
def raporlar():
    return render_template("raporlar.html")

@app.route("/musteriler")
def musteriler():
    customers = Customer.query.order_by(Customer.created_at.desc()).all()
    return render_template("musteriler.html", customers=customers)

# ---------------- AJAX API: Müşteri Ekle ----------------
@app.route("/api/customers", methods=["POST"])
def api_customers_add():
    data = request.get_json(force=True)  # {"name": "...", "phone": "...", "email": "..."}
    name = (data.get("name") or "").strip()
    phone = (data.get("phone") or "").strip()
    email = (data.get("email") or "").strip()

    if not name:
        return jsonify({"ok": False, "message": "Ad soyad gerekli."}), 400

    c = Customer(name=name, phone=phone, email=email)
    db.session.add(c)
    db.session.commit()

    return jsonify({
        "ok": True,
        "message": "Müşteri eklendi.",
        "customer": {"id": c.id, "name": c.name, "phone": c.phone or "-", "email": c.email or "-", "debt": f"{c.debt:.2f}"}
    })

# ---------------- MAIN ----------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
