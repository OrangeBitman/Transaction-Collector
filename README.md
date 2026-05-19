Hier ist eine passende `README.md` für das Projekt:

```markdown
# Transaction Collector

A Python command-line tool to collect and document Bitcoin transaction data using the [mempool.space](https://mempool.space) Esplora REST API. It generates a structured CSV file suitable for proof-of-funds or transaction traceability purposes.

---

## Features

- Fetches full Bitcoin transaction details (inputs, outputs, fees, block info)
- Resolves input addresses via `prevout` data or predecessor transactions
- Calculates transaction fees if not provided by the API
- Outputs a structured CSV file with 43 columns per transaction row
- Supports both UTC and MEZ/MESZ (Europe/Berlin) timestamps
- Exponential backoff with jitter for resilient HTTP retries
- Optional TLS certificate configuration via `certifi` or a custom CA bundle
- Debug logging to console and/or file

---

## Requirements

- Python 3.9+
- Optional: [`certifi`](https://pypi.org/project/certifi/) for an up-to-date CA trust store

Install optional dependencies:
```
bash
pip install certifi
```
---

## Usage
```
bash
python transaction_collector.py <transaction_id> [OPTIONS]
```
### Positional Arguments

| Argument         | Description                          |
|------------------|--------------------------------------|
| `transaction_id` | The Bitcoin transaction ID (txid) to analyze |

### Options

| Option              | Default                          | Description                                                |
|---------------------|----------------------------------|------------------------------------------------------------|
| `--mempool-base`    | `https://mempool.space/api`      | Base URL of the mempool.space API                          |
| `--cafile`          | *(empty)*                        | Path to a custom CA bundle (overrides certifi/system store)|
| `--insecure`        | `False`                          | Disable TLS validation (**testing only!**)                 |
| `--timeout`         | `20.0`                           | Socket timeout per request in seconds                      |
| `--csv-out`         | `nachweis.csv`                   | Output CSV file path                                       |
| `--decimal-sep`     | `,`                              | Decimal separator in CSV: `,` (German Excel) or `.`        |
| `--log-file`        | *(empty)*                        | Optional path to a log output file                         |
| `--debug`           | `False`                          | Enable verbose debug output                                |

### Examples

**Basic usage:**
```bash
python transaction_collector.py abc123def456...
```
```


**With custom output file and debug logging:**
```shell script
python transaction_collector.py abc123def456... --csv-out output.csv --debug
```


**Using a custom mempool instance and log file:**
```shell script
python transaction_collector.py abc123def456... \
  --mempool-base https://my-mempool-instance.local/api \
  --log-file run.log \
  --debug
```


---

## Output Format

The generated CSV file uses `;` as a field delimiter and includes the following columns (among others):

| Column                        | Description                              |
|-------------------------------|------------------------------------------|
| `event`                       | Event type (e.g. `transaction`)          |
| `event_date_time_utc`         | Timestamp in UTC (ISO 8601)              |
| `event_date_time_mez`         | Timestamp in MEZ/MESZ (Europe/Berlin)    |
| `transaction_id`              | Transaction ID (txid)                    |
| `transaction_explorer_url`    | Link to mempool.space transaction view   |
| `transaction_fee_btc`         | Transaction fee in BTC                   |
| `address_type`                | `input` or `output`                      |
| `address`                     | Bitcoin address                          |
| `address_value_btc`           | Value in BTC for this address            |
| `blockheight`                 | Block height                             |
| `blockhash`                   | Block hash                               |
| `document_1` – `document_12` | Free fields for supporting documents     |

---

## Architecture Overview

| Component              | Description                                                              |
|------------------------|--------------------------------------------------------------------------|
| `MempoolClient`        | HTTP client for the mempool.space Esplora REST API with retry logic      |
| `fetch_tx_full()`      | Fetches and normalizes a full transaction object                         |
| `compute_fee_if_needed()` | Calculates the fee by summing inputs minus outputs if not available  |
| `build_rows_for_csv()` | Builds the CSV rows for all inputs and outputs of a transaction          |
| `write_csv()`          | Writes the final CSV file                                                |

---

## License

This project is provided as-is without any warranty. Use at your own risk.
```
Die README enthält alle wesentlichen Informationen:
- **Features** auf einen Blick
- **Installationsanforderungen** mit optionalem `certifi`
- **Vollständige CLI-Referenz** mit Tabelle aller Parameter
- **Praxisbeispiele** für verschiedene Anwendungsfälle
- **CSV-Ausgabeformat** mit den wichtigsten Feldern
- **Architekturübersicht** der Kernkomponenten
```
