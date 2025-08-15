import requests

def _headers(token):
    return {"X-Shopify-Access-Token": token, "Content-Type":"application/json"}

def fetch_locations(shop, token):
    url = f"https://{shop}/admin/api/2024-04/locations.json"
    r = requests.get(url, headers=_headers(token), timeout=30)
    r.raise_for_status()
    return r.json().get("locations", [])

def fetch_products(shop, token, limit=100):
    url = f"https://{shop}/admin/api/2024-04/products.json?limit={limit}"
    r = requests.get(url, headers=_headers(token), timeout=60)
    r.raise_for_status()
    return r.json().get("products", [])

def set_inventory(shop, token, location_id, inventory_item_id, new_qty):
    url = f"https://{shop}/admin/api/2024-04/inventory_levels/set.json"
    payload = {"location_id": int(location_id), "inventory_item_id": int(inventory_item_id), "available": int(new_qty)}
    r = requests.post(url, headers=_headers(token), json=payload, timeout=30)
    r.raise_for_status()
    return r.json()
