'use client';

import React, { createContext, useContext, useState, useEffect } from 'react';
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

export function AuthProvider({ children }: { children: React.ReactNode }) {
  // Mock state for Entra ID authentication
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    // Simulate checking for existing session
    const checkSession = async () => {
      setTimeout(() => {
        // For development, auto-login
        setUser({
          id: '1',
          name: 'משתמש פרומו',
          email: 'promo.user@company.com',
          roles: ['PromoTeam'],
        });
        setIsLoading(false);
      }, 500);
    };

    checkSession();
  }, []);

  const login = () => {
    setIsLoading(true);
    setTimeout(() => {
      setUser({
        id: '1',
        name: 'משתמש פרומו',
        email: 'promo.user@company.com',
        roles: ['PromoTeam'],
      });
      setIsLoading(false);
    }, 1000);
  };

  const logout = () => {
    setUser(null);
  };

  const getToken = async () => {
    // In a real MSAL implementation, this would call acquireTokenSilent
    return user ? 'mock-jwt-token' : null;
  };

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
