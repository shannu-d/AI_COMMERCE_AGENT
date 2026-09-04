import { describe, expect, it } from "vitest";

import { pickLatestTurn } from "./useAgentRecommendations";
import type { AgentTurnData } from "./agentContext";
import { aeroCase, shieldCase } from "../../test/fixtures";

/**
 * The stale-request guard.
 *
 * Runs are serialised today, so completion order equals request order and the
 * distinction never bites. This test pins the guarantee: if a slow request ever
 * finishes after a newer one, the newer request's results must still win.
 */

const turn = (seq: number, recs: AgentTurnData["recommendations"]): AgentTurnData => ({
  seq,
  state: "RECOMMENDING",
  recommendations: recs,
  error: null,
  transportError: null,
});

describe("pickLatestTurn", () => {
  it("returns undefined for no turns", () => {
    expect(pickLatestTurn([])).toBeUndefined();
  });

  it("picks the highest seq, not the last appended", () => {
    // The newer request (seq 6) completed first and was appended first; the
    // older request (seq 5) landed afterwards. Last-appended would be the stale
    // one — max(seq) is the newer.
    const newer = turn(6, [aeroCase]);
    const older = turn(5, [shieldCase]);

    expect(pickLatestTurn([newer, older])).toBe(newer);
    expect(pickLatestTurn([older, newer])).toBe(newer);
  });

  it("agrees with append order in the normal (serialised) case", () => {
    const first = turn(1, [aeroCase]);
    const second = turn(2, [shieldCase]);

    expect(pickLatestTurn([first, second])).toBe(second);
  });
});
