# Tunnel Exposure

Copyright 2026 Firefly Software Solutions Inc. Licensed under the Apache License 2.0.

Firefly Agentic Studio can be exposed to the internet through a Cloudflare
Quick Tunnel. This gives your local Studio instance a public HTTPS URL
without configuring DNS, certificates, or firewall rules -- and without
a Cloudflare account.

---

## Overview

Cloudflare Quick Tunnels use the `cloudflared` binary to create a
temporary, publicly accessible URL that proxies traffic to your local
server. The URL looks like `https://random-words.trycloudflare.com` and
stays active as long as the tunnel process runs.

This is useful for:

- Sharing a pipeline with a teammate for testing.
- Connecting external services (webhooks, mobile apps) to your local API.
- Demoing a pipeline without deploying to production.

---

## Installing cloudflared

### macOS

```bash
brew install cloudflared
```

### Linux

```bash
# Debian / Ubuntu
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb -o cloudflared.deb
sudo dpkg -i cloudflared.deb

# Or via the package manager
sudo apt install cloudflared
```

### Windows

Download from the [Cloudflare releases page](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/)
or use:

```powershell
winget install Cloudflare.cloudflared
```

### Verify Installation

```bash
cloudflared --version
```

---

## CLI Usage

The `firefly expose` command starts a tunnel that proxies to your running
Studio instance:

```bash
# Default: expose port 8470
firefly expose

# Custom port
firefly expose --port 9000
```

Output:

```
Studio is now publicly accessible at: https://random-words.trycloudflare.com
Press Ctrl+C to stop the tunnel.
```

The tunnel runs until you press `Ctrl+C`. Studio must already be running
on the specified port.

### Two-terminal workflow

Terminal 1 -- start Studio:

```bash
firefly studio --port 8470
```

Terminal 2 -- expose it:

```bash
firefly expose --port 8470
```

---

## Studio UI

The Studio top bar includes a **Share** button that manages the tunnel
through the API:

1. Click the **Share** button (globe icon) in the top bar.
2. Studio calls `POST /api/tunnel/start` to launch a quick tunnel.
3. The public URL appears in the UI and is copied to your clipboard.
4. Click the button again or use the stop action to call
   `POST /api/tunnel/stop`.

---

## Tunnel API

The tunnel is managed through three REST endpoints:

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/tunnel/status` | Current tunnel status |
| `POST` | `/api/tunnel/start` | Start a quick tunnel |
| `POST` | `/api/tunnel/stop` | Stop the running tunnel |

### Status Response

```json
{"active": false, "url": null, "port": 8470}
```

### Start Response

```json
{"url": "https://random-words.trycloudflare.com", "status": "active"}
```

If `cloudflared` is not installed:

```json
{
  "error": "cloudflared not installed",
  "install_url": "https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
}
```

### Stop Response

```json
{"status": "stopped"}
```

---

## External Testing with Tunnel URLs

Once the tunnel is active, all Studio endpoints are accessible via the
public URL:

```bash
TUNNEL="https://random-words.trycloudflare.com"

# Run a pipeline
curl -X POST "$TUNNEL/api/projects/my-project/run" \
  -H "Content-Type: application/json" \
  -d '{"input": "Test from external client"}'

# Check project schema
curl "$TUNNEL/api/projects/my-project/schema"

# Upload a file
curl -X POST "$TUNNEL/api/projects/my-project/upload" \
  -F "file=@document.pdf"

# GraphQL
curl -X POST "$TUNNEL/api/graphql" \
  -H "Content-Type: application/json" \
  -d '{"query": "{ projects { name } }"}'
```

WebSocket connections work through the tunnel as well:

```javascript
const ws = new WebSocket("wss://random-words.trycloudflare.com/ws/execution");
```

---

## Security Considerations

| Consideration | Guidance |
|---|---|
| **Public access** | Anyone with the URL can access your Studio instance. Share the URL only with trusted parties. |
| **No authentication** | Studio does not enforce authentication by default. Do not expose sensitive pipelines or API keys. |
| **Temporary URLs** | Quick tunnel URLs are random and change each time you restart. They are not guessable but are not secret either. |
| **Data in transit** | All traffic through the tunnel uses HTTPS. |
| **Local only** | The tunnel proxies to `localhost`. It does not expose other services on your machine. |
| **Lifetime** | The tunnel stops when you press Ctrl+C or close Studio. There is no persistent exposure. |

For production use, deploy behind a proper reverse proxy with
authentication rather than relying on quick tunnels.

---

## Troubleshooting

| Issue | Solution |
|---|---|
| "cloudflared is not installed" | Install `cloudflared` using the instructions above |
| Tunnel starts but URL not shown | Check that port 8470 (or your custom port) is not blocked |
| Connection refused through tunnel | Ensure Studio is running on the same port the tunnel targets |
| Tunnel stops unexpectedly | Check `cloudflared` logs; the process may have been killed |

---

*See also: [Project API](project-api.md) for the endpoints accessible
through the tunnel, [Studio](studio.md) for general Studio usage.*
