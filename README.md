# DomainRadar – Loader & Pre-filter

The **Loader & Pre-filter** is a modular application designed to load domain names from various sources, filter them based on predefined criteria, and provide the filtered results to subsequent components of the **DomainRadar** system. Its goal is to optimize system performance by discarding invalid or benign domains early in the pipeline.

## How It Works

The application operates in a main loop consisting of three phases:

1. **Loading:** Domain names are retrieved using input modules.
2. **Filtering:** Domains are processed through configurable filter modules to determine their handling.
3. **Output:** Filtered domain names are passed to output modules for further processing.

The main loop is preceded by an initialization phase where the application configures itself based on settings stored in **Apache Kafka**.

## Configuration

Set the following **environment variables** before running the Loader:
- `DOMAINRADAR_KAFKA_BROKER_URL`: URL of the Kafka broker.
- `DOMAINRADAR_KAFKA_SECRETS_DIR`: Path to a directory that contains the following authentication files:
    - `ca-cert.pem`: CA certificate of the issuer of the client certificates.
    - `loader-cert.pem`: Client certificate for authenticating the Loader at Kafka.
    - `loader-priv-key.pem`: Private key matching the public key in the client certificate.
    - `key-password.txt`: Password for unlocking the encrypted private key.

The main configuration is **dynamically loaded during runtime** from the `configuration_states` Kafka topic. See the [runtime configuration exchange](https://github.com/nesfit/domainradar/blob/main/docs/configuration_exchange.md) documentation for more information. An example of a configuration message is available in `config.example.json`.

## Modules

### Input Modules

Input modules load domain names from various sources. To add an input module, implement a class deriving from `feta_prefilter.Sources.BaseSource.BaseSource` with the method:
- `collect(self) -> list[str]`: Returns a list of domain names for processing.

### Filter Modules

Filter modules mark the input domain names with one of the **filtering actions**:
- **PASS (0)**: Domain is valid and forwarded for further processing.
- **DROP (1)**: Domain is discarded completely.
- **STORE (2)**: Domain is flagged as filtered but sent to the output modules for storage.

To add a filter, implement a class deriving from `feta_prefilter.Filters.BaseFilter.BaseFilter`. The base filter includes a suffix trie structure for efficient filtering. You can either override the constructor, where you fill `self.suffix_trie` with the domains to filter, or you can instead override the `filter` method to process the domains using custom logic:
- `filter(self, domains: list[str]) -> list[FilterAction]`: Filters domain names and assigns an action (`PASS`, `DROP`, or `STORE`).

### Output Modules

Output modules send filtered results to the appropriate destinations. To add an output module, implement a class deriving from `feta_prefilter.Outputs.BaseOutput.BaseOutput` that implements:
  - `__init__(self)`: Initializes connections to output destinations.
  - `output(self, domains: list[dict])`: outputs filtered data. The `domains` argument contains a list of objects with the domain name and results of the individual filters:
```python
{ domain="domain name", f_results= {"filter1": PASS, "filter2": DROP} }
```


## Usage

1. Start Apache Kafka, configure the topics required by the runtime configuration exchange mechanism.
2. Set the required environment variables.
3. Use **Poetry** for dependency management:
   ```bash
   poetry install
   poetry run python main.py
   ```
4. Deploy the application and configure input, filter, and output modules via Kafka.


## Requirements

- **Python Version:** 3.11
- **Dependency Manager:** Poetry
