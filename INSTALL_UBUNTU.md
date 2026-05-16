# 🦉 OWL-AGENT Proxy Defense Stack — Ubuntu Installation Guide

> Complete installation guide for Ubuntu 20.04+ (also works on Debian 11+, Pop!_OS, Linux Mint, WSL2).

---

## Table of Contents

- [Quick Install (60 seconds)](#quick-install-60-seconds)
- [Manual Step-by-Step](#manual-step-by-step)
- [Phased Protocol Installation](#phased-protocol-installation)
- [Post-Install](#post-install)
- [Troubleshooting](#troubleshooting)
- [Uninstall](#uninstall)

---

## Quick Install (60 seconds)

### Automated Installer (Recommended)

```bash
# Fresh Ubuntu system — run this:
sudo apt update && sudo apt install -y curl git python3 python3-pip python3-venv
curl -fsSL https://raw.githubusercontent.com/marktantongco/owl-agent-proxy/main/scripts/install-ubuntu.sh | bash
source ~/.bashrc
owl-status
```

### One-Line (with sudo)

```bash
curl -fsSL https://raw.githubusercontent.com/marktantongco/owl-agent-proxy/main/scripts/install-ubuntu.sh | sudo bash
```

### User-Only (no sudo)

```bash
curl -fsSL https://raw.githubusercontent.com/marktantongco/owl-agent-proxy/main/scripts/install-ubuntu.sh | bash -s -- --user
```

### Minimal (Phase 1 only)

```bash
curl -fsSL https://raw.githubusercontent.com/marktantongco/owl-agent-proxy/main/scripts/install-ubuntu.sh | bash -s -- --minimal
```

---

## Manual Step-by-Step

### 1. System Preparation

```bash
# Update package list
sudo apt update

# Install essential build tools and Python
sudo apt install -y \
    build-essential \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    libssl-dev \
    libffi-dev \
    curl \
    git \
    wget \
    ca-certificates

# Verify Python version (must be >= 3.10)
python3 --version
# Expected: Python 3.10.x or higher
```

### 2. Clone the Repository

```bash
git clone https://github.com/marktantongco/owl-agent-proxy.git ~/owl-agent-proxy
cd ~/owl-agent-proxy
```

### 3. Create Virtual Environment

```bash
python3 -m venv ~/.owl-agent/venv
source ~/.owl-agent/venv/bin/activate
pip install --upgrade pip setuptools wheel
```

### 4. Install Core Dependencies (Phase 1)

```bash
pip install \
    aiohttp>=3.11.0 \
    aiofiles>=24.1.0 \
    cachetools>=5.5.0 \
    orjson>=3.10.0 \
    cryptography>=44.0.0 \
    PySocks>=1.7.1 \
    requests>=2.32.0 \
    urllib3>=2.4.0 \
    PyYAML>=6.0.2 \
    tenacity>=9.1.0 \
    fake-useragent>=2.2.0 \
    aiohttp-socks>=0.10.0 \
    certifi>=2025.0.0 \
    python-dateutil>=2.9.0

# Verify
python3 -c "import aiohttp, aiofiles, cachetools, orjson, cryptography, socks; print('✅ Core installed')"
```

### 5. Run Built-in Test

```bash
python3 proxy_defense.py
```

Expected output:
```
🦉 OWL-AGENT Proxy Defense Stack v3.0
==================================================
Proxy Pool: 0 | Healthy: 0
Protocols: {'http/1.1': True, 'http/2': False, 'ja3': False, 'websocket': False, 'browser': False}

Test: Status 200, Protocol: http/1.1

✅ Defense stack operational.
```

### 6. Deploy Source Files

```bash
# Create OWL-AGENT directory structure
mkdir -p ~/.owl-agent/{config,cache/{http,dedup,proxies},logs,skills/{development,system},workspace/{projects,worklogs}}

# Copy files
cp proxy_defense.py ~/.owl-agent/workspace/projects/
cp requirements.txt ~/.owl-agent/workspace/projects/
cp -r skills/* ~/.owl-agent/skills/
cp -r docs/* ~/.owl-agent/workspace/projects/
cp config/proxy_pool.template.json ~/.owl-agent/config/proxy_pool.json
chmod +x ~/.owl-agent/workspace/projects/proxy_defense.py
```

### 7. Shell Integration

Add to `~/.bashrc`:

```bash
cat >> ~/.bashrc << 'EOF'

# ─── 🦉 OWL-AGENT SHELL INTEGRATION ───────────────────────────────────────
export OWL_AGENT_HOME="$HOME/.owl-agent"
export OWL_AGENT_SKILLS="$OWL_AGENT_HOME/skills"
export OWL_AGENT_WORKSPACE="$OWL_AGENT_HOME/workspace"
export OWL_AGENT_CONFIG="$OWL_AGENT_HOME/config"
export OWL_AGENT_LOGS="$OWL_AGENT_HOME/logs"
export OWL_AGENT_CACHE="$OWL_AGENT_HOME/cache"
export OWL_AGENT_VENV="$OWL_AGENT_HOME/venv"

if [ -f "$OWL_AGENT_VENV/bin/activate" ] && [ -z "${VIRTUAL_ENV:-}" ]; then
    source "$OWL_AGENT_VENV/bin/activate"
fi

alias owl-status='echo "🦉 Owl Agent Status" && echo "  Skills: $(find "$OWL_AGENT_SKILLS" -name "*.md" 2>/dev/null | wc -l)" && echo "  Cache: $(ls "$OWL_AGENT_CACHE/http" 2>/dev/null | wc -l) entries" && python3 --version && echo "  Venv: $OWL_AGENT_VENV"'
alias owl-proxy='python3 "$OWL_AGENT_WORKSPACE/projects/proxy_defense.py"'
alias owl-venv='source "$OWL_AGENT_VENV/bin/activate"'

owl-skill() {
    local query="$1"
    [ -z "$query" ] && { echo "Usage: owl-skill <term>"; return 1; }
    find "$OWL_AGENT_SKILLS" -name "*.md" -exec grep -l "$query" {} + 2>/dev/null | head -5
}
# ─── END OWL-AGENT ──────────────────────────────────────────────────────────
EOF

source ~/.bashrc
```

### 8. Verify Installation

```bash
# Check status
owl-status

# Run CI/CD check
bash .github/scripts/ci-check.sh

# Run tests
python3 -m pytest tests/ -v
```

---

## Phased Protocol Installation

Install protocols on demand — start minimal, add only what you need.

### Phase 2: HTTP/2

```bash
source ~/.owl-agent/venv/bin/activate
pip install 'httpx[http2]>=0.28.0'
python3 -c "import httpx; c=httpx.AsyncClient(http2=True); print('✅ HTTP/2 available')"
```

### Phase 3: JA3 / TLS Fingerprint

```bash
source ~/.owl-agent/venv/bin/activate
pip install curl-cffi>=0.10.0
python3 -c "from curl_cffi.requests import AsyncSession; print('✅ JA3 available')"
```

### Phase 4: WebSocket

```bash
source ~/.owl-agent/venv/bin/activate
pip install websockets>=15.0.0
python3 -c "import websockets; print('✅ WebSocket available')"
```

### Phase 5: Browser Automation

```bash
source ~/.owl-agent/venv/bin/activate
pip install playwright>=1.52.0
python3 -m playwright install chromium
python3 -c "from playwright.async_api import async_playwright; print('✅ Browser available')"
```

### All Protocols at Once

```bash
source ~/.owl-agent/venv/bin/activate
pip install 'httpx[http2]>=0.28.0' curl-cffi>=0.10.0 websockets>=15.0.0 playwright>=1.52.0
python3 -m playwright install chromium
```

---

## Post-Install

### Verify All Protocols

```bash
python3 -c "
import sys
sys.path.insert(0, '$HOME/.owl-agent/workspace/projects')
from proxy_defense import HTTP2_AVAILABLE, JA3_AVAILABLE, WS_AVAILABLE, PLAYWRIGHT_AVAILABLE
print(f'  http/1.1: ✅ always')
print(f'  http/2:   {\"✅\" if HTTP2_AVAILABLE else \"⬜\"}')
print(f'  ja3:     {\"✅\" if JA3_AVAILABLE else \"⬜\"}')
print(f'  ws:      {\"✅\" if WS_AVAILABLE else \"⬜\"}')
print(f'  browser: {\"✅\" if PLAYWRIGHT_AVAILABLE else \"⬜\"}')
"
```

### Configure Proxy Pool

```bash
nano ~/.owl-agent/config/proxy_pool.json
```

Add your proxy credentials using the template format.

### CI/CD GitHub Actions Setup

Push to GitHub, and the `protocol-check.yml` workflow automatically runs on PRs:

```bash
cd ~/owl-agent-proxy
git remote add origin https://github.com/YOUR_USER/owl-agent-proxy.git
git push -u origin main
```

---

## Troubleshooting

### Build Failures

| Symptom | Cause | Fix |
|---------|-------|-----|
| `fatal error: Python.h: No such file or directory` | Missing `python3-dev` | `sudo apt install python3-dev` |
| `openssl/ssl.h: No such file or directory` | Missing `libssl-dev` | `sudo apt install libssl-dev` |
| `cffi extension build failed` | Missing build tools | `sudo apt install build-essential libffi-dev` |
| `pip: command not found` | pip not installed | `sudo apt install python3-pip` |

### Runtime Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| `ModuleNotFoundError: No module named 'aiohttp'` | Venv not activated | `source ~/.owl-agent/venv/bin/activate` |
| `Proxy Pool: 0 | Healthy: 0` | No proxy pool file | `cp config/proxy_pool.template.json ~/.owl-agent/config/proxy_pool.json` |
| `Playwright executable not found` | Browser not installed | `python3 -m playwright install chromium` |
| `curl_cffi not available` | JA3 not installed | `pip install curl-cffi` |
| `owl-status: command not found` | Shell not reloaded | `source ~/.bashrc` |

### curl_cffi on Older Ubuntu (20.04)

If `curl-cffi` fails to build from source:

```bash
sudo apt install -y libcurl4-openssl-dev
pip install curl-cffi --no-build-isolation
```

Or install pre-built wheel:

```bash
pip install curl-cffi --only-binary=curl-cffi
```

### Playwright on WSL2

```bash
# WSL2 requires additional dependencies for Chromium
sudo apt install -y libnss3 libnspr4 libatk-bridge2.0-0 libdrm2 libatspi2.0-0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2

# Then install Playwright
pip install playwright
playwright install chromium
```

---

## Uninstall

```bash
# Remove all OWL-AGENT files
rm -rf ~/.owl-agent

# Remove repository
rm -rf ~/owl-agent-proxy

# Remove shell integration (edit ~/.bashrc and delete the OWL-AGENT section)
sed -i '/# ─── 🦉 OWL-AGENT SHELL INTEGRATION/,/# ─── END OWL-AGENT/d' ~/.bashrc

# Remove system packages (if no longer needed)
sudo apt remove -y python3-dev libssl-dev libffi-dev
sudo apt autoremove -y
```

---

## Supported Ubuntu Versions

| Version | Codename | Status |
|---------|----------|--------|
| 24.04 LTS | Noble Numbat | ✅ Tested |
| 22.04 LTS | Jammy Jellyfish | ✅ Tested |
| 20.04 LTS | Focal Fossa | ✅ Tested (curl_cffi may need workaround) |
| 24.10 | Oracular Oriole | ✅ Should work |
| 25.04 | Plucky Puffin | ✅ Should work |

### WSL2

Fully supported on WSL2 with Ubuntu. See [Playwright on WSL2](#playwright-on-wsl2) for browser dependencies.

---

*Build it once → it runs forever.*
