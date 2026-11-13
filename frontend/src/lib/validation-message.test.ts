import { describe, expect, it } from "vitest";

import { looksLikeEmail, validationMessage } from "./validation-message";

describe("validationMessage", () => {
  it("turns email validator output into plain language", () => {
    expect(validationMessage(["body", "email"], "value is not a valid email address: An email address must have an @-sign.")).toBe(
      "Enter a valid email address, like name@example.com.",
    );
  });
  it("drops pydantic's prefix and labels the field", () => {
    expect(validationMessage(["body", "new_password"], "Value error, Password must be at least 10 characters")).toBe(
      "New password: Password must be at least 10 characters",
    );
    expect(validationMessage(["body", "items", 0, "quantity"], "Input should be greater than 0")).toBe("Quantity: Input should be greater than 0");
  });
  it("works without a field", () => {
    expect(validationMessage(undefined, "Something is off")).toBe("Something is off");
  });
});

describe("looksLikeEmail", () => {
  it.each([["name@example.com", true], ["  name@example.com ", true], ["not-an-email", false], ["nobody@", false], ["a b@c.d", false]])(
    "%s -> %s",
    (value, expected) => expect(looksLikeEmail(value)).toBe(expected),
  );
});
