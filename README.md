
# Transaction Collector

Ein Python-Kommandozeilenwerkzeug zum Abrufen und Dokumentieren von Bitcoin-Transaktionsdaten über die [mempool.space](https://mempool.space) Esplora REST API. Es erzeugt strukturierte CSV-Dateien, die sich für Mittelherkunftsnachweise oder die Rückverfolgung von Transaktionen eignen.

---

## Features

- Ruft vollständige Bitcoin-Transaktionsdetails ab (Inputs, Outputs, Gebühren, Blockinformationen)
- Löst Input-Adressen über `prevout`-Daten oder Vorgänger-Transaktionen auf
- Berechnet Transaktionsgebühren automatisch, falls nicht von der API geliefert
- Erzeugt strukturierte CSV-Dateien mit 44 Spalten pro Transaktionszeile
- Unterstützt UTC- und MEZ/MESZ-Zeitstempel (Europe/Berlin)
- Exponential Backoff mit Jitter für robuste HTTP-Wiederholungsversuche
- Optionale TLS-Zertifikatkonfiguration über `certifi` oder ein benutzerdefiniertes CA-Bundle
- Logging auf Konsole und/oder in eine Datei
- Batch-Verarbeitung mehrerer TX-IDs aus einer Textdatei
- Zwei Ausgabemodi: eine CSV pro TX-ID (`split`) oder eine kombinierte CSV (`combined`)

---

## Voraussetzungen

- Python 3.9+
- Optional: [`certifi`](https://pypi.org/project/certifi/) für einen aktuellen CA-Truststore (Installation: bash pip install certifi)


---

## Verwendung

bash python3 transaction_collector.py [OPTIONEN]

### Positionelle Argumente

| Argument  | Beschreibung                                                                 |
|-----------|------------------------------------------------------------------------------|
| `txlist`  | Pfad zur Textdatei mit TX-IDs (eine TX-ID pro Zeile, Kommentare mit `#`)    |

### Optionen

#### Verbindung & API

| Option             | Standard                        | Beschreibung                                                                                      |
|--------------------|---------------------------------|---------------------------------------------------------------------------------------------------|
| `--mempool-base`   | `https://mempool.space/api`     | Basis-URL der mempool.space Esplora REST API (z. B. für selbst gehostete Instanzen)               |
| `--cafile`         | *(leer)*                        | Pfad zu einem CA-Bundle, das `certifi` und den System-Truststore überschreibt                     |
| `--insecure`       | `False`                         | TLS-Validierung deaktivieren – **nur für Testzwecke!**                                            |
| `--timeout`        | `20.0`                          | Socket-Timeout je HTTP-Anfrage in Sekunden                                                        |

#### Ausgabe & Dateioptionen

| Option             | Standard   | Beschreibung                                                                                                                                               |
|--------------------|------------|------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `--output-mode`    | `split`    | Ausgabemodus: `split` erstellt je TX-ID eine eigene CSV-Datei; `combined` schreibt alle TX-IDs in eine gemeinsame Datei (`resources/combined.csv`)         |
| `--overwrite`      | `False`    | Vorhandene CSV-Dateien überschreiben anstatt zu überspringen                                                                                               |
| `--digits`         | *(keiner)* | Anzahl der Stellen für führende Nullen im Dateinamen (z. B. `3` → `001_abcdef…csv`). Schließt `--auto-digits` aus.                                        |
| `--auto-digits`    | `False`    | Stellenzahl automatisch anhand der Anzahl gültiger TX-IDs bestimmen. Schließt `--digits` aus.                                                              |
| `--decimal-sep`    | `,`        | Dezimaltrennzeichen in der CSV-Ausgabe: `,` (Standard, für deutsches Excel) oder `.` (international)                                                       |

#### Logging & Debugging

| Option             | Standard   | Beschreibung                                              |
|--------------------|------------|-----------------------------------------------------------|
| `--log-file`       | *(leer)*   | Pfad zur Log-Ausgabedatei (zusätzlich zur Konsolenausgabe)|
| `--debug`          | `False`    | Aktiviert ausführliche Debug-Ausgaben (Scripthashes, History-Abfragen, Header-Nachladung usw.) |

### Beispiel
bash python3 transaction_collector.py resources/transactions.txt
--decimal-sep ,
--log-file transaction_collector.log
--mempool-base [https://mempool.space/api](https://mempool.space/api)
--overwrite
--output-mode split
--digits 3

---

## Eingabedatei (`txlist`)

Die Eingabedatei enthält eine TX-ID pro Zeile (64 hexadezimale Zeichen).  
Leerzeilen und Zeilen, die mit `#` beginnen, werden ignoriert.  
Doppelte TX-IDs werden automatisch übersprungen.

### Beispiel einer Eingabedatei
\# transaction_id\
a1ef55cc86c0596b55ca92360715a57071cb3d598571013b51121eed4d2642c7
4d9887ac983f0487176ed76a5e2d8780bd7b89554f2b813f66b48f0093cacc40
---

## Ausgabedateien

- **split-Modus:** Für jede TX-ID wird eine Datei `resources/<index>_<txid[:16]>.csv` erzeugt.  
  Mit `--digits 3` und 2 TX-IDs entstehen z. B.: `resources/001_a1b2c3d4e5f6abcd.csv`, `resources/002_…`
- **combined-Modus:** Alle Zeilen werden in `resources/combined.csv` gesammelt.

Alle CSV-Dateien verwenden `;` als Feldtrenner und `UTF-8`-Kodierung.

---

## CSV-Ausgabeformat

Die CSV-Datei enthält **eine Zeile pro Input oder Output** der Transaktion. Die Spalten sind:

| Spalte                                | Beschreibung                                                                                                   |
|---------------------------------------|----------------------------------------------------------------------------------------------------------------|
| `event_number`                        | Fortlaufende Ereignisnummer (für manuelle Einträge)                                                            |
| `event`                               | Ereignistyp, z. B. `transaction`                                                                               |
| `event_date_time_utc`                 | Zeitstempel des Blocks in UTC im ISO-8601-Format (z. B. `2024-03-15T14:32:00+00:00`)                           |
| `event_date_time_mez`                 | Zeitstempel des Blocks in MEZ/MESZ (Europe/Berlin) im Format `YYYY-MM-DD HH:MM:SS`                             |
| `transaction_id`                      | Bitcoin-Transaktions-ID (64 hexadezimale Zeichen)                                                              |
| `transaction_explorer_url`            | Direkt-URL zur Transaktion auf mempool.space                                                                   |
| `transaction_explorer_url_link`       | Link in Excel zur Transaktion (für manuelle Einträge)                                                          |
| `transaction_fee_btc`                 | Transaktionsgebühr in BTC mit gewähltem Dezimaltrennzeichen                                                    |
| `address_index`                       | Nullbasierter Index des Inputs oder Outputs innerhalb der Transaktion                                          |
| `address_type`                        | Typ der Adresse: `input` (Eingabe) oder `output` (Ausgabe)                                                     |
| `address`                             | Bitcoin-Adresse des Inputs oder Outputs (P2PKH, P2SH, Bech32)                                                  |
| `address_value_btc`                   | Betrag in BTC für diese Adresse mit gewähltem Dezimaltrennzeichen                                              |
| `address_owner`                       | Bezeichnung des Adressinhabers (für manuelle Einträge)                                                         |
| `address_explorer_url`                | Direkt-URL zur Adresse auf mempool.space                                                                       |
| `address_explorer_url_link`           | Link in Excel zur Adresse (für manuelle Einträge)                                                              |
| `blockheight`                         | Blockhöhe (Blocknummer), in dem die Transaktion bestätigt wurde                                                |
| `blockhash`                           | Hexadezimaler Hash des Blocks                                                                                  |
| `exchange_name`                       | Name der Börse / Plattform oder Wallet (für manuelle Einträge)                                                 |
| `exchange_type`                       | Typ der Börse / Wallet (für manuelle Einträge)                                                                 |
| `wallet_account_number`               | Account innerhalb eines Wallets (für manuelle Einträge)                                                        |
| `wallet_account_name`                 | Account-Name innerhalb eines Wallets (für manuelle Einträge)                                                   |
| `derivation_path`                     | BIP32/BIP44-Ableitungspfad des Schlüssels (für manuelle Einträge, z. B. `m/84'/0'/0'/0/0`)                     |
| `wallet_account_extended_public_key_1`| Erweiterter öffentlicher Schlüssel (xpub/ypub/zpub) des Wallet-Accounts (1) (für manuelle Einträge)            |
| `master_fingerprint_1`                | Master-Fingerprint des Wallets (1) (für manuelle Einträge)                                                     |
| `wallet_account_extended_public_key_2`| Erweiterter öffentlicher Schlüssel (xpub/ypub/zpub) des Wallet-Accounts (2) (für Multi-Sig, manuelle Einträge) |
| `master_fingerprint_2`                | Master-Fingerprint des Wallets (2) (für manuelle Einträge)                                                     |
| `exchange_rate_btc_euro`              | Wechselkurs BTC/EUR zum Zeitpunkt der Transaktion (für manuelle Einträge)                                      |
| `exchange_fee_btc`                    | Börsengebühr in BTC (für manuelle Einträge)                                                                    |
| `exchange_fee_euro`                   | Börsengebühr in EUR (für manuelle Einträge)                                                                    |
| `amount_btc`                          | Transaktionsbetrag in BTC (für manuelle Einträge)                                                              |
| `amount_euro`                         | Transaktionsbetrag in EUR (für manuelle Einträge)                                                              |
| `description_owner`                   | Freitextbeschreibung für den Eigentümer (für manuelle Einträge)                                                   |
| `description_authority`               | Freitextbeschreibung für eine Behörde oder Dritte gedacht (für manuelle Einträge)                              |
| `document_1` – `document_12`          | Felder für Verweise auf Belege und Nachweisdokumente, z. B. Dateinamen oder URLs (für manuelle Einträge)       |

> **Hinweis:** Felder, die als „für manuelle Einträge" gekennzeichnet sind, werden vom Skript leer ausgegeben und können nachträglich manuell in der CSV befüllt werden.

---

## Architekturübersicht

| Komponente                 | Beschreibung                                                                                       |
|----------------------------|----------------------------------------------------------------------------------------------------|
| `MempoolClient`            | HTTP-Client für die mempool.space Esplora REST API mit Rate-Limiting und Retry-Logik               |
| `fetch_tx_full()`          | Lädt und normalisiert ein vollständiges Transaktionsobjekt inkl. Blockhöhe, Hash und Zeit          |
| `compute_fee_if_needed()`  | Berechnet die Gebühr durch Summierung aller Inputs minus Outputs, falls nicht von der API geliefert |
| `build_rows_for_csv()`     | Erstellt alle CSV-Zeilen für Inputs und Outputs einer Transaktion                                  |
| `write_csv()`              | Schreibt die fertige CSV-Datei mit Semikolon-Trenner                                               |
| `scripthash_from_address()`| Berechnet den Electrum-kompatiblen Script-Hash einer Bitcoin-Adresse                               |
| `address_to_scriptpubkey()`| Konvertiert P2PKH-, P2SH- und Bech32-Adressen in das zugehörige scriptPubKey-Format               |

---

## Exit-Codes

| Code | Bedeutung                                                    |
|------|--------------------------------------------------------------|
| `0`  | Alle TX-IDs erfolgreich verarbeitet                          |
| `1`  | Eingabedatei nicht gefunden oder ungültiger Parameter        |
| `2`  | Mindestens eine TX-ID konnte nicht verarbeitet werden        |
| `130`| Abbruch durch den Benutzer (Strg+C)                          |