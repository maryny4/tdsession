#!/bin/bash
set -e

WEB_PORT="${WEB_PORT:-6160}"
VNC_RES="${VNC_RESOLUTION:-1920x1080}"
VNC_W="${VNC_RES%x*}"
VNC_H="${VNC_RES#*x}"

# Runtime dirs
mkdir -p /tmp/runtime-root
chmod 700 /tmp/runtime-root

# Shared folder — appears as bookmark in GTK file dialogs (sidebar)
mkdir -p /app/shared /root/.config/gtk-3.0
echo "file:///app/shared Shared" > /root/.config/gtk-3.0/bookmarks

# ── KasmVNC setup ──
mkdir -p ~/.vnc

# xstartup — KasmVNC calls this when display starts
cat > ~/.vnc/xstartup << 'XEOF'
#!/bin/sh
mkdir -p ~/.fluxbox
cat > ~/.fluxbox/apps << 'FBEOF'
[app] (name=.*)
  [Maximized] {yes}
  [Deco] {NONE}
[end]
FBEOF
cat > ~/.fluxbox/init << 'FBEOF'
session.screen0.toolbar.visible: false
session.screen0.slit.autoHide: true
FBEOF
exec dbus-launch --exit-with-session fluxbox
XEOF
chmod +x ~/.vnc/xstartup

# System-level KasmVNC config (shared by all sessions)
mkdir -p /etc/kasmvnc
cat > /etc/kasmvnc/kasmvnc.yaml << EOF
desktop:
  resolution:
    width: ${VNC_W}
    height: ${VNC_H}
  allow_resize: true
  pixel_depth: 24

network:
  protocol: http
  interface: 127.0.0.1
  use_ipv4: true
  use_ipv6: false
  ssl:
    require_ssl: false
    pem_certificate:
    pem_key:

data_loss_prevention:
  clipboard:
    delay_between_operations: none
    server_to_client:
      enabled: true
      size: unlimited
    client_to_server:
      enabled: true
      size: unlimited

command_line:
  prompt: false
EOF
cp /etc/kasmvnc/kasmvnc.yaml ~/.vnc/kasmvnc.yaml

# Ensure root is in ssl-cert group
adduser root ssl-cert 2>/dev/null || true

echo "=== tdsession ready ==="
echo "  Web UI: http://0.0.0.0:${WEB_PORT}"

# Start FastAPI (foreground — keeps container alive)
exec uvicorn backend.app:app --host 0.0.0.0 --port "${WEB_PORT}"
