// Drive the renderer's clock and endpoint conditions independently of agent timing.
const assert = require("node:assert/strict");

module.exports = async function checkAnimations(browser, url) {
  const context = await browser.newContext({ viewport: {width: 1000, height: 700} });
  try {
    const page = await context.newPage();
    await page.clock.install();
    await page.addInitScript(() => {
      window.EventSource = class { constructor() { window.stream = this; } };
      const battery = Object.assign(new EventTarget(), { charging: true, level: 1 });
      Object.defineProperty(navigator, "getBattery", {value: async () => battery});
      window.battery = battery;
    });
    await page.goto(url);
    await page.waitForFunction(() => !!window.stream?.onmessage);
    let sequence = 0;
    const send = m => page.evaluate(msg => window.stream.onmessage({data: JSON.stringify(msg)}),
      {version: 1, sequence: ++sequence, ...m});
    let session = {id: "a", order: 0, activity: "idle", attention: "none", active_calls: 0, helpers: 0};
    const update = (changes, moment) => {
      session = {...session, ...changes};
      return send({type: "update", session, moment});
    };
    const el = page.locator('.pet[data-session="a"]');
    async function pose(name) {
      assert.equal(await el.getAttribute("data-pose"), name);
      await el.locator(":scope > img").evaluate(img => img.decode());
    }
    await send({type:"snapshot", sessions:[]});
    await update({});
    await pose("wake");
    await page.clock.runFor(12500);
    await pose("coffee");
    await page.clock.runFor(12000);
    await pose("groove");
    await page.clock.runFor(12000);
    await pose("hat");
    await update({activity:"working"});
    await pose("working");
    await page.clock.runFor(10500);
    await pose("thinking");
    await page.clock.runFor(10000);
    await pose("pushing");
    await update({active_calls:2, helpers:1});
    await pose("parallel");
    assert.equal(await el.locator(".companion").isVisible(), true);
    await update({active_calls:1, activity:"building"});
    await pose("building");
    await update({activity:"transferring"});
    await pose("transferring");
    await page.setViewportSize({width:420, height:700});
    await page.waitForFunction(() => document.querySelector(".pet").dataset.pose === "compact_work");
    await pose("compact_work");
    await page.setViewportSize({width:1000, height:700});
    await update({}, "setback");
    await pose("setback");
    await update({}, "setback");
    await pose("overheated");
    await update({attention:"approval"});
    await pose("approval");
    await update({attention:"ready", activity:"idle"}, "completed");
    await pose("completed");
    await update({attention:"none", activity:"working"});
    await update({attention:"ready", activity:"idle"}, "completed");
    await pose("eureka");
    await update({attention:"none", helpers:0, active_calls:0});
    await page.evaluate(() => { battery.charging=false; battery.level=.12; battery.dispatchEvent(new Event("levelchange")); });
    await pose("low_power");
    await page.emulateMedia({reducedMotion:"reduce"});
    await page.waitForFunction(() => document.querySelector(".pet").dataset.pose === "still");
    await pose("still");
    await page.emulateMedia({reducedMotion:"no-preference"});
    await page.evaluate(() => window.stream.onerror());
    await pose("offline");
    await send({type:"snapshot", sessions:[session]});
    for (const [index,id] of ["b","c","d"].entries()) {
      await send({type:"update", session:{...session, id, order:index+1, attention:"approval"}});
    }
    assert.equal(await page.locator(".leaving.walking").count(), 1);
    await send({type:"update", session, moment:"forked"});
    assert.equal(await page.locator("#overflow .fork-flash").count(), 1);
    await page.clock.runFor(1600);
    await send({type:"remove", id:"b"});
    await pose("walking");
    await page.clock.runFor(3500);
    await send({type:"remove", id:"a"});
    assert.equal(await page.locator(".leaving.departing").count(), 1);
    await page.clock.runFor(3500);
    assert.equal(await page.locator(".leaving").count(), 0);
  } finally {
    await context.close();
  }
};
