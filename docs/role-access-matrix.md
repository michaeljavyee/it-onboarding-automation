# Role-to-access matrix

The authoritative statement of what each role gets. `config/roles.yml` is the
machine-readable form of this table and is what the tooling reads; if the two
disagree, this document is the one that's wrong and needs updating.

## The environment being modelled

Northwind Labs — a fictional 50-person B2B SaaS company. Remote-first, US and
EU, all-macOS fleet. Roughly 25 engineering, 12 go-to-market, 6 finance and ops,
7 contractors at any given time.

| Layer | Choice |
|---|---|
| HR system (source of truth for identity) | BambooHR |
| Identity provider | Okta |
| Directory / email | Google Workspace |
| Device management | see `mdm/` — baselines as code, MDM-agnostic |
| Ticketing | Jira Service Management |

**Source of truth is BambooHR, not Okta.** A person exists because HR says they
were hired, not because someone created an account. Okta is downstream. This
matters for the leaver flow: the termination date comes from HR, and if the two
systems disagree, HR wins.

## The matrix

| | Engineer | Sales | Finance | Contractor |
|---|---|---|---|---|
| **Okta group** | `eng-all` | `sales-all` | `finance-all` | `contractors` |
| Google Workspace | ✅ | ✅ | ✅ | ✅ no external Drive sharing |
| Slack | ✅ member | ✅ member | ✅ member | ✅ single-channel guest |
| GitHub | ✅ write | ❌ | ❌ | ✅ read, time-boxed |
| AWS | ✅ dev full, prod read-only | ❌ | ❌ | ❌ |
| Salesforce | ❌ | ✅ standard | ✅ read-only | ❌ |
| NetSuite | ❌ | ❌ | ✅ | ❌ |
| Zoom | ✅ licensed | ✅ licensed | ✅ licensed | ❌ |
| Datadog | ✅ | ❌ | ❌ | ❌ |
| **MDM profile** | `eng-baseline`<br>FileVault, firewall, dev tools allowed | `standard` | `finance-hardened`<br>no USB mass storage | `contractor`<br>BYOD, app-level controls only |
| **Hardware** | MacBook Pro 16" | MacBook Pro 14" | MacBook Pro 14" | BYOD |
| **Access expiry** | — | — | — | **90 days, auto-suspend** |

Everyone additionally lands in `everyone` and `okta-mfa-required`. Those are
assigned by rule, not by role, so a misconfigured role can never produce an
account without MFA.

## Which of these can Okta actually deprovision?

The distinction that makes or breaks offboarding. SCIM-managed apps drop the
user when their group membership is removed. The rest do not, and nothing in
Okta will tell you they didn't.

| App | SCIM-provisioned | Removal on offboard |
|---|---|---|
| Google Workspace | ✅ | automatic |
| Slack (members) | ✅ | automatic |
| GitHub | ✅ | automatic |
| Salesforce | ✅ | automatic |
| NetSuite | ✅ | automatic |
| **Zoom** | ❌ | **manual** |
| **AWS** | ❌ | **manual** — permission sets assigned directly |
| **Slack single-channel guests** | ❌ | **manual** — guest accounts sit outside SCIM |
| **Datadog** | ❌ | **manual** |

`offboard.py` reads the `non_scim_apps` list in `config/roles.yml` and puts
anything on it into the manual-action section of the report rather than assuming
group removal handled it.

## Notes on two rows people skip

**Contractors.** Most access matrices only cover employees, which is backwards —
contractors are the larger hygiene problem. They arrive through a different path
(no HR record, sometimes no manager, occasionally no one who remembers
sponsoring them), they use BYOD so there's no device to reclaim, and their end
date is a project milestone rather than a termination notice. Giving them a
column forces the question "and how does this one end?" to be answered up front.

**Access expiry.** Contractor accounts carry a 90-day expiry with auto-suspend,
renewable by the sponsoring manager. The renewal is the useful half: it converts
"does this contractor still need GitHub?" from a question nobody asks into a
question the system asks on a schedule. Suspend rather than delete, so a renewal
that arrives late is a two-minute fix rather than a re-onboarding.

## Review cadence

| What | How often | Who |
|---|---|---|
| Full access review (`access_review.py` export) | quarterly | IT + each department head |
| Contractor renewals | continuous, triggered at day 76 (14 days' notice) | sponsoring manager |
| Admin role holders | monthly | IT lead |
| This matrix | on any new app rollout, and quarterly regardless | IT lead |
