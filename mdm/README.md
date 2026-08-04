# Device baselines as code

> **Status:** approach documented, scripts to follow. Listed in the repo status
> as not-yet-built rather than quietly implied. See decision log #6.

This directory defines device security baselines as code rather than as MDM
console screenshots. The policies map to configuration profiles deployable via
Jamf, Kandji, or Intune; `check_compliance.sh` will verify the resulting state
*independently of whichever MDM applied it*.

That independence is the argument. **MDM reporting tells you a profile was
delivered, not that it is currently effective.** A user with admin rights can
turn off the firewall after the profile lands, and plenty of MDM dashboards
will keep showing green. Reading live system state answers the question the
dashboard only appears to.

It is the same principle as `offboard.py`'s verification stage, applied to
endpoints instead of identity: verify, don't assume.

## Planned structure

```
mdm/
├── README.md                       ← this file
├── baselines/
│   ├── macos-standard.md           ← the policy, in plain language
│   ├── macos-engineering.md        ← + dev tooling exceptions
│   └── macos-finance-hardened.md   ← + no USB mass storage
├── scripts/
│   ├── apply_baseline.sh           ← what an MDM would push
│   └── check_compliance.sh         ← reads current state, reports drift
└── profiles/
    └── com.northwind.security.mobileconfig
```

## What `check_compliance.sh` will check

Each of these reads real system state on a Mac and reports pass/fail:

| Control | Source of truth |
|---|---|
| FileVault enabled | `fdesetup status` |
| Firewall on | `socketfilterfw --getglobalstate` |
| Gatekeeper on | `spctl --status` |
| Screen lock ≤ 5 min | `sysadminctl -screenLock status` |
| SIP enabled | `csrutil status` |
| Automatic updates on | `softwareupdate --schedule` |
| Guest account off | `defaults read /Library/Preferences/com.apple.loginwindow GuestEnabled` |

Exit non-zero on any failure, same as `offboard.py` — a compliance check that
always exits 0 is decoration.
