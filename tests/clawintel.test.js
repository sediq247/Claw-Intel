import { describe, expect, it } from "vitest";
import { TestDriver } from "testdriverai/vitest/hooks";

const APP_URL = process.env.APP_URL || "https://technological-raid-estate-fan.trycloudflare.com";

describe("ClawIntel", () => {
  it("navigates through ClawIntel dashboards and tests Forensic Lab", async (context) => {
    const testdriver = TestDriver(context);

    await testdriver.provision.chrome({ url: APP_URL });

    const assertResult1 = await testdriver.assert("the ClawIntel logo and Dashboard navigation are visible");
    expect(assertResult1).toBeTruthy();

    await testdriver.find("the Markets navigation link in the top bar").click();

    const assertResult2 = await testdriver.assert("the Market Intelligence heading and market tabs are visible");
    expect(assertResult2).toBeTruthy();

    await testdriver.find("the Forensic Lab navigation link in the top bar").click();

    const assertResult3 = await testdriver.assert("the ClawIntel Lab title and token contract address input are visible");
    expect(assertResult3).toBeTruthy();

    await testdriver.find("the token contract address input field").click();
    await testdriver.type("0xdAC17F958D2ee523a2206206994597C13D831ec7");

    await testdriver.find("the INITIATE SCAN button").click();

    const assertResult4 = await testdriver.assert("the on-chain investigation progress or forensic scan results are visible");
    expect(assertResult4).toBeTruthy();

    await testdriver.find("the Records navigation link in the top bar").click();

    const assertResult5 = await testdriver.assert("the Forensics Records heading and metrics cards are visible");
    expect(assertResult5).toBeTruthy();
  });
});
