#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Transaction Collector
"""

import logging
import argparse
import datetime as dt
import decimal
import hashlib
import json
import ssl
import struct
import sys
import time
import csv
import random
import urllib.request, urllib.error
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

def setup_logging(debug: bool = False, log_file: Optional[str] = None) -> None:
    """Konfiguriert das Logging: Konsole + optional eine Ausgabedatei."""

    level = logging.DEBUG if debug else logging.INFO
    fmt = "%(asctime)s [%(levelname)s] %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    handlers: List[logging.Handler] = [logging.StreamHandler(sys.stdout)]

    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(level=level, format=fmt, datefmt=datefmt, handlers=handlers)

# Optionaler certifi-Truststore (falls System-CA fehlt)
try:
    import certifi  # type: ignore
    DEFAULT_CAFILE = certifi.where()
except ImportError:
    DEFAULT_CAFILE = None

# ---------- Einstellungen ----------
MEMPOOL_TX_URL = "https://mempool.space/tx/{}"
MEMPOOL_ADDR_URL = "https://mempool.space/address/{}"  # für address_explorer_url

# Große Limits gegen LimitOverrunError
READ_CHUNK_BYTES = 4 * 1024 * 1024     # 4 MiB pro Chunk
MAX_MESSAGE_BYTES = 64 * 1024 * 1024   # 64 MiB pro Message

D = decimal.Decimal
_DECIMAL_CTX = decimal.Context(prec=16)

# ---------- Hilfsfunktionen: Base58 & Bech32 ----------
alphabet_b58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

def b58decode_check(s: str) -> bytes:
    """Dekodiert einen Base58Check-kodierten String und verifiziert die Prüfsumme.
    Gibt die dekodierten Rohbytes (ohne Prüfsumme) zurück."""

    num = 0
    for ch in s:
        num *= 58
        if ch not in alphabet_b58:
            raise ValueError("Ungültiges Base58-Zeichen")
        num += alphabet_b58.index(ch)
    full = num.to_bytes(25, "big")
    data, checksum = full[:-4], full[-4:]
    if hashlib.sha256(hashlib.sha256(data).digest()).digest()[0:4] != checksum:
        raise ValueError("Base58Check Prüfsumme ungültig")
    return data

BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_BECH32_GEN = (0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3)

def bech32_polymod(values):
    """Berechnet den Bech32-Polynom-Prüfwert (Checksum) über eine Wertesequenz."""

    chk = 1
    for v in values:
        b = (chk >> 25) & 0xff
        chk = (chk & 0x1ffffff) << 5 ^ v
        for i in range(5):
            chk ^= _BECH32_GEN[i] if ((b >> i) & 1) else 0
    return chk

def bech32_hrp_expand(hrp):
    """Expandiert den Human-Readable-Part (HRP) für die Bech32-Prüfsummenberechnung."""
    return [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]

def bech32_verify_checksum(hrp, data):
    """Prüft, ob die Bech32-Prüfsumme für den gegebenen HRP und die Daten gültig ist."""
    return bech32_polymod(bech32_hrp_expand(hrp) + data) == 1

def bech32_decode(addr: str) -> Tuple[str, List[int]]:
    """Dekodiert eine Bech32-Adresse und gibt HRP und Datenbytes zurück.
    Wirft einen ValueError bei ungültiger Adresse oder Prüfsumme."""
    addr = addr.strip()
    if addr.lower() != addr and addr.upper() != addr:
        raise ValueError("Bech32 gemischte Groß-/Kleinschreibung")
    addr = addr.lower()
    pos = addr.rfind('1')
    if pos < 1:
        raise ValueError("Bech32: '1' Trenner fehlt")
    hrp = addr[:pos]
    data = addr[pos+1:]
    decoded = [BECH32_CHARSET.find(c) for c in data]
    if any(x == -1 for x in decoded):
        raise ValueError("Bech32: ungültiges Zeichen")
    if not bech32_verify_checksum(hrp, decoded):
        raise ValueError("Bech32: Prüfsumme ungültig")
    return hrp, decoded[:-6]

def convertbits(data, frombits, tobits, pad=True):
    """Konvertiert eine Byte-Sequenz zwischen verschiedenen Bit-Gruppierungen
    (z. B. von 5-Bit- auf 8-Bit-Gruppen für Bech32-Witness-Programme)."""
    acc = 0
    bits = 0
    ret = []
    maxv = (1 << tobits) - 1
    for value in data:
        if value < 0 or (value >> frombits):
            return None
        acc = (acc << frombits) | value
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            ret.append((acc >> bits) & maxv)
    if pad:
        if bits:
            ret.append((acc << (tobits - bits)) & maxv)
    elif bits >= frombits or ((acc << (tobits - bits)) & maxv):
        return None
    return ret

def address_to_scriptpubkey(addr: str) -> bytes:
    """Wandelt eine Bitcoin-Adresse (P2PKH, P2SH oder Bech32) in das
    zugehörige scriptPubKey-Byte-Array um."""
    # P2PKH / P2SH
    if addr.startswith(("1", "m", "n")):  # P2PKH
        payload = b58decode_check(addr)
        if payload[0] not in (0x00, 0x6f):  # Mainnet=0x00, Testnet=0x6f
            raise ValueError(f"Unerwartetes P2PKH-Versionsbyte: {payload[0]:#04x}")
        h160 = payload[1:21]  # Byte 0 = version, Bytes 1-20 = hash160
        return bytes([0x76, 0xa9, 0x14]) + h160 + bytes([0x88, 0xac])
    if addr.startswith(("3", "2")):  # P2SH
        payload = b58decode_check(addr)
        if payload[0] not in (0x05, 0xc4):  # Mainnet=0x05, Testnet=0xc4
            raise ValueError(f"Unerwartetes P2SH-Versionsbyte: {payload[0]:#04x}")
        h160 = payload[1:21]
        return bytes([0xa9, 0x14]) + h160 + bytes([0x87])

    # Bech32 (bc/tb/bcrt)
    hrp, data = bech32_decode(addr)
    if hrp not in ("bc", "tb", "bcrt"):
        raise ValueError("Unbekannte HRP")
    if len(data) < 1:
        raise ValueError("Bech32 zu kurz")
    witver = data[0]
    bits = convertbits(data[1:], 5, 8, False)
    if bits is None:
        raise ValueError("Ungültige Bech32-Witness-Daten")
    prog = bytes(bits)
    if witver == 0 and len(prog) not in (20, 32):
        raise ValueError("Ungültige v0-Programmlänge")
    op = bytes([0x00]) if witver == 0 else bytes([0x50 + witver])
    return op + bytes([len(prog)]) + prog

def scripthash_from_address(addr: str) -> str:
    """Berechnet den Electrum-kompatiblen Script-Hash (SHA256, little-endian)
    einer Bitcoin-Adresse als Hex-String."""
    spk = address_to_scriptpubkey(addr)
    return hashlib.sha256(spk).digest()[::-1].hex()  # little-endian hex

def truncate_middle(s: str, left: int = 8, right: int = 8) -> str:
    """Kürzt einen langen String in der Mitte mit '...' für lesbare Log-Ausgaben."""
    if not s or len(s) <= left + right + 3:
        return s
    return f"{s[:left]}...{s[-right:]}"

def sats_to_btc(sats: Optional[int]) -> D:
    """Rechnet einen Satoshi-Betrag in BTC (Decimal mit 8 Nachkommastellen) um."""
    if sats is None:
        return D("0")
    with decimal.localcontext(_DECIMAL_CTX):
        return (D(int(sats)) / D(100_000_000)).quantize(D("0.00000001"))

def btc_fmt(val: Any, decimal_sep: str = ",") -> str:
    """Formatiert einen BTC-Wert auf 8 Nachkommastellen mit wählbarem Dezimaltrennzeichen."""
    if val is None or val == "":
        return ""
    return f"{D(val):.8f}".replace(".", decimal_sep)

def unix_to_iso_utc(ts: Optional[int]) -> str:
    """Wandelt einen Unix-Timestamp in einen ISO-8601-UTC-String um (z. B. für CSV-Felder)."""
    if not ts:
        return ""
    return dt.datetime.fromtimestamp(int(ts), tz=dt.timezone.utc).isoformat()

# MEZ/MESZ Excel-Format (Europe/Berlin)
try:
    from zoneinfo import ZoneInfo  # ab Python 3.9
except Exception:
    ZoneInfo = None  # Fallback, falls nicht verfügbar

def unix_to_mez_excel(ts: Optional[int]) -> str:
    """Wandelt einen Unix-Timestamp in einen Datums-/Zeitstring in MEZ/MESZ
    (Europe/Berlin) im Excel-lesbaren Format um."""
    if not ts:
        return ""
    if ZoneInfo is None:
        return dt.datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M:%S")
    dt_utc = dt.datetime.fromtimestamp(int(ts), tz=dt.timezone.utc)
    dt_berlin = dt_utc.astimezone(ZoneInfo("Europe/Berlin"))
    return dt_berlin.strftime("%Y-%m-%d %H:%M:%S")

class ElectrumXConnectionError(Exception):
    pass

class ElectrumXRPCError(Exception):
    pass

class ElectrumXError(Exception):
    pass

def _backoff_delay(attempt: int, base: float = 0.5, max_wait: float = 30.0) -> float:
    """Berechnet die Wartezeit mit Exponential Backoff + Jitter.

    Beispiel bei base=0.5:
      attempt 0 → 0.5s  ± Jitter
      attempt 1 → 1.0s  ± Jitter
      attempt 2 → 2.0s  ± Jitter
      attempt 3 → 4.0s  ± Jitter  (gedeckelt auf max_wait)
    """
    exp_wait = base * (2 ** attempt)
    jitter = random.uniform(0, exp_wait * 0.2)   # ±20% Streuung
    return min(exp_wait + jitter, max_wait)

# ---------- Mempool.space (Esplora) REST Client ----------
class MempoolClient:
    """
    Minimaler HTTP-Client für mempool.space (Esplora REST API) mit certifi-Truststore.
    """
    def __init__(self, base_url: str = "https://mempool.space/api", timeout: float = 20.0, retries: int = 1, cafile: Optional[str] = None, insecure: bool = False):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = max(0, int(retries))
        self._last_request_time: float = 0.0   # für Rate-Limiting
        self.min_request_interval: float = 0.25  # min. Pause zwischen Anfragen (Sek.)
        # SSL-Kontext: bevorzugt explizites cafile, ansonsten certifi, ansonsten System-Store
        ca = cafile or DEFAULT_CAFILE
        self._ctx = ssl.create_default_context(cafile=ca) if ca else ssl.create_default_context()
        if insecure:
            self._ctx.check_hostname = False
            self._ctx.verify_mode = ssl.CERT_NONE

    def tx_status(self, txid: str) -> dict:
        return self._get_json(f"/tx/{txid}/status") or {}

    def _get_json(self, path: str) -> Any:
        url = f"{self.base_url}{path}"
        req = urllib.request.Request(url, headers={"User-Agent": "btc_mittelherkunft/1.0"})
        last_err = None
        for attempt in range(self.retries + 1):
            # Rate-Limiting: Mindestpause zwischen Anfragen einhalten
            elapsed = time.monotonic() - self._last_request_time
            if elapsed < self.min_request_interval:
                time.sleep(self.min_request_interval - elapsed)
            try:
                self._last_request_time = time.monotonic()
                with urllib.request.urlopen(req, timeout=self.timeout, context=self._ctx) as resp:
                    data = resp.read()
                    if not data:
                        return None
                    text = data.decode("utf-8", errors="replace")
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError:
                        # einige Endpunkte liefern Text (z. B. block-hash oder header)
                        return text
            except urllib.error.HTTPError as e:
                last_err = e
                if attempt < self.retries:
                    if e.code == 429:
                        # Rate-Limit: Retry-After-Header respektieren
                        wait = int(e.headers.get("Retry-After", 10))
                    else:
                        wait = _backoff_delay(attempt)
                    logger.warning(f"HTTP {e.code} bei {url} – Versuch {attempt + 1}/{self.retries + 1}, warte {wait:.1f}s")
                    time.sleep(wait)
            except (urllib.error.URLError, TimeoutError) as e:
                last_err = e
                if attempt < self.retries:
                    wait = _backoff_delay(attempt)
                    logger.warning(f"Verbindungsfehler bei {url} – Versuch {attempt + 1}/{self.retries + 1}, warte {wait:.1f}s: {e}")
                    time.sleep(wait)
        raise ElectrumXConnectionError(f"HTTP-Fehler bei mempool.space: {last_err}")

    def get_tx(self, txid: str, verbose: bool = True) -> Any:
        # verbose wird bei Esplora nicht benötigt – Parameter nur für Interface-Kompatibilität
        _ = verbose  # explizit als ungenutzt markieren
        return self._get_json(f"/tx/{txid}")# Esplora: JSON-Transaktion

    def block_header(self, height: int) -> str:
        # /block-height/:height -> block hash (text), dann /block/:hash/header -> header hex (text)
        block_hash = self._get_json(f"/block-height/{int(height)}")
        if not block_hash or not isinstance(block_hash, str):
            raise ElectrumXRPCError("Konnte Blockhash nicht ermitteln")
        header_hex = self._get_json(f"/block/{block_hash}/header")
        if not header_hex or not isinstance(header_hex, str):
            raise ElectrumXRPCError("Konnte Blockheader nicht laden")
        return header_hex

    def scripthash_history(self, scripthash: str) -> List[Dict[str, Any]]:
        # Liefert vollständige TX-Objekte; wir mappen auf Electrum-ähnliche Einträge
        lst = self._get_json(f"/scripthash/{scripthash}/txs") or []
        res = []
        for tx in lst:
            txid = tx.get("txid")
            h = 0
            st = tx.get("status") or {}
            if st.get("confirmed"):
                h = int(st.get("block_height", 0) or 0)
            res.append({"tx_hash": txid, "height": h})
        return res

    def scripthash_utxos(self, scripthash: str) -> List[Dict[str, Any]]:
        return self._get_json(f"/scripthash/{scripthash}/utxo") or []

# ---------- Blockheader-Hilfe ----------
def header_hex_to_hash_and_time(header_hex: str) -> Tuple[str, Optional[int]]:
    """Parst einen 80-Byte-Blockheader-Hex-String und gibt
    den Block-Hash (double-SHA256, little-endian) und den nTime-Wert zurück."""
    try:
        raw = bytes.fromhex(header_hex)
        if len(raw) < 80:
            return ("", None)
        h = hashlib.sha256(hashlib.sha256(raw).digest()).digest()[::-1].hex()
        ntime = struct.unpack("<I", raw[68:72])[0]
        return (h, ntime)
    except Exception:
        return ("", None)

# ---------- CSV-Felder ----------
CSV_FIELDS = [
    "event_number",
    "event",
    "event_date_time_utc",
    "event_date_time_mez",
    "transaction_id",
    "transaction_explorer_url",
    "transaction_explorer_url_link",
    "transaction_fee_btc",
    "address_index",
    "address_type",
    "address",
    "address_value_btc",
    "address_owner",
    "address_explorer_url",
    "address_explorer_url_link",
    "blockheight",
    "blockhash",
    "exchange_name",
    "exchange_type",
    "wallet_account_number",
    "wallet_account_name",
    "derivation_path",
    "wallet_account_extended_public_key_1",
    "master_fingerprint_1",
    "wallet_account_extended_public_key_2",
    "master_fingerprint_2",
    "exchange_rate_btc_euro",
    "exchange_fee_btc",
    "exchange_fee_euro",
    "amount_btc",
    "amount_euro",
    "description_owner",
    "description_authority",
    "document_1",
    "document_2",
    "document_3",
    "document_4",
    "document_5",
    "document_6",
    "document_7",
    "document_8",
    "document_9",
    "document_10",
    "document_11",
    "document_12",
]

def write_csv(path: str, rows: List[Dict[str, Any]]):
    """Schreibt eine Liste von Zeilen-Dicts als CSV-Datei mit Semikolon-Trennzeichen
    und den in CSV_FIELDS definierten Spalten."""
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, delimiter=";", extrasaction="ignore")
        writer.writeheader()
        writer.writerows({k: (v if v is not None else "") for k, v in row.items()} for row in rows)

def _make_row(overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Erstellt eine CSV-Zeile mit Standard-Leerfeldern, überschrieben durch `overrides`."""
    row = {field: "" for field in CSV_FIELDS}
    row.update(overrides)
    return row

