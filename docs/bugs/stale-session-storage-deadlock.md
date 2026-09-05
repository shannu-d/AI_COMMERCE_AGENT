# Bug — Stale Session Storage Deadlocked Assistant Chat on Rebuilt Database

**Date:** September 5, 2026  
**Time:** 10:29:13 +0530

### Question

When the backend database is re-seeded or wiped during development, or when a stored session is claimed by another user account, how does the frontend handle the next message from an existing browser session?

### What I Expected

If the backend no longer recognizes the session ID stored in the browser's `localStorage` (answering with HTTP 404), the frontend should recognize that the session is expired/invalid, purge the dead session ID from storage, mint a fresh session, and re-send the user's message seamlessly.

### What Actually Happened

During testing after rebuilding the database, any browser that had a previously saved session ID was permanently broken. Every message typed into the chat immediately returned:
`Request failed with status code 404`
The chat was completely dead. The only workaround was opening Developer Tools and manually running `localStorage.clear()`.

### Why Was This a Problem?

This created an inescapable trap for users. If a customer's session was purged or claimed, their browser kept sending the defunct UUID on every request. Because the user has no way of knowing what a 404 or `localStorage` is, the storefront concierge became permanently non-functional on that device.

### Root Cause

In `frontend/src/features/agent/AgentRuntimeProvider.tsx`, `sendChat` read the session ID directly from storage:
```typescript
const response = await sendChat({ session_id: readSessionId(), message: text });
```
When the server responded with 404 (because `sessions` table did not contain that UUID), the runtime caught the error and displayed a generic transport failure, leaving the dead session UUID in `localStorage`. 

Crucially, the backend design deliberately answers **HTTP 404, never 403**, when a session is unknown or belongs to another user (to prevent session enumeration attacks). The frontend failed to interpret 404 as a signal that the local session ID was dead.

### Decision

We decided that when `sendChat` or `addCartItem` receives an HTTP 404 error:
1. It must treat the stored session ID as unusable (`isUnusableSession(error)`).
2. It must clear the stored session ID from `localStorage`.
3. It must retry the request exactly once with `session_id: null`, prompting the backend to mint a brand new session.
4. If the retry fails again, it must report a real error rather than entering an infinite retry loop.

### Fix

In commit `567f35d`:
1. Added `isUnusableSession(error)` in `frontend/src/session.ts` checking for `error.status === 404`.
2. Wrapped chat dispatch in `sendWithSessionRecovery()` in `frontend/src/features/agent/AgentRuntimeProvider.tsx`:
   ```typescript
   async function sendWithSessionRecovery(text: string, setSessionId: ...) {
     try {
       return await sendChat({ session_id: readSessionId(), message: text });
     } catch (error) {
       if (!isUnusableSession(error)) throw error;
       clearSessionId();
       setSessionId(null);
       return sendChat({ session_id: null, message: text });
     }
   }
   ```
3. Applied the same recovery logic in `useAddToCart.ts`.

### Verification

Automated unit tests added in `frontend/src/test/agent-runtime.test.tsx`:
- `"starts a fresh session when the backend no longer accepts the stored one"`: Asserts that an initial 404 causes `clearSessionId()` and a second request with `session_id: null`, which succeeds.
- `"reports a second refusal rather than retrying forever"`: Asserts that persistent errors do not loop infinitely.

### Result

PASS. Browser automatically recovers from invalid or stale session storage without manual user intervention.

### Evidence

- Git commit: `567f35d fix(frontend): recover from a session the backend will not accept`
- Files: [`frontend/src/features/agent/AgentRuntimeProvider.tsx`](file:///l:/AI_COMMERCE/frontend/src/features/agent/AgentRuntimeProvider.tsx), [`frontend/src/session.ts`](file:///l:/AI_COMMERCE/frontend/src/session.ts), [`frontend/src/features/catalog/useAddToCart.ts`](file:///l:/AI_COMMERCE/frontend/src/features/catalog/useAddToCart.ts)
- Regression test: [`frontend/src/test/agent-runtime.test.tsx`](file:///l:/AI_COMMERCE/frontend/src/test/agent-runtime.test.tsx#L228-L260)
