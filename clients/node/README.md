# @monapi/client

Client for a [monapi](https://github.com/dplusf/monapi-engine) engine:
**allow**, **challenge** or **block** for an email address, IP or domain,
with the signals behind the verdict.

Zero dependencies, works on Node 18+, Next.js route handlers, edge
runtimes and workers. TypeScript types included.

## Install

```bash
npm install @monapi/client
```

## Use

```ts
import { checkEmail, summarize } from "@monapi/client";

const result = await checkEmail("kontakt@gamil.com");

result.decision; // "allow" | "challenge" | "block"
result.score; // 0-100
result.signals; // [{ id: "email:domain_typo", category: "typo", weight: 10, ... }]
result.enrichment.did_you_mean; // "gmail.com"

summarize(result); // "allow, score 15 — email:role_account, email:domain_typo"
```

Configuration comes from the environment:

| Variable | Default | Meaning |
|---|---|---|
| `MONAPI_URL` | `https://api.monapi.io` | Engine base URL — point at your own instance |
| `MONAPI_API_KEY` | — | Without one, every check is a no-op that allows |
| `MONAPI_PROFILE` | `default` | Policy profile applied when a call does not name one |

Or explicitly, when you need more than one engine or profile:

```ts
import { MonapiClient } from "@monapi/client";

const strict = new MonapiClient({
  baseUrl: "http://localhost:18000",
  apiKey: process.env.MONAPI_API_KEY,
  profile: "checkout",
  timeoutMs: 1500,
});

await strict.checkIp(request.headers.get("x-forwarded-for") ?? "");
await strict.checkDomain("example.com");
```

## Fail-open, by design

If the engine is unreachable, slow, or no API key is set, the check
resolves to `allow` with `checked: false` — it never throws, and a form
never breaks because a reputation service is down.

```ts
const result = await checkEmail(email);

if (!result.checked) {
  // The engine said nothing. Decide without it.
} else if (result.decision === "block") {
  return reject("Please use a permanent email address.");
} else if (result.enrichment.did_you_mean) {
  return suggest(`Did you mean ${result.enrichment.did_you_mean}?`);
}
```

Set `timeoutMs` to the longest you are willing to make a user wait —
2000ms by default. To fail *closed* instead, treat `checked: false` as a
rejection yourself; the flag exists so that choice stays yours.

Failures are reported through `onError` (default: `console.warn`). Pass
`onError: () => {}` to silence it, or route it into your logger.

## In a Next.js route handler

```ts
// app/api/contact/route.ts
import { checkEmail } from "@monapi/client";

export async function POST(request: Request) {
  const { email, message } = await request.json();
  const verdict = await checkEmail(email);

  if (verdict.decision === "block") {
    return Response.json({ error: "invalid_email" }, { status: 422 });
  }

  await store({ email, message, reputation: summarize(verdict) });
  return Response.json({ ok: true });
}
```

Keep the API key server-side. This package is meant for route handlers,
server actions and backends — not the browser.

## Reading signals

```ts
import { hasCategory, hasSignal } from "@monapi/client";

hasCategory(result, "disposable"); // throwaway mailbox provider
hasSignal(result, "feed:"); // any IP feed listed the address
```

Match on `category`, or on an id *prefix* — feed signal ids carry an
index (`feed:ipsum:0`) that shifts when feeds change. Every id is
documented in the [signal
reference](https://github.com/dplusf/monapi-engine/blob/main/docs/signals.md),
and served as JSON by `GET /v1/signals` on any instance.

An empty `signals` array means no source had anything to say — an absence
of evidence, not a clean bill of health.

## API

| Export | What it does |
|---|---|
| `MonapiClient` | Configurable client: `checkEmail`, `checkIp`, `checkDomain`, `isConfigured` |
| `checkEmail(email, profile?)` | Shorthand on a process-wide client from the environment |
| `monapi()` | That shared client, if you want the other methods |
| `summarize(result)` | One line for a log, an admin email or a lead record |
| `hasCategory(result, category)` / `hasSignal(result, idPrefix)` | Predicates over the signals |

Types: `CheckResult`, `Decision`, `Signal`, `Enrichment`,
`DecisionAction`, `MonapiOptions`, `Deliverability`.

## Development

```bash
npm install
npm test        # node --test
npm run build
```

MIT.
