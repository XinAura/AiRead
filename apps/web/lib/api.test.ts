import { describe, expect, it } from "vitest";

import { ApiError, audioStreamUrl } from "./api";

describe("API client helpers", () => {
  it("builds a stable audio part streaming URL", () => {
    expect(audioStreamUrl("part-123")).toBe(
      "http://127.0.0.1:8000/audio-parts/part-123/stream",
    );
  });

  it("keeps HTTP status on API errors", () => {
    const error = new ApiError(416, "无效范围");
    expect(error.status).toBe(416);
    expect(error.message).toBe("无效范围");
  });
});
