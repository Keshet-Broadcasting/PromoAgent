'use client';

import React, { createContext, useContext, useCallback, useEffect, useState } from 'react';
import {
  PublicClientApplication,
  InteractionRequiredAuthError,
  type AccountInfo,
} from '@azure/msal-browser';
import { msalConfig, loginRequest, API_SCOPE } from '../../config/msal';
import { User } from '../../types/chat';

interface AuthContextType {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: () => void;
  logout: () => void;
  getToken: () => Promise<string | null>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

const msalInstance = new PublicClientApplication(msalConfig);

function accountToUser(account: AccountInfo): User {
  return {
    id: account.localAccountId,
    name: account.name ?? account.username,
    email: account.username,
    roles: (account.idTokenClaims?.roles as string[]) ?? [],
  };
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const init = async () => {
      try {
        await msalInstance.initialize();
        const response = await msalInstance.handleRedirectPromise();
        if (response?.account) {
          msalInstance.setActiveAccount(response.account);
          setUser(accountToUser(response.account));
        } else {
          const accounts = msalInstance.getAllAccounts();
          if (accounts.length > 0) {
            msalInstance.setActiveAccount(accounts[0]);
            setUser(accountToUser(accounts[0]));
          }
        }
      } catch (err) {
        console.error('MSAL init error:', err);
      } finally {
        setIsLoading(false);
      }
    };
    init();
  }, []);

  const login = useCallback(async () => {
    setIsLoading(true);
    try {
      const response = await msalInstance.loginPopup(loginRequest);
      if (response?.account) {
        msalInstance.setActiveAccount(response.account);
        setUser(accountToUser(response.account));
      }
    } catch (err) {
      console.error('Login error:', err);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const logout = useCallback(() => {
    msalInstance.logoutPopup({
      postLogoutRedirectUri: window.location.origin,
      mainWindowRedirectUri: window.location.origin,
    }).then(() => {
      setUser(null);
    }).catch(console.error);
  }, []);

  const getToken = useCallback(async (): Promise<string | null> => {
    const account = msalInstance.getActiveAccount();
    if (!account) return null;
    try {
      const response = await msalInstance.acquireTokenSilent({
        scopes: [API_SCOPE],
        account,
      });
      return response.accessToken;
    } catch (err) {
      if (err instanceof InteractionRequiredAuthError) {
        try {
          const response = await msalInstance.acquireTokenPopup({ scopes: [API_SCOPE] });
          return response.accessToken;
        } catch (popupErr) {
          console.error('Popup token acquisition error:', popupErr);
          return null;
        }
      }
      console.error('Token acquisition error:', err);
      return null;
    }
  }, []);

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated: !!user,
        isLoading,
        login,
        logout,
        getToken,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
