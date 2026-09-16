/**
 * Client for a monapi engine.
 *
 * Fail-open by design: if the engine is unreachable, misconfigured or
 * slow, every check resolves to `allow` with `checked: false`. A lost
 * real customer costs more than a waved-through bad one at the volumes
 * this is used at — and a form that breaks when a reputation service is
 * down is worse than a form with no reputation check.
 *
 * Callers that need the opposite behaviour read `checked` and decide for
 * themselves; nothing here throws.
 */

export type Decision = "allow" | "challenge" | "block";

export type Deliverability =
  | "deliverable"
  | "undeliverable"
  | "catchall"
  | "unknown";

/** One finding, e.g. `email:no_mx` with the weight it contributed. */
export interface Signal {
  /** Signal id, e.g. "email_domain:disposable". Match on the prefix — feed ids carry a shifting index. */
  id: string;
  /** What the signal is about, e.g. "disposable", "mx", "abuse". Stable; profiles key off this. */
  category: string;
  /** Score contribution after the active profile's overrides. */
  weight: number;
  /** What matched — the domain, the address, the IP. */
  match: string;
  /** Where the fact came from: a feed name, "dns", "validator", "static_list". */
  source: string;
  severity: "low" | "medium" | "high";
}

/** Present on `challenge` only. */
export interface DecisionAction {
  type: string;
  retry_after_seconds: number;
  reason: string;
}

export interface Enrichment {
  domain?: string | null;
  deliverability?: Deliverability;
  is_catchall?: boolean;
  is_role_account?: boolean;
  /** Correction for a mistyped provider domain, e.g. "gmail.com" for "gamil.com". */
  did_you_mean?: string | null;
  mx_hosts?: string[];
  mx_ips?: string[];
  resolved_ips?: string[];
  country?: string;
  country_iso?: string;
  asn?: number;
  asn_organization?: string;
  hostname?: string;
  [key: string]: unknown;
}

export interface CheckResult {
  decision: Decision;
  /** 0-100, the sum of signal weights under the active profile. */
  score: number;
  /** How much evidence there is, not how likely abuse is. 0.2 means nothing was found. */
  confidence: number;
  signals: Signal[];
  enrichment: Enrichment;
  action: DecisionAction | null;
  /** The policy profile that produced this decision. */
  profile: string;
  /**
   * False when the engine could not be reached or is not configured. The
   * decision is then always "allow" and says nothing about the subject.
   */
  checked: boolean;
  /** Why `checked` is false. Never thrown, only reported. */
  error?: string;
  /** The engine's untouched response, for fields this type does not name. */
  raw?: Record<string, unknown>;
}

export interface MonapiOptions {
  /** Engine base URL. Default: MONAPI_URL, else https://api.monapi.io */
  baseUrl?: string;
  /** API key. Default: MONAPI_API_KEY. Without one, every check is a no-op. */
  apiKey?: string;
  /** Policy profile. Default: MONAPI_PROFILE, else "default". */
  profile?: string;
  /** Milliseconds before giving up and allowing. Default: 2000. */
  timeoutMs?: number;
  /** Called when a check could not run. Default: console.warn. Pass a no-op to silence. */
  onError?: (message: string, cause?: unknown) => void;
  /** Injected for tests. Default: global fetch. */
  fetch?: typeof fetch;
}

const DEFAULT_BASE_URL = "https://api.monapi.io";
const DEFAULT_TIMEOUT_MS = 2000;
const DECISIONS: ReadonlySet<string> = new Set(["allow", "challenge", "block"]);

function env(name: string): string | undefined {
  // Guarded so the package also loads in a browser or edge runtime.
  return typeof process !== "undefined" ? process.env?.[name] : undefined;
}

function unchecked(profile: string, error?: string): CheckResult {
  return {
    decision: "allow",
    score: 0,
    confidence: 0,
    signals: [],
    enrichment: {},
    action: null,
    profile,
    checked: false,
    ...(error ? { error } : {}),
  };
}

export class MonapiClient {
  private readonly baseUrl: string;
  private readonly apiKey: string;
  private readonly profile: string;
  private readonly timeoutMs: number;
  private readonly onError: (message: string, cause?: unknown) => void;
  private readonly fetchImpl: typeof fetch;

  constructor(options: MonapiOptions = {}) {
    this.baseUrl = (
      options.baseUrl ??
      env("MONAPI_URL") ??
      DEFAULT_BASE_URL
    ).replace(/\/+$/, "");
    this.apiKey = options.apiKey ?? env("MONAPI_API_KEY") ?? "";
    this.profile = options.profile ?? env("MONAPI_PROFILE") ?? "default";
    this.timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    this.onError =
      options.onError ??
      ((message, cause) => console.warn(`[monapi] ${message}`, cause ?? ""));
    this.fetchImpl = options.fetch ?? globalThis.fetch;
  }

