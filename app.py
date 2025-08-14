from flask import Flask, render_template, request, redirect, url_for, flash
import os
# .env dosyasını lokal için yükler
load_dotenv()

app = Flask(__name__)

# Railway DATABASE_URL değişkenini çekiyoruz
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv("DATABASE_URL").replace("postgres://", "postgresql://")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

app = Flask(__name__)
app.secret_key = "secret-key"

# Ana sayfa
@app.route("/")
def index():
    return render_template("index.html")

# Ürünler
@app.route("/urunler")
def urunler():
    return render_template("urunler.html")

# Satış ekranı
@app.route("/satis", methods=["GET", "POST"])
def satis():
    if request.method == "POST":
        flash("Satış başarıyla kaydedildi!", "success")
        return redirect(url_for("satis"))
    return render_template("satis.html")

# Müşteriler
@app.route("/musteriler")
def musteriler():
    return render_template("musteriler.html")
@app.route("/api/customers", methods=["POST"])
def api_customers_add():
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    phone = (data.get("phone") or "").strip()
    email = (data.get("email") or "").strip()
    if not name:
        return jsonify({"ok": False, "message": "Ad soyad gerekli."}), 400

    c = Customer(name=name, phone=phone, email=email)
    db.session.add(c)
    db.session.commit()

    return jsonify({"ok": True, "message": "Müşteri eklendi.",
                    "customer": {"id": c.id, "name": c.name, "phone": c.phone or "-",
                                 "email": c.email or "-", "debt": f"{c.debt:.2f}"}})

# Raporlar
@app.route("/raporlar")
def raporlar():
    return render_template("raporlar.html")

if __name__ == "__main__":
    app.run(debug=True)
