import "@testing-library/jest-dom/vitest";

// jsdom has no layout engine, so it implements neither of these. They are real
// browser APIs the components legitimately use; stubbing them here keeps the
// gap in the test environment rather than adding defensive checks to app code
// for something every browser provides.
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}
