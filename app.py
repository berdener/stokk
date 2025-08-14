from flask import Flask, render_template, request, redirect, url_for, flash
import os

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

# Raporlar
@app.route("/raporlar")
def raporlar():
    return render_template("raporlar.html")

if __name__ == "__main__":
    app.run(debug=True)
