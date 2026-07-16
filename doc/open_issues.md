# Open issues

Small, deliberate gaps that are decided-and-parked rather than forgotten. Each entry: what's missing, why it's acceptable for now, and what would change that.

## Remote-access checkbox doesn't open a Windows Firewall rule (2026-07-16)
The Windows installer's remote-access checkbox sets `SYLO_WEB_BIND_HOST=0.0.0.0` so other machines on the network can reach the web UI. It deliberately does **not** also create a Windows Firewall inbound rule for the configured port.

Decided this way because: Windows itself already prompts on the first inbound connection to a newly-listening process (the standard "Windows Defender Firewall has blocked some features of this app" dialog), and adding a rule automatically would be a second, less visible system change bundled into one checkbox. Deployers who want it open without that prompt can add an inbound rule for the configured port themselves (`New-NetFirewallRule` or the Windows Firewall UI).

Revisit if: remote viewing becomes the common case rather than the exception, or support requests show people getting stuck on the firewall prompt.
