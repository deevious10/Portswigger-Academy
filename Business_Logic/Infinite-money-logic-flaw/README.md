# PortSwigger — Infinite Money Logic Flaw

Script de automatización para el laboratorio **"Infinite money logic flaw"** de PortSwigger Web Security Academy. Explota una falla en la lógica de negocio que permite generar crédito en tienda de forma indefinida combinando tarjetas de regalo con un cupón de descuento.

---

## Descripción de la vulnerabilidad

La tienda permite:

1. Comprar tarjetas de regalo a **$10.00** c/u.
2. Aplicar el cupón **SIGNUP30** que otorga un **30% de descuento** sobre el total.
3. Canjear las tarjetas obtenidas para recuperar **$10.00** por cada una.

Al aplicar el descuento, cada tarjeta cuesta efectivamente **$7.00**, pero al canjearla se recuperan **$10.00**, generando una **ganancia neta de $3.00 por tarjeta** en cada ciclo.

```
Costo con descuento : $7.00 por tarjeta
Valor de canje      : $10.00 por tarjeta
Ganancia neta       : +$3.00 por tarjeta
```

---

## Flujo del script

```
┌─────────────────────────────────────────────┐
│  1. Consultar saldo disponible (Store credit)│
│  2. Calcular n tarjetas: floor(saldo / 7.00) │
│  3. POST /cart          → agregar tarjetas   │
│  4. POST /cart/coupon   → aplicar SIGNUP30   │
│  5. POST /cart/checkout → realizar compra    │
│  6. GET  /cart/order-confirmation → códigos  │
│  7. POST /gift-card     → canjear cada código│
│  8. Verificar nuevo saldo                    │
│  9. Repetir hasta alcanzar $1,000,000        │
└─────────────────────────────────────────────┘
```

> **Nota:** El POST a `/cart/checkout` responde con un `303 See Other`. El script captura esta redirección manualmente y realiza el GET a `/cart/order-confirmation?order-confirmed=true` para extraer los códigos de las tarjetas.

---

## Concurrencia

El script utiliza `ThreadPoolExecutor` 

| Fase   | Variable           | Default | Descripción                                                                        |
| ------ | ------------------ | ------- | ---------------------------------------------------------------------------------- |
| Canje  | `REDEEM_THREADS`   | `10`    | Hilos para canjear tarjetas. Cada código es una petición independiente.            |


```
Iteración N
│
├── [Fase compra — PURCHASE_THREADS hilos en paralelo]
│   |──carrito → cupón → checkout → códigos[]
│
└── [Fase canje — REDEEM_THREADS hilos en paralelo]
    ├── Hilo 1: /gift-card (código_1)
    ├── Hilo 2: /gift-card (código_2)
    └── ... (todos los códigos recolectados)
```

---

## Requisitos

- Python 3.8+
- `requests`

```bash
pip install requests
```

---

## Configuración

Editar las constantes al inicio del script antes de ejecutar:

```python
HOST           = "0af6003c033389b88094531200ba0076.web-security-academy.net"  # Host del laboratorio
SESSION_COOKIE = "kuH4k5T1h8EdJnB2Hy0Bc2stge5aHiMl"                          # Cookie de sesión activa

REDEEM_THREADS   = 10   # Hilos para canje de tarjetas (recomendado: 10-30)
TARGET_CREDIT    = 1_000_000.0  # Saldo objetivo en dólares
```

> **Importante:** El `HOST` y `SESSION_COOKIE` cambian con cada instancia del laboratorio en PortSwigger. Actualízalos antes de cada ejecución.


---

## Uso

```bash
python portswigger_gift_card.py
```

### Salida esperada

```
============================================================
  Iteración #1  |  Store credit: $100.00
============================================================
  Tarjetas totales  : 14  (repartidas en 3 hilo(s): [5, 5, 4])
  Costo estimado    : $98.00

[*] Fase compra — 3 hilo(s) en paralelo...
  [T1] Comprando 5 tarjeta(s)...
  [T1] ✓ 5 código(s) extraído(s)

[*] Total códigos a canjear: 14
[*] Fase canje — 10 hilo(s) en paralelo...
    [✓][T01] 2kKzAMRDfi  →  HTTP 200
    [✓][T02] b8vICUOGvG  →  HTTP 200
    ...

  Saldo anterior : $100.00
  Saldo actual   : $142.00
  Ganancia neta  : +$42.00
```

---

## Advertencias

- Este script es exclusivamente para uso en entornos controlados de práctica como **PortSwigger Web Security Academy**.
- No utilizar contra aplicaciones reales o sin autorización explícita del propietario.
- Aumentar `PURCHASE_THREADS` por encima de `1` puede generar errores en la compra de tarjetas por el uso de una misma cookie para interactuar con el carrito, ademas de que no se puede contar con el saldo suficiente para realizar todas las compras.

---

## Referencia

- Laboratorio: [Infinite money logic flaw — PortSwigger](https://portswigger.net/web-security/logic-flaws/examples/lab-logic-flaws-infinite-money)
- Categoría: Business Logic Vulnerabilities
