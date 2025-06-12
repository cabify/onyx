import { cookies, headers } from "next/headers";
import { HOST_URL, INTERNAL_URL } from "./constants";

export function buildClientUrl(path: string) {
  if (path.startsWith("/")) {
    return `${HOST_URL}${path}`;
  }
  return `${HOST_URL}/${path}`;
}

export function buildUrl(path: string) {
  if (path.startsWith("/")) {
    return `${INTERNAL_URL}${path}`;
  }
  return `${INTERNAL_URL}/${path}`;
}

export class UrlBuilder {
  private url: URL;

  constructor(baseUrl: string) {
    try {
      this.url = new URL(baseUrl);
    } catch {
      // Handle relative URLs by prepending a base
      this.url = new URL(baseUrl, "http://placeholder.com");
    }
  }

  addParam(key: string, value: string | number | boolean): UrlBuilder {
    this.url.searchParams.set(key, String(value));
    return this;
  }

  addParams(params: Record<string, string | number | boolean>): UrlBuilder {
    Object.entries(params).forEach(([key, value]) => {
      this.url.searchParams.set(key, String(value));
    });
    return this;
  }

  toString(): string {
    // Extract just the path and query parts for relative URLs
    if (this.url.origin === "http://placeholder.com") {
      return `${this.url.pathname}${this.url.search}`;
    }
    return this.url.toString();
  }

  static fromInternalUrl(path: string): UrlBuilder {
    return new UrlBuilder(buildUrl(path));
  }

  static fromClientUrl(path: string): UrlBuilder {
    return new UrlBuilder(buildClientUrl(path));
  }
}


export async function fetchSS(url: string, options?: RequestInit) {
  const headerName =
    process.env.HEADER_AUTH_EMAIL_HEADER || "X-Auth-Email";

  // ─── HEADERS ────────────────────────────────────────────────────────────────
  const requestHeaders = await headers();          // await here
  const headerEmail = requestHeaders.get(headerName);

  // ─── COOKIES ────────────────────────────────────────────────────────────────
  const cookieStore = await cookies();             // you were already awaiting this
  const baseHeaders: Record<string, string> = {
    cookie: cookieStore
      .getAll()
      .map(({ name, value }) => `${name}=${value}`)
      .join("; "),
  };
  if (headerEmail) baseHeaders[headerName] = headerEmail;

  // ─── FETCH ─────────────────────────────────────────────────────────────────
  const init: RequestInit = {
    credentials: "include",
    cache: "no-store",
    ...(options ?? {}),
    headers: {
      ...baseHeaders,
      ...(options?.headers as Record<string, string> | undefined),
    },
  };

  return fetch(buildUrl(url), init);
}

