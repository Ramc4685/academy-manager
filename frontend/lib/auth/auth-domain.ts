export interface AuthDomainInputs {
  configuredAuthDomain: string | undefined;
  proxyEnabled: boolean;
  pageHost: string | undefined;
}

// Proxy mode keeps Google sign-in first-party on tenant domains.
export function resolveAuthDomain(inputs: AuthDomainInputs): string | undefined {
  const { configuredAuthDomain, proxyEnabled, pageHost } = inputs;
  if (!proxyEnabled || !pageHost) return configuredAuthDomain;
  const hostname = pageHost.split(":")[0];
  if (hostname === "localhost" || hostname === "127.0.0.1") {
    return configuredAuthDomain;
  }
  return pageHost;
}
