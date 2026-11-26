import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { ParentRegistration } from "@/lib/api/parent";
import { AddChildLink, OpenRegistrationsCard } from "./open-registrations";

function row(over: Partial<ParentRegistration>): ParentRegistration {
  return {
    application_id: "app-1",
    child_first_name: "Lucia",
    session_id: "sess-free",
    session_title: "Wednesday Clinic",
    schedule_label: "Wed 5:00 PM",
    status: "PENDING_APPROVAL",
    state: "waiting",
    submitted_at: "2026-11-26T12:00:00Z",
    ...over,
  };
}

describe("OpenRegistrationsCard", () => {
  it("renders nothing when every registration is finished", () => {
    expect(renderToStaticMarkup(<OpenRegistrationsCard rows={[]} />)).toBe("");
  });

  it("shows a waiting child with the class and how the family hears back", () => {
    const out = renderToStaticMarkup(<OpenRegistrationsCard rows={[row({})]} />);
    expect(out).toContain("Lucia");
    expect(out).toContain("Wednesday Clinic");
    expect(out).toContain("Waiting for the academy to confirm");
    expect(out).toContain("We will email you when the academy confirms");
    expect(out).not.toContain("/parent/onboarding");
  });

  it("links an unfinished registration back into the wizard for that application", () => {
    const out = renderToStaticMarkup(
      <OpenRegistrationsCard
        rows={[row({ application_id: "app-mateo", child_first_name: "Mateo", state: "finish", status: "CHECKOUT_PENDING" })]}
      />,
    );
    expect(out).toContain("Finish registration");
    expect(out).toContain('href="/parent/onboarding?application=app-mateo"');
  });

  it("states waitlisted and declined plainly", () => {
    const out = renderToStaticMarkup(
      <OpenRegistrationsCard
        rows={[
          row({ application_id: "a", state: "waitlisted", status: "WAITLISTED" }),
          row({ application_id: "b", state: "declined", status: "DECLINED" }),
        ]}
      />,
    );
    expect(out).toContain("On the waitlist");
    expect(out).toContain("Not accepted");
  });
});

describe("AddChildLink", () => {
  it("goes to the registration wizard, not Trials", () => {
    const out = renderToStaticMarkup(<AddChildLink />);
    expect(out).toContain('href="/parent/onboarding"');
    expect(out).toContain("Add a child or enroll in a class");
  });
});