# ---------- Kernlogik ----------
def extract_address_from_vout(vout_entry: Dict[str, Any]) -> str:
    """
    Unterstützt Electrum-Verbose (scriptPubKey.address/addresses) und Esplora (scriptpubkey_address).
    """
    # Esplora-Style
    addr_esplora = vout_entry.get("scriptpubkey_address")
    if addr_esplora:
        return addr_esplora
    # Electrum-Style
    spk = vout_entry.get("scriptPubKey", {})
    addrs = spk.get("addresses") or []
    if isinstance(addrs, list) and addrs:
        return addrs[0]
    addr = spk.get("address")
    return addr or ""

def find_height_via_history(client_any: Any, tx_verbose: dict, txid: str, debug: bool = True) -> Optional[int]:
    """Ermittelt die Blockhöhe einer Transaktion über die Script-History der Ausgabe-Adressen,
    falls die Höhe nicht direkt im TX-Objekt verfügbar ist."""
    for idx, vout in enumerate(tx_verbose.get("vout", [])):
        addr = extract_address_from_vout(vout)
        if not addr:
            continue
        try:
            sh = scripthash_from_address(addr)
            if debug:
                logger.debug(f"Versuche Höhe via History (Output {idx}, Scripthash {sh})")
            hist = client_any.scripthash_history(sh) or []
            for h in hist:
                if h.get("tx_hash") == txid and int(h.get("height", 0)) > 0:
                    if debug:
                        logger.debug(f"Höhe via History gefunden: {h['height']} (über Output {idx})")
                    return int(h["height"])
        except Exception as e:
            if debug:
                logger.debug(f"History-Fallback-Fehler (Output {idx}): {e}")
    return None

