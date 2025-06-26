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
  // Get headers from the incoming request to forward to backend
  const incomingHeaders = await headers();
  const xEmailHeader = incomingHeaders.get("X-Email") || incomingHeaders.get("x-email");
  
  // Get cookies
  const cookieHeader = (await cookies())
    .getAll()
    .map((cookie) => `${cookie.name}=${cookie.value}`)
    .join("; ");
  
  // Prepare headers to send to backend
  const requestHeaders: Record<string, string> = {
    cookie: cookieHeader,
  };
  
  // Forward X-Email header if present
  if (xEmailHeader) {
    requestHeaders["X-Email"] = xEmailHeader;
  }
  
  // Merge with any headers provided in options
  if (options?.headers) {
    Object.assign(requestHeaders, options.headers);
  }
  
  console.log(`fetchSS - Making request to ${url}`);
  console.log(`fetchSS - X-Email header to forward:`, xEmailHeader || 'not present');
  
  const init = options || {
    credentials: "include",
    cache: "no-store",
    headers: requestHeaders,
  };
  
  // Update headers if init was provided but use our merged headers
  if (options) {
    init.headers = requestHeaders;
  }
  
  return fetch(buildUrl(url), init);
}
