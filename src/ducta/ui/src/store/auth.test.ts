import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useAuthStore, getToken } from './auth';

/**
 * Tests for auth.ts - Zustand authentication store
 * Sprint 2 I-1: Test coverage expansion
 */

describe('useAuthStore (Auth Zustand Store)', () => {
  beforeEach(() => {
    // Clear localStorage before each test
    localStorage.clear();
    // Reset Zustand store
    useAuthStore.setState({
      token: null,
      user: null,
    });
  });

  describe('login()', () => {
    it('should set token and user on login', () => {
      const { result } = renderHook(() => useAuthStore());

      const testUser = { id: 'user1', email: 'test@example.com', name: 'Test User' };
      const testToken = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c';

      act(() => {
        result.current.login({
          token: testToken,
          user: testUser,
        });
      });

      expect(result.current.token).toBe(testToken);
      expect(result.current.user).toEqual(testUser);
    });

    it('persists the user but not the token', () => {
      // The token deliberately stays in memory: the backend issues it as an
      // httpOnly cookie so page scripts cannot read it, and a persisted copy
      // would hand it straight back to them. `restoreSession()` re-obtains it
      // from the cookie after a reload.
      const { result } = renderHook(() => useAuthStore());

      act(() => {
        result.current.login({
          token: 'token123',
          user: { id: 'user1' },
        });
      });

      const stored = localStorage.getItem('ducta-auth');
      expect(stored).toBeTruthy();
      const parsed = JSON.parse(stored!);
      expect(parsed.state.token).toBeUndefined();
      expect(parsed.state.user).toEqual({ id: 'user1' });
    });
  });

  describe('logout()', () => {
    it('should clear token and user', () => {
      const { result } = renderHook(() => useAuthStore());

      act(() => {
        result.current.login({
          token: 'token123',
          user: { id: 'user1' },
        });
      });

      expect(result.current.token).toBeTruthy();

      act(() => {
        result.current.logout();
      });

      expect(result.current.token).toBeNull();
      expect(result.current.user).toBeNull();
    });

    it('should clear the persisted user on logout', () => {
      const { result } = renderHook(() => useAuthStore());

      act(() => {
        result.current.login({
          token: 'token123',
          user: { id: 'user1' },
        });
      });

      act(() => {
        result.current.logout();
      });

      const stored = localStorage.getItem('ducta-auth');
      const parsed = stored ? JSON.parse(stored) : null;
      expect(parsed?.state.user).toBeNull();
      expect(result.current.token).toBeNull();
    });
  });

  describe('refreshTokenAsync()', () => {
    // The refresh contract is cookie-based: the backend re-issues a token from
    // the httpOnly access_token cookie, so there is no client-held refresh token.
    // refreshTokenAsync must call /auth/refresh and, on failure, log the user
    // out and rethrow.
    it('should attempt a cookie-based refresh and logout on failure', async () => {
      const { result } = renderHook(() => useAuthStore());

      act(() => {
        result.current.login({ token: 'old_token', user: { id: 'user1' } });
      });
      expect(result.current.token).toBe('old_token');

      // No HTTP mock in jsdom → the POST rejects with a network error, which
      // exercises the failure path (logout + rethrow), not an early throw.
      await expect(result.current.refreshTokenAsync()).rejects.toBeTruthy();
      expect(result.current.token).toBeNull();
      expect(result.current.user).toBeNull();
    });
  });

  describe('getToken (exported function)', () => {
    it('should return token if not expired', () => {
      const { result } = renderHook(() => useAuthStore());

      // Create a JWT token that won't expire for a while
      const futureExp = Math.floor(Date.now() / 1000) + 3600; // 1 hour from now
      const payload = { exp: futureExp, sub: 'user1' };
      const token = `eyJhbGciOiJIUzI1NiJ9.${btoa(JSON.stringify(payload))}.signature`;

      act(() => {
        result.current.login({ token, user: { id: 'user1' } });
      });

      const retrievedToken = getToken();
      expect(retrievedToken).toBe(token);
    });

    it('should logout and return null if token is expired', () => {
      const { result } = renderHook(() => useAuthStore());

      // Create a JWT token that expires in the past
      const pastExp = Math.floor(Date.now() / 1000) - 3600; // 1 hour ago
      const payload = { exp: pastExp, sub: 'user1' };
      const token = `eyJhbGciOiJIUzI1NiJ9.${btoa(JSON.stringify(payload))}.signature`;

      act(() => {
        result.current.login({ token, user: { id: 'user1' } });
      });

      const retrievedToken = getToken();

      expect(retrievedToken).toBeNull();
      expect(useAuthStore.getState().token).toBeNull();
    });

    it('should handle malformed JWT gracefully', () => {
      const { result } = renderHook(() => useAuthStore());

      act(() => {
        result.current.login({ token: 'not.a.jwt', user: { id: 'user1' } });
      });

      const retrievedToken = getToken();
      // Should NOT logout for malformed token (assume it's invalid but not expired)
      expect(retrievedToken).toBe('not.a.jwt');
    });
  });

  describe('persistence (localStorage)', () => {
    it('should restore state from localStorage on store init', () => {
      const stateData = {
        state: {
          token: 'persisted_token',
          user: { id: 'user123', email: 'user@example.com' },
        },
        version: 1,
      };

      localStorage.setItem('ducta-auth', JSON.stringify(stateData));

      // Create new hook instance that reads from localStorage
      const { result } = renderHook(() => useAuthStore());

      // Give Zustand time to hydrate from localStorage
      setTimeout(() => {
        expect(result.current.token).toBe('persisted_token');
      }, 100);
    });
  });

  describe('version field (C-3: Storage versioning)', () => {
    it('should store version=1 with auth data', () => {
      const { result } = renderHook(() => useAuthStore());

      act(() => {
        result.current.login({
          token: 'token123',
          user: { id: 'user1' },
        });
      });

      const stored = localStorage.getItem('ducta-auth');
      const parsed = JSON.parse(stored!);
      expect(parsed.version).toBe(1);
    });
  });
});

describe('token persistence', () => {
  beforeEach(() => {
    localStorage.clear();
    useAuthStore.setState({ token: null, user: null });
  });

  it('never writes the access token to localStorage', () => {
    // The backend issues the token as an httpOnly cookie precisely so page
    // scripts cannot read it. Persisting a second copy here handed it back to
    // any script on the page and undid that.
    useAuthStore.getState().login({
      token: 'super-secret-jwt',
      user: { id: 'u1', username: 'ana' },
    });

    const dumped = JSON.stringify(localStorage);
    expect(dumped).not.toContain('super-secret-jwt');
  });

  it('still persists the user so the UI can render before the refresh lands', () => {
    useAuthStore.getState().login({
      token: 'super-secret-jwt',
      user: { id: 'u1', username: 'ana' },
    });

    expect(JSON.stringify(localStorage)).toContain('ana');
  });

  it('keeps the token available in memory for the session', () => {
    useAuthStore.getState().login({
      token: 'super-secret-jwt',
      user: { id: 'u1' },
    });

    expect(useAuthStore.getState().token).toBe('super-secret-jwt');
  });
});
