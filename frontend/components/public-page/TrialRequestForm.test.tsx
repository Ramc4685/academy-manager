import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { TrialRequestForm } from "./TrialRequestForm";
import { TrialSection } from "./TrialSection";

function render(overrides: Partial<Parameters<typeof TrialRequestForm>[0]> = {}): string {
  return renderToStaticMarkup(
    <TrialRequestForm
      academyName="Riverside Shuttle Club"
      classOptions={[{ value: "c_open", label: "Starters Saturday, Sat 9:00" }]}
      privacyNoticeUrl={null}
      variant="trial"
      {...overrides}
    />,
  );
}

/** The opening tag of the (single) control named `name`. */
function control(html: string, name: string): string {
  const tag = new RegExp(`<(input|select|textarea)[^>]*name="${name}"[^>]*>`).exec(html)?.[0];
  expect(tag, `control ${name}`).toBeTruthy();
  return tag!;
}

function attr(tag: string, attribute: string): string | null {
  return new RegExp(`\\s${attribute}="([^"]*)"`).exec(tag)?.[1] ?? null;
}

describe("TrialRequestForm markup", () => {
  it("labels every visible control and marks required ones", () => {
    const html = render();
    for (const [name, label] of [
      ["name", "Your name"],
      ["email", "Email"],
      ["phone", "Phone"],
      ["player_age", "Player"],
      ["class_id", "Class"],
      ["message", "Anything the coach should know"],
      ["contact_about_request", "Riverside Shuttle Club may contact me"],
      ["marketing_opt_in", "Also send me news"],
    ]) {
      const id = attr(control(html, name), "id");
      expect(id).toBeTruthy();
      expect(html).toMatch(new RegExp(`<label for="${id}">${label}`));
    }
    for (const name of ["name", "email", "player_age", "contact_about_request"]) {
      expect(attr(control(html, name), "aria-required")).toBe("true");
    }
    expect(attr(control(html, "phone"), "aria-required")).toBeNull();
  });

  it("ties the age hint to its input and never asks for the child's name", () => {
    const html = render();
    const hintId = /<p class="[^"]*" id="([^"]+)">We do not ask for the player/.exec(html)?.[1];
    expect(hintId).toBeTruthy();
    expect(attr(control(html, "player_age"), "aria-describedby")).toBe(hintId);
    expect(html).not.toMatch(/child_name|child's name/i);
  });

  it("hides the honeypot from people and assistive technology", () => {
    const html = render();
    const honeypot = control(html, "website");
    expect(attr(honeypot, "tabindex")).toBe("-1");
    const wrapper =
      /<div class="([^"]*)" aria-hidden="true"><label[^>]*>Leave this field empty/.exec(html);
    expect(wrapper).not.toBeNull();
    expect(wrapper![1]).toMatch(/honeypot/);
  });

  it("offers consent to be contacted (required) and marketing (off by default)", () => {
    const html = render();
    expect(html).toContain("Riverside Shuttle Club may contact me about this request.");
    expect(html).toContain("Also send me news and offers from Riverside Shuttle Club");
    expect(attr(control(html, "marketing_opt_in"), "checked")).toBeNull();
  });

  it("links the academy's privacy notice, falling back to the platform page", () => {
    expect(render()).toContain('href="/privacy"');
    expect(render({ privacyNoticeUrl: "https://riverside.example.test/privacy" })).toContain(
      'href="https://riverside.example.test/privacy"',
    );
    // Only https links are rendered as a target.
    expect(render({ privacyNoticeUrl: "javascript:alert(1)" })).not.toContain("javascript:");
  });

  it("has a polite live region and no error summary before a submit", () => {
    const html = render();
    expect(html).toMatch(/aria-live="polite"/);
    expect(html).not.toContain("trial-error-summary");
  });

  it("changes the call to action by variant and drops the class select when none are listed", () => {
    expect(render()).toContain("Request a free trial");
    expect(render({ variant: "waitlist" })).toContain("Join the waitlist");
    const notify = render({ variant: "notify", classOptions: [] });
    expect(notify).toContain("Tell me when classes open");
    expect(notify).not.toContain('name="class_id"');
  });
});

describe("TrialSection slot", () => {
  it("renders the form only while trials are open", () => {
    const form = (
      <TrialRequestForm
        academyName="Riverside Shuttle Club"
        classOptions={[]}
        privacyNoticeUrl={null}
        variant="trial"
      />
    );
    const open = renderToStaticMarkup(
      <TrialSection
        academyName="Riverside Shuttle Club"
        trialsOpen
        hasClasses
        allFull={false}
        form={form}
      />,
    );
    expect(open).toContain('data-testid="trial-request-form"');
    const closed = renderToStaticMarkup(
      <TrialSection
        academyName="Riverside Shuttle Club"
        trialsOpen={false}
        hasClasses
        allFull={false}
        form={form}
      />,
    );
    expect(closed).not.toContain('data-testid="trial-request-form"');
    expect(closed).toContain("Free trials are paused right now");
  });
});
