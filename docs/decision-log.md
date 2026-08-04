# Decision log

Where a real choice existed, what was chosen, and what was given up. Written
because the tradeoff is the interesting part — anyone can pick an option.

---

## 1. Account creation happens 1 business day before start, not at offer signature

**Options.** Create on offer acceptance (often 2–6 weeks ahead); create the
evening before the start date; create on day one.

**Chosen.** The evening before, in `STAGED` state, activated on the morning of
day one.

**Why.** Creating at offer acceptance means a live credential exists for
someone who is not yet an employee, has signed no acceptable-use policy, and
in maybe 3–5% of cases never shows up. That account sits in the tenant with
group memberships attached and nobody watching it. Creating on day one means IT
is doing setup while a new hire watches, which is a bad first day and a
guaranteed source of ad-hoc, undocumented shortcuts.

Okta's `STAGED` status is what makes the middle option work: the account, its
groups, and its app assignments all exist and can be reviewed, but no
credential is active and no welcome email has gone out. Provisioning becomes a
verifiable overnight batch; activation becomes a single click at 09:00.

**Given up.** Anything needing lead time longer than a day — hardware shipping,
a Salesforce licence with a procurement step — has to be tracked outside the
account lifecycle. Those live in the manual runbook with their own lead times.

---

## 2. Group-based assignment only. No individual app assignments.

**Options.** Assign apps to users directly; assign via groups; hybrid.

**Chosen.** Groups only. If someone needs an app, they need the group that
grants it, and if no group fits, a new group gets created and documented.

**Why.** Direct assignments are invisible to the mover flow. The transfer diff
is computed from group membership; an app attached straight to a user won't
appear in it and will survive a department change indefinitely. They're also
invisible to a quarterly access review that reads group membership, which is
how a five-year employee ends up with access nobody can explain.

**Given up.** Genuine speed. "Just give Sam access to Figma for this one
project" is a 30-second job with a direct assignment and a 10-minute job with a
new group. Ten minutes is the price of the access being reviewable, and I'd
rather pay it. The escape hatch is documented: direct assignment is permitted
for break-glass, must carry an expiry, and gets flagged in the next access
review.

---

## 3. Non-SCIM apps are reported, not automated

**Options.** Build API integrations for Zoom, Datadog, and AWS so offboarding is
fully automated; or detect and report them for a human to handle.

**Chosen.** Report them. `config/roles.yml` lists `non_scim_apps` and
`offboard.py` puts anything on that list into the manual-action section of the
report, with the process exiting non-zero until they're cleared.

**Why.** At 50 people, that's roughly four leavers a month and maybe twelve
manual removals. Automating them means three more API integrations, three more
stored credentials with write access to three more systems, and three more
things that break silently when a vendor changes their API. The failure mode of
"we automated it and it quietly stopped working" is considerably worse than
"the report tells a human to go do it," because the first one looks like
success.

**Given up.** A fully hands-off offboard. Accepted deliberately — the tool's
job is to make the remaining manual work *explicit and impossible to forget*,
not to eliminate it by pretending. Revisit at roughly 150 people, when the
volume justifies the maintenance.

---

## 4. The tool verifies rather than trusting its own return codes

**Options.** Treat HTTP 200 from each write as proof the step worked; or re-query
everything afterwards.

**Chosen.** Re-query, in a phase that shares no state with the action phase.

**Why.** Most of the interesting failures here return 200. Removing a user from
a group succeeds whether or not that group was what granted the app. Suspension
succeeds whether or not a refresh token is still live. Deleting an account
succeeds while an API token that account created keeps working. In every case
the API did exactly what it was asked; the request just wasn't sufficient for
the outcome. Return codes describe the request, and I care about the state.

**Given up.** Roughly double the API calls per offboard, and a slower run.
Irrelevant at four leavers a month.

**Corollary.** The tool exits non-zero when anything remains, so it cannot be
wired into a pipeline that treats it as complete when it isn't.

---

## 5. Same-day deprovisioning for involuntary departures, end-of-day for voluntary

**Options.** Uniform same-day for everyone; uniform end-of-day; split by
departure type.

**Chosen.** Split. Involuntary is immediate — ideally initiated before the
conversation finishes. Voluntary runs at 17:00 on the last working day.

**Why.** These are different risk profiles and treating them the same
over-serves one and under-serves the other. Cutting a resigning engineer's
access at 09:00 on their last day costs you the handover and makes the process
adversarial for someone likely to be a reference or a boomerang hire. Waiting
until end of day on an involuntary termination is how data leaves the building.

**Given up.** Uniformity, and with it a simpler runbook. The tool takes the
departure type as an input and the human running it makes the call, because
the judgement about which path applies is not one a script should make.

---

## 6. Device baselines as code rather than an MDM trial

**Options.** Enrol in a Jamf Now / Kandji / Intune trial and screenshot the
console; or define baselines as configuration-as-code with an independent
compliance check.

**Chosen.** Configuration-as-code. See `mdm/`.

**Why.** A trial expires in 14 days and leaves a portfolio piece that's a dated
screenshot of a product I no longer have. More substantively: MDM reporting
tells you a profile was *delivered*, not that it is currently *effective*. A
user with admin rights can disable the firewall after the profile lands, and
plenty of MDM dashboards will still show green. An independent compliance check
that reads live system state answers the question the dashboard only appears to.

This is the same principle as decision 4, applied to endpoints instead of
identity, and I'd rather the portfolio have a point of view than a pile of
tools.

**Given up.** Enforcement. Config-as-code describes and verifies; it does not
push. The policies map to profiles deployable via Jamf, Kandji, or Intune, and
in a real environment one of those would do the pushing while
`check_compliance.sh` keeps checking the result.
