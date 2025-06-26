import { cookies } from "next/headers";
import { User } from "./types";
import { buildUrl, UrlBuilder } from "./utilsSS";
import { ReadonlyRequestCookies } from "next/dist/server/web/spec-extension/adapters/request-cookies";
import { AuthType, NEXT_PUBLIC_CLOUD_ENABLED } from "./constants";
import { headers } from "next/headers";

export interface AuthTypeMetadata {
  authType: AuthType;
  autoRedirect: boolean;
  requiresVerification: boolean;
  anonymousUserEnabled: boolean | null;
}

export const getAuthTypeMetadataSS = async (): Promise<AuthTypeMetadata> => {
  // Get headers from the incoming request to forward to backend
  const incomingHeaders = await headers();
  const xEmailHeader = incomingHeaders.get("X-Email") || incomingHeaders.get("x-email");
  
  // Prepare headers to send to backend
  const requestHeaders: Record<string, string> = {};
  
  // Forward X-Email header if present
  if (xEmailHeader) {
    requestHeaders["X-Email"] = xEmailHeader;
  }
  
  console.log("getAuthTypeMetadataSS - Making request to /auth/type");
  console.log("getAuthTypeMetadataSS - X-Email header to forward:", xEmailHeader || 'not present');
  
  const res = await fetch(buildUrl("/auth/type"), {
    headers: requestHeaders,
  });
  
  if (!res.ok) {
    throw new Error("Failed to fetch data");
  }

  const data: {
    auth_type: string;
    requires_verification: boolean;
    anonymous_user_enabled: boolean | null;
  } = await res.json();

  console.log("getAuthTypeMetadataSS - Response data:", data);

  let authType: AuthType;

  // Override fastapi users auth so we can use both
  if (NEXT_PUBLIC_CLOUD_ENABLED) {
    authType = "cloud";
  } else {
    authType = data.auth_type as AuthType;
  }

  // for SAML / OIDC, we auto-redirect the user to the IdP when the user visits
  // Onyx in an un-authenticated state
  if (authType === "oidc" || authType === "saml") {
    return {
      authType,
      autoRedirect: true,
      requiresVerification: data.requires_verification,
      anonymousUserEnabled: data.anonymous_user_enabled,
    };
  }

  // for bypass authentication, no special handling needed
  if (authType === "bypass") {
    return {
      authType,
      autoRedirect: false,
      requiresVerification: false, // Bypass users are auto-verified
      anonymousUserEnabled: data.anonymous_user_enabled,
    };
  }

  return {
    authType,
    autoRedirect: false,
    requiresVerification: data.requires_verification,
    anonymousUserEnabled: data.anonymous_user_enabled,
  };
};

export const getAuthDisabledSS = async (): Promise<boolean> => {
  return (await getAuthTypeMetadataSS()).authType === "disabled";
};

const getOIDCAuthUrlSS = async (nextUrl: string | null): Promise<string> => {
  const url = UrlBuilder.fromInternalUrl("/auth/oidc/authorize");
  if (nextUrl) {
    url.addParam("next", nextUrl);
  }

  const res = await fetch(url.toString());
  if (!res.ok) {
    throw new Error("Failed to fetch data");
  }

  const data: { authorization_url: string } = await res.json();
  return data.authorization_url;
};

const getGoogleOAuthUrlSS = async (nextUrl: string | null): Promise<string> => {
  const url = UrlBuilder.fromInternalUrl("/auth/oauth/authorize");
  if (nextUrl) {
    url.addParam("next", nextUrl);
  }

  const res = await fetch(url.toString(), {
    headers: {
      cookie: processCookies(await cookies()),
    },
  });
  if (!res.ok) {
    throw new Error("Failed to fetch data");
  }

  const data: { authorization_url: string } = await res.json();
  return data.authorization_url;
};

const getSAMLAuthUrlSS = async (nextUrl: string | null): Promise<string> => {
  const url = UrlBuilder.fromInternalUrl("/auth/saml/authorize");
  if (nextUrl) {
    url.addParam("next", nextUrl);
  }

  const res = await fetch(url.toString());
  if (!res.ok) {
    throw new Error("Failed to fetch data");
  }

  const data: { authorization_url: string } = await res.json();
  return data.authorization_url;
};

export const getAuthUrlSS = async (
  authType: AuthType,
  nextUrl: string | null
): Promise<string> => {
  // Returns the auth url for the given auth type

  switch (authType) {
    case "disabled":
      return "";
    case "basic":
      return "";
    case "bypass":
      return ""; // No auth URL needed for bypass, handled by header
    case "google_oauth": {
      return await getGoogleOAuthUrlSS(nextUrl);
    }
    case "cloud": {
      return await getGoogleOAuthUrlSS(nextUrl);
    }
    case "saml": {
      return await getSAMLAuthUrlSS(nextUrl);
    }
    case "oidc": {
      return await getOIDCAuthUrlSS(nextUrl);
    }
  }
};

const logoutStandardSS = async (headers: Headers): Promise<Response> => {
  return await fetch(buildUrl("/auth/logout"), {
    method: "POST",
    headers: headers,
  });
};

const logoutSAMLSS = async (headers: Headers): Promise<Response> => {
  return await fetch(buildUrl("/auth/saml/logout"), {
    method: "POST",
    headers: headers,
  });
};

export const logoutSS = async (
  authType: AuthType,
  headers: Headers
): Promise<Response | null> => {
  switch (authType) {
    case "disabled":
      return null;
    case "saml": {
      return await logoutSAMLSS(headers);
    }
    default: {
      return await logoutStandardSS(headers);
    }
  }
};

export const getCurrentUserSS = async (): Promise<User | null> => {
  try {
    const cookiesHeaders = (await cookies())
      .getAll()
      .map((cookie) => `${cookie.name}=${cookie.value}`)
      .join("; ");
    
    // Get headers from the incoming request to forward to backend
    const incomingHeaders = await headers();
    const xEmailHeader = incomingHeaders.get("X-Email") || incomingHeaders.get("x-email");
    
    console.log("getCurrentUserSS - Making request to /me");
    console.log("getCurrentUserSS - X-Email header to forward:", xEmailHeader || 'not present');
    
    // Prepare headers to send to backend
    const requestHeaders: Record<string, string> = {
      cookie: cookiesHeaders,
    };
    
    // Forward X-Email header if present
    if (xEmailHeader) {
      requestHeaders["X-Email"] = xEmailHeader;
    }
    
    const response = await fetch(buildUrl("/me"), {
      credentials: "include",
      next: { revalidate: 0 },
      headers: requestHeaders,
    });

    console.log("getCurrentUserSS - Response status:", response.status);

    if (!response.ok) {
      console.log("getCurrentUserSS - Response not ok:", await response.text());
      return null;
    }

    const user = await response.json();
    console.log("getCurrentUserSS - Success, user:", user ? `${user.email} (${user.id})` : 'null');
    return user;
  } catch (e) {
    console.log(`Error fetching user: ${e}`);
    return null;
  }
};

export const processCookies = (cookies: ReadonlyRequestCookies): string => {
  return cookies
    .getAll()
    .map((cookie) => `${cookie.name}=${cookie.value}`)
    .join("; ");
};
