import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  MonapiClient,
  hasCategory,
  hasSignal,
  summarize,
  type CheckResult,
} from "../src/index.ts";

const BLOCKED = {
  profile: "default",
  decision: "block",
  score: 80,
  confidence: 0.9,
  action: null,
  signals: [
    {
      id: "email_domain:disposable",
      category: "disposable",
      weight: 40,
      match: "mailinator.com",
      source: "disposable_ivolo",
      severity: "high",
    },
  ],
  enrichment: { domain: "mailinator.com", deliverability: "undeliverable" },
};

/** A fetch that answers with `payload` and records what it was asked. */
function fakeFetch(payload: unknown, init: { status?: number } = {}) {
  const calls: string[] = [];
  const impl = (async (url: string | URL) => {
    calls.push(String(url));
    return new Response(JSON.stringify(payload), {
      status: init.status ?? 200,
      headers: { "content-type": "application/json" },
    });
  }) as unknown as typeof fetch;
  return { impl, calls };
}

function client(fetchImpl: typeof fetch, options = {}) {
  return new MonapiClient({
    baseUrl: "http://engine.test",
    apiKey: "k",
    fetch: fetchImpl,
    onError: () => {},
    ...options,
  });
}

describe("checkEmail", () => {
  it("maps a block response", async () => {
    const { impl } = fakeFetch(BLOCKED);
    const result = await client(impl).checkEmail("a@mailinator.com");

    assert.equal(result.decision, "block");
    assert.equal(result.score, 80);
    assert.equal(result.checked, true);
    assert.equal(result.signals[0]?.id, "email_domain:disposable");
    assert.equal(result.enrichment.deliverability, "undeliverable");
  });

  it("encodes the address and passes the profile", async () => {
    const { impl, calls } = fakeFetch(BLOCKED);
    await client(impl).checkEmail("a+tag@example.com", "checkout");

    assert.match(calls[0]!, /a%2Btag%40example\.com/);
    assert.match(calls[0]!, /profile=checkout/);
  });

  it("strips a trailing slash from the base URL", async () => {
    const { impl, calls } = fakeFetch(BLOCKED);
    await client(impl, { baseUrl: "http://engine.test/" }).checkEmail("a@b.de");

    assert.match(calls[0]!, /^http:\/\/engine\.test\/v1\/check\/email\//);
  });
});

describe("fail-open", () => {
  it("allows when no API key is configured", async () => {
    const { impl, calls } = fakeFetch(BLOCKED);
    const result = await new MonapiClient({
      baseUrl: "http://engine.test",
      apiKey: "",
      fetch: impl,
    }).checkEmail("a@mailinator.com");

    assert.equal(result.decision, "allow");
    assert.equal(result.checked, false);
    assert.equal(result.error, "no API key configured");
    assert.equal(calls.length, 0, "must not call the engine without a key");
  });

  it("allows when the engine errors", async () => {
    const { impl } = fakeFetch({ detail: "nope" }, { status: 500 });
    const result = await client(impl).checkEmail("a@mailinator.com");

    assert.equal(result.decision, "allow");
    assert.equal(result.checked, false);
    assert.match(result.error!, /500/);
  });

  it("allows when the engine is unreachable", async () => {
    const impl = (async () => {
      throw new TypeError("fetch failed");
    }) as unknown as typeof fetch;
    const result = await client(impl).checkEmail("a@mailinator.com");

    assert.equal(result.decision, "allow");
    assert.equal(result.checked, false);
    assert.equal(result.error, "engine unreachable");
  });

  it("allows and reports when the engine is too slow", async () => {
    const impl = ((_url: string, init?: RequestInit) =>
      new Promise((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => {
          const error = new Error("aborted");
          error.name = "AbortError";
          reject(error);
        });
      })) as unknown as typeof fetch;

    const result = await client(impl, { timeoutMs: 20 }).checkEmail("a@b.de");

    assert.equal(result.decision, "allow");
    assert.equal(result.checked, false);
    assert.match(result.error!, /within 20ms/);
  });

  it("allows when the response has no usable decision", async () => {
    const { impl } = fakeFetch({ decision: "maybe", score: 99 });
    const result = await client(impl).checkEmail("a@b.de");

    assert.equal(result.decision, "allow");
    assert.equal(result.checked, false);
  });

  it("allows on an empty value without calling the engine", async () => {
    const { impl, calls } = fakeFetch(BLOCKED);
    const result = await client(impl).checkEmail("");

    assert.equal(result.checked, false);
    assert.equal(calls.length, 0);
  });

  it("reports the failure once through onError", async () => {
    const { impl } = fakeFetch({}, { status: 503 });
    const seen: string[] = [];
    await client(impl, { onError: (m: string) => seen.push(m) }).checkEmail("a@b.de");

    assert.deepEqual(seen, ["engine answered 503"]);
  });
});

describe("ip and domain", () => {
  it("hits the ip route", async () => {
    const { impl, calls } = fakeFetch({ ...BLOCKED, decision: "challenge" });
    const result = await client(impl).checkIp("185.1.1.1");

    assert.match(calls[0]!, /\/v1\/check\/ip\/185\.1\.1\.1/);
    assert.equal(result.decision, "challenge");
  });

  it("hits the domain route", async () => {
    const { impl, calls } = fakeFetch({ ...BLOCKED, decision: "allow" });
    await client(impl).checkDomain("example.com");

    assert.match(calls[0]!, /\/v1\/check\/domain\/example\.com/);
  });
});

describe("helpers", () => {
  const blocked = {
    decision: "block",
    score: 80,
    confidence: 0.9,
    signals: BLOCKED.signals,
    enrichment: { deliverability: "undeliverable" },
    action: null,
    profile: "default",
    checked: true,
  } as CheckResult;

  it("summarizes a checked result", () => {
    assert.equal(
      summarize(blocked),
      "block, score 80 — undeliverable — email_domain:disposable",
    );
  });

  it("summarizes an unchecked result as such", () => {
    const result = { ...blocked, checked: false, error: "engine unreachable" };
    assert.equal(summarize(result), "not checked (engine unreachable)");
  });

  it("omits unknown deliverability", () => {
    const result = { ...blocked, enrichment: { deliverability: "unknown" } } as CheckResult;
    assert.equal(summarize(result), "block, score 80 — email_domain:disposable");
  });

  it("finds categories and id prefixes", () => {
    assert.equal(hasCategory(blocked, "disposable"), true);
    assert.equal(hasCategory(blocked, "abuse"), false);
    assert.equal(hasSignal(blocked, "email_domain:"), true);
    assert.equal(hasSignal(blocked, "feed:"), false);
  });
});
