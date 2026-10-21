// Freeze time for the Node server so A/B parity runs are deterministic.
//
// Usage: node --import ./tests/parity/fake_clock.mjs index.js
//
// `HAMMERTIME_FAKE_NOW` is a local (naive) ISO timestamp, matching the Python
// clock.clock.now() test hook. When the variable is unset this module does nothing.
const fake = process.env.HAMMERTIME_FAKE_NOW;

if (fake) {
  const RealDate = Date;
  const fixed = new RealDate(fake).getTime();
  if (Number.isNaN(fixed)) {
    throw new Error(`HAMMERTIME_FAKE_NOW is not a valid date: ${fake}`);
  }

  class FakeDate extends RealDate {
    constructor(...args) {
      if (args.length === 0) super(fixed);
      else super(...args);
    }

    static now() {
      return fixed;
    }
  }

  globalThis.Date = FakeDate;
}
