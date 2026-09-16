<!-- Generated from engine/app/data/signals.yaml by
     engine/scripts/gen_signal_docs.py — do not edit by hand. -->

# Signal reference

Every check returns a list of `signals`. Each signal is one fact the
engine found, with the weight it contributed to the score. This page is
what those ids mean.

The same data is served as JSON by `GET /v1/signals` on any instance —
use that if you are generating code or building an agent, since feeds and
weights are per-instance configuration.

## How a decision is built

```
signals → sum of weights (capped at 100) = score
score >= block threshold      → block
score >= challenge threshold  → challenge
otherwise                     → allow
```

Thresholds and weights come from the active policy profile
(`?profile=<name>`, see `GET /v1/profiles`). A profile can override the
weight of a whole category or ignore it entirely; the signals you get
back already reflect that, so the weights in a response are the weights
that actually scored.

Two rules for consuming signals in code:

- **Match on the id prefix and the category, not the full id.** Feed
  signal ids carry an index (`feed:ipsum:0`) that shifts when feeds change.
- **Treat an empty signal list as "nothing known", not as "clean".** A
  score of 0 with confidence 0.2 means no source had anything to say.

## Categories

| Category | Default weight | What it means |
|---|---|---|
| `syntax` | 50 | The address is not a valid mailbox address at all. |
| `disposable` | 40 | Throwaway mailbox provider (10 minute mail and friends). |
| `phishing` | 35 | Domain listed as actively used for phishing. |
| `malware` | 40 | Domain listed as distributing malware. |
| `mx` | 30 | Mail routing of the domain — can mail be delivered at all. |
| `role_account` | 5 | Shared mailbox (info@, support@) rather than a person. |
| `typo` | 10 | One edit away from a large mailbox provider. |
| `abuse` | 15-40 | IP listed for attacks, spam or compromise by a public feed. |
| `anonymizer` | 25 | Tor exit node or commercial VPN egress. |
| `datacenter` | 15 | Hosting/cloud range — no residential user behind it. |
| `free_mail` | 10 | Large free mailbox provider (gmail.com, gmx.de). No feed currently populates this category, so no signal is emitted for it today; the category exists because the newsletter profile ignores it and profiles may override it once a source is wired. **(not emitted by any configured feed today)** |

## Signals

| Signal | Category | Weight | Severity | Source | Checks |
|---|---|---|---|---|---|
| `email:invalid_syntax` | syntax | 50 | high | validator | `/v1/check/email` |
| `email_domain:<category>` | `<from the feed that listed the domain>` | feed weight (disposable 40, malware 40, phishing 35) | high if weight >= 30, else low | comma-separated feed names that listed the domain | `/v1/check/email` |
| `domain:<category>` | `<from the feed that listed the domain>` | feed weight (see above) | high if weight >= 30, else low | comma-separated feed names | `/v1/check/domain` |
| `email:role_account` | role_account | 5 | low | static_list | `/v1/check/email` |
| `email:domain_typo` | typo | 10 | low | static_list | `/v1/check/email` |
| `email:no_mx` | mx | 30 | high | dns | `/v1/check/email` |
| `email:implicit_mx` | mx | 5 | low | dns | `/v1/check/email` |
| `feed:<feed_name>:<n>` | abuse \| anonymizer \| datacenter (from feeds.yaml) | the feed's weight in feeds.yaml (15-40) | high if weight >= 30, else medium | `<feed_name>` | `/v1/check/ip`, `/v1/check/domain`, `/v1/check/email` |

## What each signal means

### `email:invalid_syntax`

The string is not a syntactically valid email address (RFC 5322 via the email-validator library). Deliverability is reported as undeliverable without any DNS lookup.

**What to do with it.** Reject at the form level and show a correction hint. Nothing else in the response is meaningful — no domain was parsed.

**When it is wrong.** Unusual but legal local parts (quoted strings, unicode) are accepted by the validator, so a rejection here is rarely wrong.

### `email_domain:<category>`

Examples: `email_domain:disposable`, `email_domain:phishing`, `email_domain:malware`

