import { request, type FullConfig } from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";

import { E2E_USER as E2E_CREDENTIALS } from "./support";

const E2E_USER = {
  ...E2E_CREDENTIALS,
  name: "Playwright User",
};

export default async function globalSetup(config: FullConfig): Promise<void> {
  const baseURL = config.projects[0]?.use.baseURL;
  if (typeof baseURL !== "string") {
    throw new Error("Playwright baseURL is required for E2E setup");
  }

  const storageState = config.projects[0]?.use.storageState;
  if (typeof storageState !== "string") {
    throw new Error("Playwright storageState path is required for E2E setup");
  }
  const authStatePath = storageState;
  await fs.mkdir(path.dirname(authStatePath), { recursive: true });

  const context = await request.newContext({ baseURL });
  const registerResponse = await context.post("/api/auth/register", {
    data: E2E_USER,
  });

  if (!registerResponse.ok() && registerResponse.status() !== 400) {
    throw new Error(
      `Failed to create E2E user: ${registerResponse.status()} ${await registerResponse.text()}`,
    );
  }

  if (registerResponse.status() === 400) {
    const loginResponse = await context.post("/api/auth/login", {
      data: {
        email: E2E_USER.email,
        password: E2E_USER.password,
      },
    });
    if (!loginResponse.ok()) {
      throw new Error(
        `Failed to log in E2E user: ${loginResponse.status()} ${await loginResponse.text()}`,
      );
    }
  }

  await context.storageState({ path: authStatePath });
  await context.dispose();
}
