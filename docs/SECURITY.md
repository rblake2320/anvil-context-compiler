# Security Notes

- Bind the HTTP server to `127.0.0.1` unless behind a trusted gateway.
- Set `ANVIL_API_KEY` before serving over any network interface.
- Treat `.anvil/anvil_ledger.sqlite3` as sensitive. It stores exact source spans.
- Do not register high-risk tools unless policy enforcement exists outside ANVIL.
- Default compiler behavior blocks high-risk tools from loaded schemas.
- ANVIL does not execute arbitrary shell commands.
- Keep tenant ledgers separate.
- For regulated environments, add encryption at rest using your approved platform controls.
