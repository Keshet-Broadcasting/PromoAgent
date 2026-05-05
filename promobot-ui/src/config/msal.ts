import { type Configuration, LogLevel } from '@azure/msal-browser';

const TENANT_ID = process.env.NEXT_PUBLIC_ENTRA_TENANT_ID || '';
const SPA_CLIENT_ID = process.env.NEXT_PUBLIC_ENTRA_SPA_CLIENT_ID || '';
const API_CLIENT_ID = process.env.NEXT_PUBLIC_ENTRA_API_CLIENT_ID || '';

export const API_SCOPE = `api://${API_CLIENT_ID}/Query.Read`;

export const msalConfig: Configuration = {
  auth: {
    clientId: SPA_CLIENT_ID,
    authority: `https://login.microsoftonline.com/${TENANT_ID}`,
    redirectUri: typeof window !== 'undefined' ? window.location.origin : '',
    postLogoutRedirectUri: typeof window !== 'undefined' ? window.location.origin : '',
  },
  cache: {
    cacheLocation: 'sessionStorage',
  },
  system: {
    loggerOptions: {
      logLevel: LogLevel.Warning,
      piiLoggingEnabled: false,
    },
  },
};

export const loginRequest = {
  scopes: [API_SCOPE],
};
