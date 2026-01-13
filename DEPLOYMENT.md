# Deployment Guide

This guide covers deploying the Discord bot and wrapper service to a server.

## Prerequisites

- A server (VPS, dedicated, or Raspberry Pi)
- Docker and Docker Compose (recommended)
- Or: Python 3.11+, Rust toolchain, Node.js (for manual deployment)

---

## Option 1: Docker Compose (Recommended)

The simplest deployment method using Docker Compose.

### 1. Clone and Configure

```bash
# Clone the repository
git clone <your-repo-url> discord-bot
cd discord-bot

# Create environment file
cp .env.example .env

# Edit with your credentials
nano .env
```

Required environment variables:
```env
DISCORD_TOKEN=your_discord_bot_token
DISCORD_GUILD_ID=your_guild_id
ANTHROPIC_API_KEY=your_anthropic_api_key
```

### 2. Deploy with Docker Compose

```bash
# Build and start all services
cd docker
docker-compose up -d

# View logs
docker-compose logs -f

# Scale workers (optional)
docker-compose up -d --scale worker=5
```

### 3. Verify

```bash
# Check service status
docker-compose ps

# Check wrapper health
curl http://localhost:8000/api/v1/health
```

---

## Option 2: Systemd Services (Manual Deployment)

For more control, deploy as systemd services.

### 1. Install Dependencies

```bash
# Python
sudo apt update
sudo apt install python3.11 python3.11-venv

# Rust
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source ~/.cargo/env

# Node.js (for Claude Code CLI)
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install nodejs

# Claude Code CLI
sudo npm install -g @anthropic-ai/claude-code
```

### 2. Setup Wrapper Service

```bash
# Create user
sudo useradd -r -s /bin/false claude-wrapper

# Setup directory
sudo mkdir -p /opt/claude-wrapper
sudo chown claude-wrapper:claude-wrapper /opt/claude-wrapper

# Clone and install
cd /opt/claude-wrapper
git clone <your-repo-url> .
cd wrapper
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Create systemd service `/etc/systemd/system/claude-wrapper.service`:
```ini
[Unit]
Description=Claude Code Wrapper Service
After=network.target

[Service]
Type=simple
User=claude-wrapper
Group=claude-wrapper
WorkingDirectory=/opt/claude-wrapper/wrapper
Environment="PATH=/opt/claude-wrapper/wrapper/.venv/bin:/usr/local/bin:/usr/bin"
EnvironmentFile=/opt/claude-wrapper/.env
ExecStart=/opt/claude-wrapper/wrapper/.venv/bin/uvicorn wrapper.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### 3. Setup Discord Bot

```bash
# Build the bot
cd /opt/claude-wrapper/bot
cargo build --release

# Copy binary
sudo cp target/release/discord-bot /usr/local/bin/
```

Create systemd service `/etc/systemd/system/discord-bot.service`:
```ini
[Unit]
Description=Claude Discord Bot
After=network.target claude-wrapper.service
Requires=claude-wrapper.service

[Service]
Type=simple
User=claude-wrapper
Group=claude-wrapper
EnvironmentFile=/opt/claude-wrapper/.env
Environment="WRAPPER_URL=http://localhost:8000"
ExecStart=/usr/local/bin/discord-bot
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### 4. Enable and Start

```bash
sudo systemctl daemon-reload
sudo systemctl enable claude-wrapper discord-bot
sudo systemctl start claude-wrapper discord-bot

# Check status
sudo systemctl status claude-wrapper discord-bot

# View logs
sudo journalctl -u discord-bot -f
```

---

## Option 3: Kubernetes (K3s)

For the Raspberry Pi cluster deployment.

### 1. Install K3s

On the master node:
```bash
curl -sfL https://get.k3s.io | sh -
```

On worker nodes:
```bash
curl -sfL https://get.k3s.io | K3S_URL=https://<master-ip>:6443 K3S_TOKEN=<token> sh -
```

### 2. Create Secrets

```bash
kubectl create secret generic claude-secrets \
  --from-literal=discord-token=<your-token> \
  --from-literal=anthropic-api-key=<your-key>
```

### 3. Deploy

```bash
kubectl apply -k k8s/overlays/production/
```

### 4. Verify

```bash
kubectl get pods
kubectl logs -f deployment/discord-bot
```

---

## Project Registration on Server

After deployment, register your projects via Discord:

```
/project add name:my-api path:/home/user/projects/my-api description:Main API server
/project list
/task prompt:"List all TODO comments" project:my-api
```

Or via API:
```bash
curl -X POST http://localhost:8000/api/v1/projects \
  -H "Content-Type: application/json" \
  -d '{"name": "my-api", "path": "/home/user/projects/my-api"}'
```

---

## Security Considerations

1. **API Access**: The wrapper service listens on port 8000. In production:
   - Use a reverse proxy (nginx, Caddy) with HTTPS
   - Restrict access to trusted IPs only
   - Or keep it internal-only (localhost)

2. **File System Access**: The wrapper can execute Claude Code on any registered project path. Be careful what paths you register.

3. **Discord Permissions**: Only trusted users should have access to the Discord commands. Use Discord's role-based permissions.

4. **Secrets**: Never commit `.env` files. Use proper secret management in production.

---

## Monitoring

### Docker Compose
```bash
docker-compose logs -f
docker stats
```

### Systemd
```bash
journalctl -u claude-wrapper -f
journalctl -u discord-bot -f
```

### Health Checks
```bash
# Wrapper
curl http://localhost:8000/api/v1/health

# List active sessions
curl http://localhost:8000/api/v1/sessions

# List projects
curl http://localhost:8000/api/v1/projects
```

---

## Updating

### Docker Compose
```bash
cd docker
docker-compose down
git pull
docker-compose build
docker-compose up -d
```

### Systemd
```bash
sudo systemctl stop discord-bot claude-wrapper
cd /opt/claude-wrapper
git pull
cd wrapper && source .venv/bin/activate && pip install -e .
cd ../bot && cargo build --release
sudo cp target/release/discord-bot /usr/local/bin/
sudo systemctl start claude-wrapper discord-bot
```
