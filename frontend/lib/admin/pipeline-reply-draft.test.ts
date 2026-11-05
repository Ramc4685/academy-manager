import { describe, expect, it } from "vitest";

import { draftToForm, replyErrorMessage } from "./pipeline-reply-draft";

describe("draftToForm", () => {
  it("prefills the editable fields and keeps non-empty key points", () => {
    expect(
      draftToForm({
        subject: " Hello ",
        body: " Thanks for asking.\n\nSam ",
        key_points: ["Juniors Saturday", " ", "free trial"],
        prompt_version: "pipeline-reply-v1",
      }),
    ).toEqual({
      subject: "Hello",
      body: "Thanks for asking.\n\nSam",
      keyPoints: ["Juniors Saturday", "free trial"],
    });
  });
});

describe("replyErrorMessage", () => {
  const err = (status: number, code?: string, message = "") => ({ status, code, message });

  it("maps each AI status to its plain sentence", () => {
    expect(replyErrorMessage(err(503, "Ai.Disabled"), "draft")).toBe(
      "AI drafting is not enabled for this academy yet",
    );
    expect(replyErrorMessage(err(403, "Ai.NotEntitled"), "draft")).toBe(
      "AI replies are part of the Growth plan",
    );
    expect(replyErrorMessage(err(429, "Ai.MonthlyCapReached"), "draft")).toBe(
      "This academy has used its AI drafts for the month",
    );
    expect(replyErrorMessage(err(502, "Ai.ProviderError"), "draft")).toBe(
      "The draft could not be read, try again",
    );
  });

  it("shows the backend's message on 409 and a fallback otherwise", () => {
    expect(
      replyErrorMessage(err(409, "Crm.PipelineReplyNotSendable", "This lead has no email address."), "send"),
    ).toBe("This lead has no email address.");
    expect(replyErrorMessage(err(500), "send")).toBe("Could not send the reply. Try again.");
    expect(replyErrorMessage(err(403, "Other"), "draft")).toBe("Could not draft a reply. Try again.");
    expect(replyErrorMessage(null, "draft")).toBe("Could not draft a reply. Try again.");
  });
});