The email's domain appears on one or more domain blocklists. One signal per category, never one per feed; the weight is the highest weight among the feeds of that category that listed it, and `source` names all of them.

**What to do with it.** disposable is the usual reason to challenge a signup; malware and phishing on a sender domain are strong block reasons. The feed names in `source` are what you cite when a user disputes the decision.

**When it is wrong.** Disposable lists are broad and include some legitimate privacy forwarders (e.g. relay services). Phishing lists can carry a compromised domain for a while after cleanup.

### `domain:<category>`

Examples: `domain:phishing`, `domain:malware`, `domain:disposable`

Same lookup as email_domain, emitted by the domain check. The different prefix exists so a caller can tell which check produced the signal when results are stored side by side.

**What to do with it.** Use for link/referrer/website checks. Identical semantics to email_domain of the same category.

**When it is wrong.** Same as email_domain.

### `email:role_account`

The local part is a shared mailbox name (info, support, kontakt, sales, …). Not abuse — an attribute of the address.

**What to do with it.** Useful for B2B lead quality, not for blocking. Weight is deliberately small; raise it via a profile weight override if role addresses are worthless to you, or ignore the category entirely for contact forms.

**When it is wrong.** Legitimate in B2B: a purchasing department writing from einkauf@ is normal.

### `email:domain_typo`

The domain is one edit (insert, delete, substitute, adjacent transposition) away from a popular mailbox provider — gamil.com, gmial.com, web.d. Only checked when no blocklist already flagged the domain. The suggestion is in enrichment.did_you_mean.

**What to do with it.** Do not block on this. Show "did you mean gmail.com?" in the form — this is the signal that recovers real customers who mistyped.

**When it is wrong.** A real, small domain that happens to be one edit from a large provider (e.g. gmx.at vs gmx.de) will be flagged.

### `email:no_mx`

The domain has neither MX records nor an A record fallback. Mail to this address cannot be delivered by anyone. Deliverability is set to undeliverable.

**What to do with it.** The strongest cheap signal for a fake address. Worth a challenge on its own at the default threshold; combine with anything else and it blocks.

**When it is wrong.** Transient DNS failures look identical to a missing MX. A resolver timeout on a busy domain will fire this once and not again — do not persist the verdict, re-check.

### `email:implicit_mx`

No MX record, but an A record exists. RFC 5321 says mail may be delivered to the A record host, so this is deliverable in theory but unusual for a domain that accepts mail in practice.

**What to do with it.** A weak hint, not a reason to act alone. Common for small self-hosted domains.

**When it is wrong.** Legitimate single-host mail setups.

### `feed:<feed_name>:<n>`

Examples: `feed:firehol_level2:0`, `feed:tor_exits:0`, `feed:spamhaus_drop:1`

The IP falls inside a range listed by that feed. `<n>` is the index of the match when several ranges cover the same address — it is a disambiguator, not a rank. On the domain check the IP is a resolved A record; on the email check it is an IP of one of the first five MX hosts.

**What to do with it.** Match on the feed name and the category, never on the full id — the index shifts when feeds change. Weights stack: two feeds listing the same IP add up, which is how a well-known bad host reaches block range without any single feed being decisive.

**When it is wrong.** Large NAT ranges and shared hosting mean a listed IP is not necessarily the visitor. anonymizer is a policy question, not an abuse finding: VPN users are ordinary customers in Europe. datacenter on an MX host is expected and meaningless — mail servers live in datacenters.

## Reading the rest of the response

| Field | Meaning |
|---|---|
| `score` | Sum of signal weights, capped at 100 |
| `confidence` | 0.2 with no signals, 0.5 / 0.7 / 0.9 as total weight passes 0 / 30 / 80 — how much evidence there is, not how likely abuse is |
| `evidence` | The same findings as `signals`, keyed by source, for showing a human why |
| `enrichment` | Facts gathered along the way: resolved IPs, MX hosts, `did_you_mean`, deliverability, geo/ASN |
| `action` | Present on `challenge` only: `retry_after_seconds` and a machine-readable `reason` |
| `profile` | The policy profile that produced this decision |