def fetch_tx_full(client_any: Any, txid: str, debug: bool = True) -> Tuple[Dict[str, Any], Optional[int], str, Optional[int], Optional[int]]:
    """Lädt eine vollständige Transaktion und liefert ein einheitliches Tupel:
    (tx_obj, blockheight, blockhash, blocktime, fee_sats).
    Kompatibel mit ElectrumX- und Mempool-Clients."""
    if not hasattr(client_any, "get_tx"):
        raise ElectrumXError(
            f"Der übergebene Client ({type(client_any).__name__}) implementiert 'get_tx' nicht."
        )
    raw_result = client_any.get_tx(txid, verbose=True)

    # Electrum-Verbose (dict/list/string) oder Esplora-JSON (dict)
    if isinstance(raw_result, dict):
        tx = raw_result
    elif isinstance(raw_result, list):
        def _extract_tx_from_list(lst):
            for item in lst:
                if isinstance(item, dict):
                    return item
                if isinstance(item, str):
                    s = item.strip()
                    if s.startswith("{") and s.endswith("}"):
                        try:
                            parsed = json.loads(s)
                            if isinstance(parsed, dict):
                                return parsed
                        except Exception:
                            pass
                if isinstance(item, (list, tuple)):
                    found = _extract_tx_from_list(item)
                    if isinstance(found, dict):
                        return found
            return None
        tx = _extract_tx_from_list(raw_result) or {}
        if not tx and debug:
            logger.debug("Liste ohne TX-Objekt; fahre ohne Herkunftsdetails fort.")
    elif isinstance(raw_result, str):
        try:
            parsed = json.loads(raw_result)
            tx = parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            if debug:
                logger.debug("Nur Hex-String (kein verbose JSON).")
            tx = {}
    else:
        tx = {}

    # gemeinsame Felder extrahieren
    fee_sats = tx.get("fee")
    blockheight = tx.get("blockheight") or tx.get("height")
    blockhash = tx.get("blockhash") or ""
    blocktime = tx.get("blocktime") or tx.get("time")

    # Esplora-Statusblock (mempool.space)
    status = tx.get("status") or {}
    if status:
        if status.get("confirmed") and not blockheight:
            blockheight = status.get("block_height")
        if status.get("block_hash") and not blockhash:
            blockhash = status.get("block_hash")
        if status.get("block_time") and not blocktime:
            blocktime = status.get("block_time")

    # Falls Höhe fehlt, via History (über Output-Adressen)
    if not blockheight and tx:
        bh_via_hist = find_height_via_history(client_any, tx, txid, debug=debug)
        if bh_via_hist:
            blockheight = bh_via_hist

    # Header für Hash/Zeit ergänzen (funktioniert bei beiden Clients)
    if blockheight and (not blockhash or not blocktime):
        try:
            header_hex = client_any.block_header(int(blockheight))
            bh, ntime = header_hex_to_hash_and_time(header_hex)
            if not blockhash and bh:
                blockhash = bh
            if not blocktime and ntime:
                blocktime = ntime
        except Exception as e:
            if debug:
                logger.debug(f"Header-Nachladung fehlgeschlagen: {e}")

    return tx, (int(blockheight) if blockheight else None), str(blockhash) if blockhash else "", (int(blocktime) if blocktime else None), fee_sats

