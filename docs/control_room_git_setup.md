# Control-Room Git Setup

This setup is intentionally local to the repo checkout.

It does not require:

- changing global Git config
- editing `~/.ssh/config`
- adding a GitHub login in a browser

It keeps the SSH key and helper files inside the repo working directory.

## 1. Go To The Repo

```bash
cd ~/path/to/betagui
```

## 2. Create A Repo-Local Key Directory

```bash
mkdir -p .git-local
chmod 700 .git-local
```

## 3. Generate A Repo-Specific Deploy Key

```bash
ssh-keygen -t ed25519 -f .git-local/betagui_control_room -C "betagui-control-room"
chmod 600 .git-local/betagui_control_room
chmod 644 .git-local/betagui_control_room.pub
```

## 4. Show The Public Key

Copy this output:

```bash
cat .git-local/betagui_control_room.pub
```

## 5. Add It To GitHub As A Deploy Key

In `leogrossman/betagui`:

- open `Settings`
- open `Deploy keys`
- click `Add deploy key`
- title: `control-room-machine`
- paste the public key
- enable write access only if this machine should push `control_room_outputs/`

If this machine only needs `git pull`, keep the deploy key read-only.

## 6. Add A Repo-Local SSH Wrapper

Create a small helper script inside the repo:

```bash
cat > .git-local/ssh-betagui <<'EOF'
#!/usr/bin/env bash
exec ssh -i "$(dirname "$0")/betagui_control_room" -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new "$@"
EOF
chmod 700 .git-local/ssh-betagui
```

## 7. Set A Repo-Local Remote URL

```bash
git remote set-url origin git@github.com:leogrossman/betagui.git
```

## 8. Set Repo-Local Git Config Only

This writes to `.git/config` in this checkout only:

```bash
git config core.sshCommand "$PWD/.git-local/ssh-betagui"
```

Check it:

```bash
git config --local --get core.sshCommand
```

## 9. Test SSH And Pull

```bash
$PWD/.git-local/ssh-betagui -T git@github.com
git pull
```

## 10. Push Machine Outputs Back

Only works if the deploy key has write access:

```bash
git add control_room_outputs
git commit -m "Add control-room machine outputs"
git push
```

## 11. Typical Control-Room Workflow

```bash
git pull
python3 control_room/machine_check.py snapshot
python3 control_room/tools/collect_epics_inventory.py
python3 control_room/tools/step_test.py baseline
python3 control_room/betagui.py --safe
python3 control_room/betagui_cli.py --safe
```

After the run:

```bash
git add control_room_outputs
git commit -m "Add control-room outputs"
git push
```

## Notes

- `.git-local/` should stay uncommitted.
- `.betagui_local/` is intentionally gitignored.
- `control_room_outputs/` is intended to be commit-friendly.
- If control-room policy does not allow GitHub write access, use a read-only
  deploy key and move `control_room_outputs/` back manually.
