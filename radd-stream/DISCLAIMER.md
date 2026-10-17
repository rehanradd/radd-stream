# Legal & Architectural Disclaimer

> **Notice:** This project is provided strictly for educational, security research, and data-engineering purposes.

## Architecture & Data Flow

`radd-stream` is an open-source, zero-dependency network diagnostic and metadata aggregation engine written entirely in standard Python.

1. **No Media Hosting:** This software does not store, host, stream, re-encode, or distribute any video files, binary media assets, or copyrighted broadcasts.
2. **Zero DRM Circumvention:** The engine does not bypass or tamper with any Digital Rights Management (DRM) technologies, access keys, or encrypted media containers.
3. **Public Data Ingestion:** All indexing operations query publicly accessible XML sitemaps and open REST API endpoints published to the public internet by third-party web servers.
4. **Network Diagnostic Probing:** The health checker functions as an HTTP diagnostic tool, measuring server responsiveness, latency, and standard HTTP response status codes (such as `200 OK` and `206 Partial Content`).
5. **Local Catalog Ownership:** All catalog records and extracted metadata references are stored exclusively in a private, local SQLite database (`fast_fetch.db`) maintained on the end-user's machine.

## User Responsibility

Users of this software are solely responsible for ensuring that their data ingestion and network diagnostics comply with all applicable local laws, regulations, and third-party terms of service in their respective jurisdictions.