def compute_fee_if_needed(client_any: Any, tx: Dict[str, Any], fee_sats: Optional[int], debug: bool = True) -> Optional[int]:
    """Berechnet die Transaktionsgebühr in Satoshi, falls sie nicht bereits bekannt ist.
    Summiert dafür alle Input- und Output-Werte; Coinbase-Transaktionen liefern None."""
    if fee_sats is not None:
        return fee_sats
    # Coinbase-Check zuerst: keine Gebühr bei Coinbase-Transaktionen
    if any("coinbase" in vin for vin in tx.get("vin", [])):
        return None
    try:
        vout_value_sats = 0
        for vout in tx.get("vout", []):
            if "value" in vout and isinstance(vout["value"], int):
                vout_value_sats += int(vout["value"])  # Esplora: sats
            else:
                val_btc = D(str(vout.get("value", "0")))
                vout_value_sats += int(val_btc * D(100_000_000))

        vin_value_sats = 0
        for vin in tx.get("vin", []):
            prevout = vin.get("prevout") or {}
            if "value" in prevout:
                vin_value_sats += int(prevout["value"])
                continue
            prev_txid = vin.get("txid")
            prev_vout_i = int(vin.get("vout", 0))
            prev_tx, _, _, _, _ = fetch_tx_full(client_any, prev_txid, debug=debug)
            prev_outs = prev_tx.get("vout", [])
            prev_out = prev_outs[prev_vout_i] if prev_outs and 0 <= prev_vout_i < len(prev_outs) else {}
            if "value" in prev_out and isinstance(prev_out["value"], int):
                vin_value_sats += int(prev_out["value"])
            else:
                val_btc = D(str(prev_out.get("value", "0")))
                vin_value_sats += int(val_btc * D(100_000_000))

        fee = vin_value_sats - vout_value_sats
        return max(fee, 0)
    except ElectrumXConnectionError:
        # Netzwerkfehler beim Laden einer Vorgänger-TX: nach oben weitergeben
        raise
    except Exception as e:
        if debug:
            logger.debug(f"Gebührenberechnung fehlgeschlagen: {e}")
        return None

