# ProjectDiscovery security and reconnaissance tools

This optional category packages the official upstream Linux x86_64 release
binaries as independently versioned Nawa packages. Each archive is pinned by
its upstream release asset SHA-256 digest; no installer or auto-updater writes
outside Nawa's package database.

| Package | Purpose |
| --- | --- |
| `nuclei` | Template-based vulnerability scanning |
| `subfinder` | Passive subdomain discovery |
| `httpx` | HTTP probing and technology detection |
| `katana` | Web crawling and endpoint discovery |
| `naabu` | TCP port scanning |
| `dnsx` | DNS queries and resolution |
| `uncover` | Search-engine based exposed-host discovery |
| `interactsh-client` | Out-of-band interaction testing |
| `proxify` | HTTP(S) traffic capture, replay and manipulation |
| `tlsx` | TLS service and certificate probing |
| `asnmap` | ASN and network range mapping |
| `alterx` | Domain permutation generation |

Build the complete category with:

```sh
nawa --recipes recipes deps-all
# GitHub Actions: Build packages -> packages: @security
```

Or build selected tools by their package names, for example
`nuclei subfinder httpx katana`.

These are security assessment tools. Use them only against systems and assets
you own or are explicitly authorized to test. Passive discovery and OOB
callbacks may still disclose queried domains or metadata to third-party
providers. Some subfinder/uncover sources require provider API keys; configure
those in the tool's own config files rather than embedding credentials in
package recipes.
