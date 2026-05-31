# Deploy — service units (R6 cross-platform)

Run the Lighthouse supervisor as a per-user background service. Both units run as
**you**, not root: research data stays under your home (`~/.lighthouse`) and the
supervisor binds `127.0.0.1:8765` only.

## Linux (systemd user service)

```bash
mkdir -p ~/.config/systemd/user
cp deploy/lighthouse.service ~/.config/systemd/user/lighthouse.service
# edit MemoryMax / LIGHTHOUSE_REAL_BACKEND to taste
systemctl --user daemon-reload
systemctl --user enable --now lighthouse.service
loginctl enable-linger "$USER"        # keep it running after logout
systemctl --user status lighthouse.service
journalctl --user -u lighthouse.service -f   # logs
```

## macOS (launchd LaunchAgent)

```bash
sed "s/USERNAME/$USER/g" deploy/com.lighthouse.supervisor.plist \
  > ~/Library/LaunchAgents/com.lighthouse.supervisor.plist
launchctl load  ~/Library/LaunchAgents/com.lighthouse.supervisor.plist
launchctl list | grep lighthouse
# logs: ~/.lighthouse/logs/launchd.{out,err}.log ; unload: launchctl unload <plist>
```

## Verify

```bash
curl -s http://127.0.0.1:8765/api/health   # -> 200
open http://127.0.0.1:8765                  # dashboard (macOS); xdg-open on Linux
```

Both restart on failure. The systemd unit caps memory (`MemoryMax`) so a runaway
never swaps the box — match it to your hardware (≈ 75% of RAM). See
[`docs/RELEASE.md`](../docs/RELEASE.md) for the full release-readiness runbook.