def build_rows_for_csv(
        client_any: Any,
        main_txid: str,
        tx: Dict[str, Any],
        main_height: Optional[int],
        main_blockhash: str,
        main_time: Optional[int],
        main_fee_sats: Optional[int],
        debug: bool = True,
        decimal_sep: str = ",",
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Erstellt alle CSV-Zeilen für eine Transaktion (je eine Zeile pro Input und Output).
    Gibt ein Tupel aus (rows, inputs_summary, outputs_summary) zurück."""
    rows: List[Dict[str, Any]] = []
    inputs_summary: List[Dict[str, Any]] = []
    outputs_summary: List[Dict[str, Any]] = []

    tx_explorer = MEMPOOL_TX_URL.format(main_txid)
    tx_iso_utc = unix_to_iso_utc(main_time)
    tx_mez = unix_to_mez_excel(main_time)
    fee_btc = sats_to_btc(main_fee_sats) if main_fee_sats is not None else None

    if debug:
        logger.debug(f"Starte Rückverfolgung für TX {main_txid}")
        if main_height:
            logger.debug(f"Blockhöhe: {main_height}")

    # INPUTS
    for i, vin in enumerate(tx.get("vin", [])):
        if "coinbase" in vin:
            row = _make_row({
                "event": "transaction",
                "event_date_time_utc": tx_iso_utc,
                "event_date_time_mez": tx_mez,
                "transaction_id": main_txid,
                "transaction_explorer_url": tx_explorer,
                "transaction_fee_btc": btc_fmt(fee_btc, decimal_sep),
                "address_index": i,
                "address_type": "input",
                "blockheight": main_height or "",
                "blockhash": main_blockhash or "",
            })
            rows.append(row)
            inputs_summary.append({"address": "", "value_btc": ""})
            continue

        prev_txid = vin.get("txid", "")
        prev_vout_i = int(vin.get("vout", 0))

        addr = ""
        value_btc = ""

        # Esplora liefert prevout direkt
        prevout = vin.get("prevout") or {}
        if prevout:
            addr = prevout.get("scriptpubkey_address") or ""
            pv_val_sats = prevout.get("value")
            value_btc = btc_fmt(sats_to_btc(pv_val_sats), decimal_sep) if pv_val_sats is not None else ""
        else:
            # Fallback: Vor-TX laden
            try:
                prev_tx, _, _, _, _prev_fee = fetch_tx_full(client_any, prev_txid, debug=debug)
            except ElectrumXConnectionError as e:
                logger.warning(f"Herkunfts-Transaktion konnte nicht geladen werden ({prev_txid}): {e}")
                prev_tx = {}

            if prev_tx:
                try:
                    prev_outs = prev_tx.get("vout", [])
                    if prev_outs and 0 <= prev_vout_i < len(prev_outs):
                        prev_out = prev_outs[prev_vout_i]
                        addr = extract_address_from_vout(prev_out)
                        if "value" in prev_out and isinstance(prev_out["value"], int):
                            value_btc = btc_fmt(sats_to_btc(prev_out["value"]), decimal_sep)
                        else:
                            v = D(str(prev_out.get("value", "0")))
                            value_btc = btc_fmt(v, decimal_sep)
                except Exception:
                    pass

        if debug and addr:
            try:
                sh = scripthash_from_address(addr)
                logger.debug(f"Scripthash (INPUT {i}): {sh}")
                try:
                    hist = client_any.scripthash_history(sh) or []
                    logger.debug(f"Anzahl gefundener Transaktionen (INPUT {i}, Addr {truncate_middle(addr)}): {len(hist)}")
                except Exception as e_hist:
                    logger.debug(f"History-Fehler (INPUT {i}): {e_hist}")
                try:
                    utxos = client_any.scripthash_utxos(sh) or []
                    if not utxos:
                        logger.debug(f"Keine UTXOs vorhanden für Adresse (INPUT {i}): {truncate_middle(addr)}")
                except Exception as e_utxo:
                    logger.debug(f"UTXO-Check-Fehler (INPUT {i}): {e_utxo}")
            except Exception as e_sh:
                logger.debug(f"Scripthash-Fehler (INPUT {i}): {e_sh}")

        row = _make_row({
            "event": "transaction",
            "event_date_time_utc": tx_iso_utc,
            "event_date_time_mez": tx_mez,
            "transaction_id": main_txid,
            "transaction_explorer_url": tx_explorer,
            "transaction_fee_btc": btc_fmt(fee_btc, decimal_sep),
            "address_index": i,
            "address_type": "input",
            "address": addr,
            "address_value_btc": value_btc,
            "address_explorer_url": MEMPOOL_ADDR_URL.format(addr) if addr else "",
            "blockheight": main_height or "",
            "blockhash": main_blockhash or "",
        })
        rows.append(row)
        inputs_summary.append({"address": addr, "value_btc": value_btc})

    # OUTPUTS
    for i, vout in enumerate(tx.get("vout", [])):
        addr = extract_address_from_vout(vout)
        if "value" in vout and isinstance(vout["value"], int):
            value_btc = btc_fmt(sats_to_btc(vout["value"]), decimal_sep)
        else:
            value_btc = btc_fmt(D(str(vout.get("value", "0"))), decimal_sep)

        if debug and addr:
            try:
                sh = scripthash_from_address(addr)
                logger.debug(f"Scripthash (OUTPUT {i}): {sh}")
                try:
                    hist = client_any.scripthash_history(sh) or []
                    logger.debug(f"Anzahl gefundener Transaktionen (OUTPUT {i}, Addr {truncate_middle(addr)}): {len(hist)}")
                except Exception as e_hist:
                    logger.debug(f"History-Fehler (OUTPUT {i}): {e_hist}")
                try:
                    utxos = client_any.scripthash_utxos(sh) or []
                    if not utxos:
                        logger.debug(f"Keine UTXOs vorhanden für Adresse (OUTPUT {i}): {truncate_middle(addr)}")
                except Exception as e_utxo:
                    logger.debug(f"UTXO-Check-Fehler (OUTPUT {i}): {e_utxo}")
            except Exception as e_sh:
                logger.debug(f"Scripthash-Fehler (OUTPUT {i}): {e_sh}")

        row = _make_row({
            "event": "transaction",
            "event_date_time_utc": tx_iso_utc,
            "event_date_time_mez": tx_mez,
            "transaction_id": main_txid,
            "transaction_explorer_url": tx_explorer,
            "transaction_fee_btc": btc_fmt(fee_btc, decimal_sep),
            "address_index": i,
            "address_type": "output",
            "address": addr,
            "address_value_btc": value_btc,
            "address_explorer_url": MEMPOOL_ADDR_URL.format(addr) if addr else "",
            "blockheight": main_height or "",
            "blockhash": main_blockhash or "",
        })
        rows.append(row)
        outputs_summary.append({"address": addr, "value_btc": value_btc})

    return rows, inputs_summary, outputs_summary

def main():
    """Einstiegspunkt: Parst Kommandozeilenargumente, baut den Mempool-Client auf,
    lädt die Transaktion, berechnet Gebühren und schreibt die Ergebnis-CSV."""
    parser = argparse.ArgumentParser(description="BTC Mittelherkunftsnachweis aus mempool.space")
    parser.add_argument("transaction_id", help="Zu untersuchende Transaktions-ID (txid)")

    # mempool.space
    parser.add_argument("--mempool-base", default="https://mempool.space/api", help="Basis-URL der mempool.space API")
    parser.add_argument("--cafile", default="", help="Pfad zu einem CA-Bundle (überschreibt certifi/System)")
    parser.add_argument("--insecure", action="store_true", help="TLS-Validierung deaktivieren (nur Test!)")
    parser.add_argument("--timeout", type=float, default=20.0, help="Socket-Timeout je Lesevorgang (Sek.)")

    # Ausgabe/Optionen
    parser.add_argument("--csv-out", default="nachweis.csv", help="Pfad zur Ausgabedatei (CSV)")
    parser.add_argument(
        "--decimal-sep",
        default=",",
        choices=[",", "."],
        help="Dezimaltrennzeichen in der CSV-Ausgabe: ',' (Standard, Excel DE) oder '.' (international)",
    )
    parser.add_argument("--log-file", default="", help="Pfad zur Log-Ausgabedatei (optional)")
    parser.add_argument("--debug", action="store_true", help="zusätzliche Debug-Infos ausgeben")

    args = parser.parse_args()

    setup_logging(debug=args.debug, log_file=args.log_file if args.log_file.strip() else None)

    cafile = args.cafile if args.cafile.strip() else None
    client: Any = MempoolClient(base_url=args.mempool_base, timeout=args.timeout, retries=1, cafile=cafile, insecure=args.insecure)
    if args.debug:
        src = cafile or (f"certifi ({DEFAULT_CAFILE})" if DEFAULT_CAFILE else "System-Store")
        insecure_note = " (INSECURE)" if args.insecure else ""
        logger.debug(f"Verwende mempool.space REST-API: {args.mempool_base} | CA: {src}{insecure_note}")

    try:
        tx, bh, bhash, btime, fee_sats = fetch_tx_full(client, args.transaction_id, debug=args.debug)
        fee_sats = compute_fee_if_needed(client, tx, fee_sats, debug=args.debug)

        rows, ins_sum, outs_sum = build_rows_for_csv(
            client, args.transaction_id, tx, bh, bhash, btime, fee_sats,
            debug=args.debug, decimal_sep=args.decimal_sep
        )

        write_csv(args.csv_out, rows)
        logger.info(f"CSV geschrieben: {args.csv_out}")

        if args.debug and not bh:
            logger.debug("Hinweis: Keine Blockhöhe gefunden (TX unbestätigt oder nicht in History auffindbar).")

    except KeyboardInterrupt:
        logger.error("\nVom Benutzer abgebrochen.")
        sys.exit(130)
    except ElectrumXConnectionError as e:
        logger.error(f"Verbindungsfehler: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unerwarteter Fehler: {e}")
        if args.debug:
            raise
        sys.exit(1)

if __name__ == "__main__":
    main()
