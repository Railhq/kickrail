# MCP Registry listing

`server.json` is Kickrail's entry in the official MCP Registry (registry.modelcontextprotocol.io) as `com.kickrail/kickrail`. Directories that mirror the registry pick it up from there.

Ownership of the `com.kickrail` namespace is proved over HTTP: `web/public/.well-known/mcp-registry-auth` holds the public half of an Ed25519 key. The private half is not in this repo.

To publish a new version, bump `version`, then:

```sh
mcp-publisher login http --domain kickrail.com --private-key "$(openssl pkey -in <private key>.pem -outform DER | tail -c 32 | xxd -p -c 64)"
mcp-publisher publish
```