  /** True when an API key is configured. Without one, checks are no-ops. */
  get isConfigured(): boolean {
    return Boolean(this.apiKey);
  }

  /**
   * Judge an email address. Covers disposable domains, mail routing,
   * the reputation of the mail servers, role accounts and typos.
   */
  async checkEmail(email: string, profile?: string): Promise<CheckResult> {
    return this.check("email", email, profile);
  }

  /** Judge an IP address against abuse, VPN/Tor and datacenter feeds. */
  async checkIp(ip: string, profile?: string): Promise<CheckResult> {
    return this.check("ip", ip, profile);
  }

  /** Judge a domain: blocklists plus the reputation of where it resolves. */
  async checkDomain(domain: string, profile?: string): Promise<CheckResult> {
    return this.check("domain", domain, profile);
  }

  private async check(
    kind: "email" | "ip" | "domain",
    value: string,
    profileOverride?: string,
  ): Promise<CheckResult> {
    const profile = profileOverride ?? this.profile;

    if (!this.apiKey) {
      return unchecked(profile, "no API key configured");
    }
    if (!value) {
      return unchecked(profile, "nothing to check");
    }
    if (typeof this.fetchImpl !== "function") {
      return unchecked(profile, "no fetch implementation available");
    }

    const url =
      `${this.baseUrl}/v1/check/${kind}/${encodeURIComponent(value)}` +
      `?profile=${encodeURIComponent(profile)}`;

    // AbortSignal.timeout is not everywhere yet; an explicit controller
    // works on every runtime that has fetch at all.
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);

    try {
      const response = await this.fetchImpl(url, {
        headers: { "X-API-Key": this.apiKey, Accept: "application/json" },
        signal: controller.signal,
        cache: "no-store",
      });

      if (!response.ok) {
        const reason = `engine answered ${response.status}`;
        this.onError(reason);
        return unchecked(profile, reason);
      }

      const data = (await response.json()) as Record<string, unknown>;
      const decision = data.decision;

      if (typeof decision !== "string" || !DECISIONS.has(decision)) {
        const reason = "engine returned no usable decision";
        this.onError(reason);
        return unchecked(profile, reason);
      }

      return {
        decision: decision as Decision,
        score: typeof data.score === "number" ? data.score : 0,
        confidence: typeof data.confidence === "number" ? data.confidence : 0,
        signals: Array.isArray(data.signals) ? (data.signals as Signal[]) : [],
        enrichment:
          data.enrichment && typeof data.enrichment === "object"
            ? (data.enrichment as Enrichment)
            : {},
        action: (data.action as DecisionAction | null) ?? null,
        profile: typeof data.profile === "string" ? data.profile : profile,
        checked: true,
        raw: data,
      };
    } catch (cause) {
      // Timeout, DNS, TLS, abort — one case: decide without monapi.
      const aborted = cause instanceof Error && cause.name === "AbortError";
      const reason = aborted
        ? `engine did not answer within ${this.timeoutMs}ms`
        : "engine unreachable";
      this.onError(reason, aborted ? undefined : cause);
      return unchecked(profile, reason);
    } finally {
      clearTimeout(timer);
    }
  }
}

/** One-line summary for a log line, an admin email or a lead record. */
export function summarize(result: CheckResult): string {
  if (!result.checked) {
    return `not checked (${result.error ?? "unavailable"})`;
  }

  const parts = [`${result.decision}, score ${result.score}`];
  const deliverability = result.enrichment.deliverability;
  if (deliverability && deliverability !== "unknown") {
    parts.push(deliverability);
  }
  if (result.signals.length) {
    parts.push(result.signals.map((s) => s.id).join(", "));
  }
  return parts.join(" — ");
}

/** True when a signal of that category is present, e.g. hasCategory(r, "disposable"). */
export function hasCategory(result: CheckResult, category: string): boolean {
  return result.signals.some((s) => s.category === category);
}

/** True when a signal id starts with that prefix, e.g. hasSignal(r, "feed:"). */
export function hasSignal(result: CheckResult, idPrefix: string): boolean {
  return result.signals.some((s) => s.id.startsWith(idPrefix));
}

let shared: MonapiClient | undefined;

/**
 * Process-wide client configured from the environment. Convenient for a
 * route handler that has no place to keep an instance.
 */
export function monapi(): MonapiClient {
  if (!shared) shared = new MonapiClient();
  return shared;
}

/** Shorthand for `monapi().checkEmail(email)`. */
export async function checkEmail(
  email: string,
  profile?: string,
): Promise<CheckResult> {
  return monapi().checkEmail(email, profile);
}
