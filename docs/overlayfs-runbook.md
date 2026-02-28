# Musicbox OverlayFS Runbook

This Pi is configured as an appliance:

- Root filesystem uses `overlayroot` in RAM (`tmpfs`) in appliance mode.
- Persistent runtime data lives under `/data`.
- App paths are configured via `/etc/default/musicbox`.

## Modes

- `appliance`: root is overlayed (safe against many abrupt power losses)
- `maintenance`: root is normal writable ext4 (for apt/system changes)

Check current mode:

```bash
musicbox mode get
```

Switch mode (reboot required):

```bash
sudo musicbox mode set appliance --yes --reboot
sudo musicbox mode set maintenance --yes --reboot
```

Dry-run mode change:

```bash
sudo musicbox mode set appliance --dry-run
```

## Health and Diagnostics

Quick status:

```bash
musicbox status
```

Full checks:

```bash
musicbox doctor
musicbox doctor --json
```

Service logs:

```bash
musicbox logs -n 120
musicbox logs -f
```

## Persistent Data Layout

- `/data/media`
- `/data/config`
- `/data/logs`
- `/data/backups`

The app reads these from env vars in `/etc/default/musicbox`:

- `MUSICBOX_MEDIA_DIR`
- `MUSICBOX_CONFIG_DIR`
- `MUSICBOX_LOG_DIR`

## Boot/Mount Notes

Because `/data` and `/mnt/rwroot` are on the same underlying root partition,
a helper service remounts them writable at boot:

- `musicbox-rwdata.service`

Check it:

```bash
systemctl status musicbox-rwdata.service
findmnt /data
findmnt /mnt/rwroot
```

## Backup

Create a cutover backup archive:

```bash
sudo musicbox backup
sudo musicbox backup --json
```

Default path: `/data/backups`.

## Emergency Recovery (if network does not come up)

Disable overlay for next boot by appending `overlayroot=disabled` in
`/boot/firmware/cmdline.txt` on the SD card boot partition.

After recovery boot, remove that token to return to managed mode switching.
