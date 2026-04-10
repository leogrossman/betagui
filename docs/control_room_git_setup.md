# Control-Room Git Setup

Use an SSH deploy key that is restricted to this repository.

This avoids browser login on the control-room machine and keeps the access scope
as small as possible.

## 1. Generate A Repo-Specific SSH Key

Run this on the control-room machine:

```bash
mkdir -p ~/.ssh
chmod 700 ~/.ssh
ssh-keygen -t ed25519 -f ~/.ssh/betagui_control_room -C "betagui-control-room"
chmod 600 ~/.ssh/betagui_control_room
chmod 644 ~/.ssh/betagui_control_room.pub
```

## 2. Show The Public Key

Copy this output:

```bash
cat ~/.ssh/betagui_control_room.pub
```

## 3. Add It To GitHub As A Deploy Key

In the GitHub repository:

- open `Settings`
- open `Deploy keys`
- click `Add deploy key`
- title: `control-room-machine`
- paste the public key
- enable write access only if you want to push `control_room_outputs/` from the machine

If you only need `git pull`, leave write access disabled.

## 4. Add A Small SSH Config Entry

Run this on the control-room machine:

```bash
cat >> ~/.ssh/config <<'EOF'
Host github-betagui
    HostName github.com
    User git
    IdentityFile ~/.ssh/betagui_control_room
    IdentitiesOnly yes
EOF
chmod 600 ~/.ssh/config
```

## 5. Clone Or Repoint The Repo

Fresh clone:

```bash
git clone git@github-betagui:leogrossman/betagui.git
cd betagui
```

Existing checkout:

```bash
git remote set-url origin git@github-betagui:leogrossman/betagui.git
```

## 6. Test SSH And Pull

```bash
ssh -T git@github-betagui
git pull
```

## 7. Push Machine Outputs Back

Only works if the deploy key was added with write access.

```bash
git add control_room_outputs
git commit -m "Add control-room machine outputs"
git push
```

## 8. Typical Control-Room Workflow

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

- `betagui_logs/` is intentionally gitignored.
- `control_room_outputs/` is intended to be commit-friendly.
- If control-room policy does not allow write access to GitHub, use a read-only
  deploy key and move `control_room_outputs/` back manually.
